"""One latest-frame worker; inference never queues old frames or blocks the UI."""
import threading
import time
from app import config
from app.state import state, notify
from ai.inference import InferenceEngine
from system.logger import logger

class DetectionWorker:
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = None
        self.result = (0.0,0,[])
        self.stopping = False
        self.thread = None
        self.generation = 0

    def start(self):
        self.thread = threading.Thread(target=self._run,name="human",daemon=True)
        self.thread.start()

    def submit(self, packet):
        with self.condition:
            self.pending = packet
            self.condition.notify()

    def clear(self):
        with self.condition:
            self.generation += 1
            self.pending = None
            self.result = (0.0,0,[])

    def latest(self, camera_generation):
        with self.condition:
            stamp, generation, boxes = self.result
        if not state.human_enabled or generation != camera_generation or time.monotonic()-stamp > config.DETECTION_TTL_SECONDS:
            return []
        return boxes

    def _run(self):
        try:
            engine = InferenceEngine()
            state.ai_ready = True
            state.ai_status = "READY"
        except Exception as exc:
            state.ai_status = "UNAVAILABLE"
            logger.exception("Human detection unavailable: %s",exc)
            notify("Human model unavailable - see log",8)
            return
        due = 0.0
        while True:
            with self.condition:
                while not self.stopping and (self.pending is None or not state.human_enabled or time.monotonic()<due):
                    self.condition.wait(timeout=max(0.01,min(0.2,due-time.monotonic())) if time.monotonic()<due else 0.2)
                if self.stopping:
                    break
                packet,self.pending = self.pending,None
                generation = self.generation
            try:
                boxes,elapsed = engine.infer(packet.frame)
                state.ai_ms = elapsed
                state.ai_ready = True
                state.ai_status = "READY"
                with self.condition:
                    if generation == self.generation and state.human_enabled:
                        self.result = (packet.timestamp,packet.generation,boxes)
            except Exception:
                logger.exception("Inference failed")
                self.clear()
                state.ai_ready = False
                state.ai_status = "ERROR"
            due = time.monotonic()+1/config.AI_MAX_FPS

    def stop(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=5)
