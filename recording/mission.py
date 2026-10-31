"""Owned mission folders, atomic metadata, and pins protecting in-flight exports."""
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from app import config
from app.state import state
from system.logger import logger

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def atomic_json(path, data):
    temp = path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)

class MissionManager:
    def __init__(self,root=None):
        self.root = Path(root or config.RECORDINGS_DIR).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock = threading.RLock()
        self.current = None
        self.meta = None
        self.pinned = set()

    def folders(self):
        return sorted((p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()
                       and re.fullmatch(r"Mission_\d+",p.name)),key=lambda p:int(p.name.split('_')[1]))

    def start(self,mode):
        with self.lock:
            if self.current is not None:
                return self.current
            folders = self.folders()
            number = int(folders[-1].name.split('_')[1])+1 if folders else 1
            while True:
                folder = self.root/f"Mission_{number:04d}"
                try:
                    folder.mkdir()
                    break
                except FileExistsError:
                    number += 1
            self.current = folder
            self.meta = {"application":"DVP", "version":config.VERSION, "started_utc":utc_now(),
                         "status":"active", "record_mode":mode,"segments":[]}
            atomic_json(folder/'mission.json',self.meta)
            state.current_mission = folder.name
            return folder

    def add_segment(self,metadata):
        with self.lock:
            self.meta['segments'].append(metadata)
            atomic_json(self.current/'mission.json',self.meta)

    def finish(self,status="finished"):
        with self.lock:
            folder = self.current
            if folder:
                self.meta.update(status=status,ended_utc=utc_now())
                atomic_json(folder/'mission.json',self.meta)
                self.current = self.meta = None
                state.current_mission = ""
            return folder

    def completed(self):
        with self.lock:
            result = []
            for p in self.folders():
                if p == self.current:
                    continue
                try:
                    meta = json.loads((p/'mission.json').read_text())
                    if meta.get('application')=='DVP' and meta.get('status')=='finished' and meta.get('segments'):
                        result.append(p)
                except (OSError,ValueError):
                    continue
            return result

    def pin_completed(self,latest=False):
        with self.lock:
            paths = self.completed()
            if latest:
                paths = paths[-1:]
            self.pinned.update(paths)
            return paths

    def pin_export_candidates(self):
        """Protect the active mission BEFORE asking the recorder to finish it."""
        with self.lock:
            paths = self.completed()
            if self.current:
                paths.append(self.current)
            self.pinned.update(paths)
            return paths

    def unpin(self,paths):
        with self.lock:
            self.pinned.difference_update(paths)

    def delete_oldest(self):
        with self.lock:
            for p in self.completed():
                if p in self.pinned:
                    continue
                # Do not follow a symlink, delete a user-supplied path, or erase an active mission.
                if p.parent != self.root or p.is_symlink():
                    continue
                shutil.rmtree(p)
                logger.warning("Deleted completed mission %s",p.name)
                return p.name
        return None

    @staticmethod
    def _folder_size(folder):
        total = 0
        for path in folder.rglob('*'):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    def completed_info(self):
        """Return safe, operator-facing details for completed recording sessions."""
        with self.lock:
            result = []
            for folder in reversed(self.completed()):
                try:
                    meta = json.loads((folder/'mission.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    meta = {}
                result.append({
                    'name': folder.name,
                    'ended_utc': str(meta.get('ended_utc') or meta.get('started_utc') or ''),
                    'size_bytes': self._folder_size(folder),
                    'protected': folder in self.pinned,
                })
            return result

    def delete_selected(self, names):
        """Delete only exact, completed, unpinned mission names selected in the UI."""
        requested = {str(name) for name in names}
        deleted = []
        with self.lock:
            completed = {path.name:path for path in self.completed()}
            for name in sorted(requested):
                path = completed.get(name)
                if (path is None or path in self.pinned or path == self.current
                        or path.parent != self.root or path.is_symlink()):
                    continue
                shutil.rmtree(path)
                deleted.append(name)
                logger.warning("Deleted selected completed mission %s", name)
        return deleted
