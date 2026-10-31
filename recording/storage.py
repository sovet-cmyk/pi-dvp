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

    def refresh_items(self):
        items = self.missions.completed_info()
        state.storage_items = items
        valid = {item['name'] for item in items if not item['protected']}
        state.storage_selected.intersection_update(valid)
        pages = max(1, (len(items)+3)//4)
        state.storage_page = min(max(0,state.storage_page), pages-1)
        return items

    def request_delete_selected(self,names):
        self.requests.put(('selected',tuple(names)))

    def check(self):
        free = shutil.disk_usage(self.missions.root).free/1024**3
        state.free_gb = free
        low = free<config.STORAGE_WARN_GB
        if low and not state.storage_low:
            notify(f"Low storage: {free:.1f} GB. Tap S for options",10)
        state.storage_low = low
        if state.dialog in ('storage','delete_confirm'):
            self.refresh_items()
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
                    request = self.requests.get()
                    if isinstance(request,tuple) and request[0]=='selected':
                        deleted = self.missions.delete_selected(request[1])
                        state.storage_selected.clear()
                        if deleted:
                            notify(f"DELETED {len(deleted)} RECORDING"+('S' if len(deleted)!=1 else ''),6)
                        else:
                            notify("NO SELECTED RECORDINGS COULD BE DELETED",6)
                    else:
                        name = self.missions.delete_oldest()
                        notify(f"Deleted {name}" if name else "No unprotected completed mission to delete",6)
                    self.refresh_items()
                    self.check()
            except Exception:
                logger.exception("Storage check failed")
            self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
