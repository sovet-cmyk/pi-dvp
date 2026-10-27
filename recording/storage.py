import queue
import shutil
import threading
import time
from app import config
from app.state import state, notify
from system.logger import logger

class StorageManager:
    def __init__(self,missions):
        self.missions = missions
        self.stop_event = threading.Event()
        self.requests = queue.SimpleQueue()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run,name='storage',daemon=True)
        self.thread.start()

    def request_delete_oldest(self):
        self.requests.put('oldest')

    def check(self):
        free = shutil.disk_usage(self.missions.root).free/1024**3
        state.free_gb = free
        low = free<config.STORAGE_WARN_GB
        if low and not state.storage_low:
            notify(f"Low storage: {free:.1f} GB. Tap S for options",10)
        state.storage_low = low
        if config.AUTO_DELETE_OLDEST and free<config.STORAGE_DELETE_GB:
            while free<config.STORAGE_TARGET_GB and not self.stop_event.is_set():
                if not self.missions.delete_oldest():
                    break
                free = shutil.disk_usage(self.missions.root).free/1024**3
                state.free_gb = free

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.check()
                while not self.requests.empty():
                    self.requests.get()
                    name = self.missions.delete_oldest()
                    notify(f"Deleted {name}" if name else "No unprotected completed mission to delete",6)
                    self.check()
            except Exception:
                logger.exception("Storage check failed")
            self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
