"""Receive authenticated wireless touch events over UDP, with serial fallback."""
import hmac
import json
import math
import queue
import socket
import threading
import time
from app import config
from app.state import state
from system.logger import logger

MAX_MESSAGE_BYTES = 512
MAX_SEQUENCE = 0xffffffff
POWEROFF_REPEATS = 5
POWEROFF_GAP_SECONDS = 0.04
ALLOWED_COMMANDS = {'ZOOM_IN','ZOOM_OUT','UP','DOWN','LEFT','RIGHT','CENTER',
                    'MOTION','HUMAN','UI','RECORD_MODE','STORAGE','POWER'}


def parse_message(payload, shared_key=None, require_session=False):
    """Validate one JSON message and remove its transport key before queuing."""
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError('Message too long')
    if isinstance(payload, bytes):
        payload = payload.decode('utf-8')
    message = json.loads(payload)
    if not isinstance(message, dict):
        raise ValueError('Expected an object')
    supplied_key = message.pop('key', None)
    if shared_key is not None:
        if not isinstance(supplied_key, str) or not hmac.compare_digest(supplied_key, shared_key):
            raise ValueError('Authentication failed')
    kind = message.get('type')
    session = message.get('session')
    if kind == 'hello':
        if not isinstance(session, str) or not 1 <= len(session) <= 64:
            raise ValueError('Invalid session')
    elif require_session and (not isinstance(session, str) or not 1 <= len(session) <= 64):
        raise ValueError('Missing session')
    sequence = message.get('seq')
    if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int)
                                 or not 0 <= sequence <= MAX_SEQUENCE):
        raise ValueError('Invalid sequence')
    if kind == 'hello':
        return message
    if kind == 'heartbeat':
        return message
    if kind == 'command' and isinstance(message.get('command'), str) and message['command'] in ALLOWED_COMMANDS:
        return message
    if kind == 'touch' and message.get('event') in ('down','move','up'):
        for axis in ('x','y'):
            value = message.get(axis)
            if (isinstance(value, bool) or not isinstance(value, (int,float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError('Touch coordinates must be normalized to 0..1')
        return message
    raise ValueError('Unsupported message')


class TouchBridge:
    def __init__(self):
        self.events = queue.Queue(maxsize=64)
        self.stop_event = threading.Event()
        self.thread = None
        self.sock = None
        self.bound_port = None
        self.last_sequence = None
        self.session = None
        self.peer = None

    def start(self):
        mode = config.TOUCH_MODE
        if mode == 'off':
            state.touch_status = 'LOCAL'
            return
        state.touch_status = 'WAIT'
        target = self._run_udp if mode == 'udp' else self._run_serial
        self.thread = threading.Thread(target=target, name='touch-'+mode, daemon=True)
        self.thread.start()

    def _enqueue(self, message):
        try:
            self.events.put_nowait(message)
        except queue.Full:
            # Discard stale actions and force-release any held UI control.
            while True:
                try:
                    self.events.get_nowait()
                except queue.Empty:
                    break
            self.events.put_nowait({'type':'release'})

    def drain(self):
        events = []
        while True:
            try:
                events.append(self.events.get_nowait())
            except queue.Empty:
                return events

    def request_remote_poweroff(self):
        """Tell the authenticated DVP touch peer to shut down cleanly."""
        if config.TOUCH_MODE != 'udp':
            logger.info('Remote poweroff skipped: touch transport is not UDP')
            return False
        sock, peer, session = self.sock, self.peer, self.session
        if sock is None or peer is None or session is None:
            logger.warning('Remote poweroff skipped: no authenticated touch peer')
            return False
        payload = json.dumps({
            'type':'poweroff',
            'session':session,
            'key':config.TOUCH_SHARED_KEY,
        }, separators=(',',':')).encode('utf-8')
        sent = 0
        destination = (peer[0], peer[1])
        for attempt in range(POWEROFF_REPEATS):
            try:
                sock.sendto(payload, destination)
                sent += 1
            except OSError as exc:
                logger.warning('Could not send remote poweroff request: %s', exc)
                break
            if attempt + 1 < POWEROFF_REPEATS:
                time.sleep(POWEROFF_GAP_SECONDS)
        if sent:
            logger.info('Sent authenticated DVP poweroff request to %s:%d (%d copies)',
                        destination[0], destination[1], sent)
        return sent > 0

    def _accept(self, message, peer=None, network=False):
        """Apply session/sequence rules, then queue UI events."""
        now = time.monotonic()
        kind = message['type']
        if kind == 'hello':
            new_session = message['session'] != self.session or (network and peer != self.peer)
            if new_session:
                self.session = message['session']
                self.peer = peer
                self.last_sequence = None
                self._enqueue({'type':'release'})
            state.touch_last_seen = now
            state.touch_status = 'OK'
            return True
        if network and (self.session is None or message.get('session') != self.session or peer != self.peer):
            return False
        sequence = message.get('seq')
        if network and sequence is None:
            return False
        if sequence is not None:
            if self.last_sequence is not None and sequence <= self.last_sequence:
                return False
            self.last_sequence = sequence
        state.touch_last_seen = now
        state.touch_status = 'OK'
        if kind != 'heartbeat':
            message['received_at'] = now
            self._enqueue(message)
        return True

    def _mark_lost(self):
        if state.touch_status == 'OK':
            self._enqueue({'type':'release'})
        state.touch_status = 'LOST'
        self.last_sequence = None
        self.session = None
        self.peer = None

    def _check_timeout(self):
        if (state.touch_status == 'OK'
                and time.monotonic() - state.touch_last_seen > config.TOUCH_TIMEOUT_SECONDS):
            self._mark_lost()

    def _run_udp(self):
        while not self.stop_event.is_set():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    self.sock = sock
                    sock.settimeout(min(0.15, config.TOUCH_TIMEOUT_SECONDS / 2))
                    sock.bind((config.TOUCH_UDP_BIND, config.TOUCH_UDP_PORT))
                    self.bound_port = sock.getsockname()[1]
                    logger.info('Touch UDP listening on %s:%d', config.TOUCH_UDP_BIND, self.bound_port)
                    while not self.stop_event.is_set():
                        try:
                            payload, peer = sock.recvfrom(MAX_MESSAGE_BYTES + 1)
                            if len(payload) > MAX_MESSAGE_BYTES:
                                continue
                            try:
                                message = parse_message(payload, config.TOUCH_SHARED_KEY, require_session=True)
                            except (ValueError, UnicodeError, json.JSONDecodeError):
                                continue
                            self._accept(message, peer, network=True)
                        except socket.timeout:
                            pass
                        self._check_timeout()
            except OSError as exc:
                if self.stop_event.is_set():
                    break
                state.touch_status = 'PORT ERR'
                self._enqueue({'type':'release'})
                logger.warning('Touch UDP receiver unavailable: %s', exc)
                self.stop_event.wait(2)
            finally:
                self.sock = None
                self.bound_port = None

    def _run_serial(self):
        try:
            import serial
        except ImportError:
            state.touch_status = 'NO DRIVER'
            logger.error('pyserial is not installed')
            return
        while not self.stop_event.is_set():
            try:
                with serial.Serial(config.TOUCH_SERIAL_PORT, config.TOUCH_BAUD, timeout=0.15) as port:
                    self.last_sequence = None
                    self.session = None
                    buf = bytearray()
                    discard = False
                    while not self.stop_event.is_set():
                        block = port.read(min(1024, max(1, port.in_waiting)))
                        for byte in block:
                            if byte == 10:
                                if not discard:
                                    try:
                                        self._accept(parse_message(bytes(buf)))
                                    except (ValueError, UnicodeError, json.JSONDecodeError):
                                        pass
                                buf.clear()
                                discard = False
                            elif not discard:
                                buf.append(byte)
                                if len(buf) > MAX_MESSAGE_BYTES:
                                    discard = True
                        self._check_timeout()
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                state.touch_status = 'WAIT'
                self._enqueue({'type':'release'})
                logger.warning('Touch serial receiver unavailable: %s', exc)
                self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        sock = self.sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=3)
