"""One USB camera, continuously drained into a latest-frame slot."""
from dataclasses import dataclass
import sys
import threading
import time
import cv2
from app import config
from app.state import state
from system.logger import logger

@dataclass(frozen=True)
class FramePacket:
    sequence: int
    timestamp: float
    generation: int
    frame: object

class CameraManager:
    def __init__(self,on_frame=None,on_disconnect=None):
        self.on_frame = on_frame
        self.on_disconnect = on_disconnect
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest = None
        self.sequence = 0
        self.generation = 0
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run,name="camera",daemon=True)
        self.thread.start()

    def get_latest(self):
        with self.lock:
            packet = self.latest
        if packet and time.monotonic()-packet.timestamp <= config.CAMERA_STALE_SECONDS:
            return packet
        return None

    def _publish(self,frame):
        self.sequence += 1
        packet = FramePacket(self.sequence,time.monotonic(),self.generation,frame)
        with self.lock:
            self.latest = packet
        if self.on_frame:
            self.on_frame(packet)

    def _run(self):
        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        while not self.stop_event.is_set():
            cap = None
            connected = False
            try:
                for fourcc in dict.fromkeys((config.CAMERA_FOURCC,"MJPG","YUYV")):
                    candidate = cv2.VideoCapture(config.CAMERA_DEVICE,backend)
                    if not candidate.isOpened():
                        candidate.release()
                        break
                    candidate.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*fourcc))
                    candidate.set(cv2.CAP_PROP_FRAME_WIDTH,config.CAMERA_WIDTH)
                    candidate.set(cv2.CAP_PROP_FRAME_HEIGHT,config.CAMERA_HEIGHT)
                    candidate.set(cv2.CAP_PROP_FPS,config.CAMERA_FPS)
                    candidate.set(cv2.CAP_PROP_BUFFERSIZE,1)
                    ok,first = candidate.read()
                    if ok and first is not None:
                        cap = candidate
                        break
                    candidate.release()
                if cap is None:
                    self.stop_event.wait(config.RECONNECT_SECONDS)
                    continue
                self.generation += 1
                connected = True
                state.camera_size = f"{first.shape[1]}x{first.shape[0]}"
                logger.info("USB camera connected: %s, format=%s, negotiated FPS=%.1f",
                            state.camera_size,fourcc,cap.get(cv2.CAP_PROP_FPS))
                self._publish(first)
                count,started = 0,time.monotonic()
                while not self.stop_event.is_set():
                    ok,frame = cap.read()
                    if not ok or frame is None:
                        break
                    self._publish(frame)
                    count += 1
                    elapsed = time.monotonic()-started
                    if elapsed >= 1:
                        state.camera_fps = count/elapsed
                        count,started = 0,time.monotonic()
            except Exception:
                logger.exception("Camera worker failed; reconnecting")
            finally:
                if cap is not None:
                    cap.release()
                with self.lock:
                    self.latest = None
                state.camera_fps = 0.0
                if connected and self.on_disconnect:
                    self.on_disconnect()
            self.stop_event.wait(config.RECONNECT_SECONDS)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                logger.warning("Camera driver read has not returned; live image watchdog is active")

