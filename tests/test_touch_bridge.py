"""Touch receiver tests that need only the Python standard library."""
import json
import os
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

_test_data = tempfile.TemporaryDirectory(prefix='dvp-touch-tests-')
os.environ['DVP_DATA_DIR'] = _test_data.name

from app import config
from app.state import state, State
from hardware.touch_bridge import parse_message, TouchBridge


def wait_for(predicate, seconds=3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for touch receiver')


class TouchBridgeTests(unittest.TestCase):
    def setUp(self):
        state.__dict__.update(State().__dict__)

    def test_parser_auth_coordinates_and_key_removal(self):
        message = {'type':'touch','event':'down','x':.25,'y':.75,
                   'session':'boot-a','seq':1,'key':'correct-secret'}
        parsed = parse_message(json.dumps(message), 'correct-secret', require_session=True)
        self.assertNotIn('key', parsed)
        with self.assertRaisesRegex(ValueError, 'Authentication'):
            parse_message(json.dumps(message), 'wrong-secret', require_session=True)
        for x, y in ((-0.1,.5),(1.1,.5),(.5,float('nan'))):
            bad = dict(message, x=x, y=y)
            with self.assertRaises(ValueError):
                parse_message(json.dumps(bad), 'correct-secret', require_session=True)

    def test_udp_session_sequence_auth_and_timeout_release(self):
        bridge = TouchBridge()
        key = 'test-secret-at-least-16'
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with patch.object(config,'TOUCH_MODE','udp'), \
             patch.object(config,'TOUCH_UDP_BIND','127.0.0.1'), \
             patch.object(config,'TOUCH_UDP_PORT',0), \
             patch.object(config,'TOUCH_SHARED_KEY',key), \
             patch.object(config,'TOUCH_TIMEOUT_SECONDS',.2):
            bridge.start()
            try:
                wait_for(lambda: bridge.bound_port is not None)
                destination = ('127.0.0.1', bridge.bound_port)
                def send(message):
                    sender.sendto(json.dumps(message,separators=(',',':')).encode(), destination)
                send({'type':'hello','session':'boot-a','seq':0,'key':'wrong'})
                time.sleep(.05)
                self.assertNotEqual(state.touch_status, 'OK')
                send({'type':'hello','session':'boot-a','seq':0,'key':key})
                send({'type':'touch','event':'down','x':.1,'y':.2,
                      'session':'boot-a','seq':1,'key':key})
                send({'type':'touch','event':'move','x':.2,'y':.2,
                      'session':'boot-a','seq':1,'key':key})
                send({'type':'touch','event':'up','x':.1,'y':.2,
                      'session':'old-boot','seq':2,'key':key})
                send({'type':'heartbeat','session':'boot-a','seq':2,'key':key})
                wait_for(lambda: bridge.last_sequence == 2)
                events = bridge.drain()
                self.assertEqual(sum(x.get('event') == 'down' for x in events), 1)
                self.assertFalse(any(x.get('event') in ('move','up') for x in events))
                wait_for(lambda: state.touch_status == 'LOST')
                self.assertTrue(any(x['type'] == 'release' for x in bridge.drain()))
            finally:
                bridge.stop()
                sender.close()
            self.assertFalse(bridge.thread.is_alive())

    def test_remote_poweroff_returns_to_authenticated_radxa_peer(self):
        key = 'test-secret-at-least-16'
        radxa = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        radxa.bind(('127.0.0.1', 0))
        radxa.settimeout(1)
        bridge = TouchBridge()
        bridge.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bridge.sock.bind(('127.0.0.1', 0))
        bridge.peer = radxa.getsockname()
        bridge.session = 'radxa-current-boot'
        with patch.object(config, 'TOUCH_MODE', 'udp'), \
             patch.object(config, 'TOUCH_SHARED_KEY', key), \
             patch('hardware.touch_bridge.POWEROFF_REPEATS', 2), \
             patch('hardware.touch_bridge.POWEROFF_GAP_SECONDS', 0):
            try:
                self.assertTrue(bridge.request_remote_poweroff())
                messages = [json.loads(radxa.recv(512)) for _ in range(2)]
            finally:
                bridge.sock.close()
                radxa.close()
        self.assertTrue(all(message == {
            'type':'poweroff', 'session':'radxa-current-boot', 'key':key
        } for message in messages))

    def test_remote_poweroff_without_peer_does_not_block_pi_shutdown(self):
        bridge = TouchBridge()
        with patch.object(config, 'TOUCH_MODE', 'udp'):
            self.assertFalse(bridge.request_remote_poweroff())


if __name__ == '__main__':
    unittest.main()
