"""UDisks mounting and transactional, verified exports on a background worker."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import uuid
from app import config
from app.state import state, notify
from system.logger import logger

@dataclass(frozen=True)
class Drive:
    device: str
    identity: str
    label: str
    mount: str | None
    disk: str

def mounts(node):
    value = node.get('mountpoints',node.get('mountpoint'))
    if not value:
        return []
    return [p for p in (value if isinstance(value,list) else [value]) if p]

def discover_drives(tree,protected_paths=()):
    """Only filesystems on USB disks; reject the whole disk containing system/data paths."""
    result = []
    def system_disk(node):
        for mount in mounts(node):
            if mount in ('/','/boot','/boot/firmware'):
                return True
            if any(Path(p).resolve().is_relative_to(Path(mount).resolve()) for p in protected_paths):
                return True
        return any(system_disk(c) for c in node.get('children',[]))
    def walk(node,disk,is_usb):
        is_usb = is_usb or node.get('tran')=='usb'
        readonly = node.get('ro') in (True,1,'1')
        if is_usb and not readonly and node.get('fstype') in ('vfat','exfat','ntfs','ntfs3','ext4','ext3','ext2','f2fs'):
            locations = mounts(node)
            result.append(Drive(node['name'],node.get('uuid') or node['name'],
                                node.get('label') or Path(node['name']).name,
                                locations[0] if locations else None,disk))
        for child in node.get('children',[]):
            walk(child,disk,is_usb)
    for node in tree.get('blockdevices',[]):
        if not system_disk(node):
            walk(node,node['name'],False)
    return sorted(result,key=lambda d:d.device)

def run_command(args):
    done = subprocess.run(args,text=True,capture_output=True,timeout=20)
    if done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip()[:250])
    return done.stdout

def copy_snapshot(sources,mount,verify=True,cancel=None,progress=None,validate=None):
    """Never overwrite an existing export. Return only after files are closed and synced."""
    mount = Path(mount)
    source_files = []
    for source in sources:
        if source.is_symlink():
            raise RuntimeError("Refusing to export a symlinked mission")
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise RuntimeError("A mission contains a symlink; refusing export")
            if path.is_file() and not path.name.endswith(('.partial.mp4','.tmp')):
                source_files.append((path,Path(source.name)/path.relative_to(source)))
    if not source_files:
        raise RuntimeError("No completed recordings to export")
    total = sum(p.stat().st_size for p,_ in source_files)
    if shutil.disk_usage(mount).free < total+32*1024**2:
        raise RuntimeError("USB drive has insufficient free space")
    if validate:
        validate()
    # Anchor subsequent writes to the opened mount, not to its path after an unplug/unmount.
    fd = os.open(mount,os.O_RDONLY|os.O_DIRECTORY)
    tag = datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    name = 'DVP_Export_'+tag
    anchor = Path('/proc/self/fd')/str(fd) if Path('/proc/self/fd').exists() else mount
    temporary = anchor/('.'+name+'.partial')
    completed = 0
    manifest = []
    try:
        temporary.mkdir()
        for source,relative in source_files:
            if cancel and cancel():
                raise RuntimeError("Export cancelled")
            if validate:
                validate()
            dest = temporary/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with open(source,'rb') as src,open(dest,'xb') as dst:
                while True:
                    if cancel and cancel():
                        raise RuntimeError("Export cancelled")
                    if validate:
                        validate()
                    chunk = src.read(1024*1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    completed += len(chunk)
                    if progress:
                        progress(90*completed/max(1,total))
                dst.flush()
                os.fsync(dst.fileno())
            if size != source.stat().st_size:
                raise RuntimeError("Source changed during export")
            if verify:
                copied = hashlib.sha256()
                with open(dest,'rb') as check:
                    while chunk := check.read(1024*1024):
                        if cancel and cancel():
                            raise RuntimeError("Export cancelled")
                        if validate:
                            validate()
                        copied.update(chunk)
                if copied.digest()!=digest.digest():
                    raise RuntimeError("USB checksum verification failed")
            manifest.append({'file':relative.as_posix(),'bytes':size,'sha256':digest.hexdigest()})
        with open(temporary/'export_manifest.json','x',encoding='utf-8') as f:
            json.dump({'application':'DVP','verified':verify,'files':manifest},f,indent=2)
            f.flush()
            os.fsync(f.fileno())
        with open(temporary/'EXPORT_COMPLETE.txt','x',encoding='utf-8') as f:
            f.write('DVP export completed and verified.\n')
            f.write('The source recordings remain stored in DVP.\n')
            f.flush()
            os.fsync(f.fileno())
        if validate:
            validate()
        temporary.rename(anchor/name)
        try:
            os.fsync(fd)
        except OSError:
            # Some removable filesystems reject directory fsync; individual files were synced.
            pass
        if progress:
            progress(100)
        return mount/name
    except Exception:
        # Retain only this operation's clearly labelled partial directory for diagnosis/retry.
        # A later export creates a new unique directory and never removes prior user content.
        raise
    finally:
        os.close(fd)

class USBMonitor:
    def __init__(self,missions,recorder):
        self.missions,self.recorder = missions,recorder
        self.stop_event = threading.Event()
        self.commands = queue.Queue(maxsize=4)
        self.drive = None
        self.drives = []
        self.ejected_disk = None
        self.mount_attempts = {}
        self.last_key = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run,name='usb-export',daemon=True)
        self.thread.start()

    def request(self,command):
        if state.export_busy:
            notify('Export in progress - wait or cancel',3)
            return
        try:
            self.commands.put_nowait(command)
        except queue.Full:
            notify('USB operation already queued',3)

    def scan(self):
        raw = run_command(['lsblk','-J','-p','-o','NAME,TYPE,TRAN,RM,RO,MOUNTPOINTS,FSTYPE,UUID,LABEL'])
        tree = json.loads(raw)
        drives = discover_drives(tree,(config.DATA_DIR,config.PROJECT_ROOT))
        disks = {d.disk for d in drives}
        if self.ejected_disk and self.ejected_disk not in disks:
            self.ejected_disk = None
            state.usb_safe_to_remove = False
            state.usb_export_error = False
        drives = [d for d in drives if d.disk != self.ejected_disk]
        self.drives = drives
        now = time.monotonic()
        connected_devices = {d.device for d in drives}
        self.mount_attempts = {k:v for k,v in self.mount_attempts.items() if k in connected_devices}
        mounted = [d for d in drives if d.mount and os.path.ismount(d.mount)]
        if not mounted and config.USB_AUTOMOUNT:
            for d in drives:
                if not d.mount and now-self.mount_attempts.get(d.device,-100)>15:
                    self.mount_attempts[d.device] = now
                    try:
                        run_command(['udisksctl','mount','--block-device',d.device,'--no-user-interaction'])
                    except Exception as exc:
                        notify('USB mount failed - see log',5)
                        logger.warning('USB mount failed for %s: %s',d.device,exc)
                    # Re-read the authoritative mount path on the next scan; never parse guessed /media paths.
        self.drive = mounted[0] if mounted else None
        state.usb_connected = self.drive is not None
        state.usb_label = self.drive.label if self.drive else ''
        key = (self.drive.device,self.drive.identity,self.drive.mount) if self.drive else None
        if self.last_key and not key and not self.ejected_disk:
            # Keep usb_last_result so the display can report the outcome when it
            # is reconnected after using the shared external connector.
            state.usb_export_error = False
        if key and key != self.last_key:
            state.usb_safe_to_remove = False
            state.usb_export_error = False
            state.usb_last_result = ''
            notify('USB detected - automatic export starting',8)
            if config.AUTO_USB_EXPORT:
                self.request('all')
        self.last_key = key

    def _export(self,latest):
        drive = self.drive
        if not drive or not drive.mount:
            raise RuntimeError('No mounted USB drive')
        state.export_busy = True
        state.export_cancel = False
        state.export_progress = 0
        state.usb_last_result = ''
        protected = []
        mount = Path(drive.mount)
        try:
            original_dev = mount.stat().st_dev
            def validate():
                if not os.path.ismount(mount) or mount.stat().st_dev != original_dev:
                    raise RuntimeError('USB drive removed or unmounted')
            # Queue boundary closes the active file/mission without stopping live capture.
            protected = self.missions.pin_export_candidates()
            self.recorder.boundary(wait=True)
            sources = self.missions.pin_completed(latest=latest)
            protected = list(set(protected) | set(sources))
            if not sources:
                raise RuntimeError('No completed mission to export')
            notify('Exporting recordings - do not unplug USB',3600)
            target = copy_snapshot(sources,mount,config.VERIFY_EXPORT,
                cancel=lambda:self.stop_event.is_set() or state.export_cancel,
                progress=lambda p:setattr(state,'export_progress',p),validate=validate)
            logger.info('Export complete: %s',target.name)
            state.usb_last_result = 'copied'
            notify('Export copied and verified',10)
            return target
        finally:
            self.missions.unpin(protected)
            state.export_busy = False

    def _eject(self):
        if not self.drive:
            raise RuntimeError('No USB drive to eject')
        disk = self.drive.disk
        # Unmount every filesystem and suppress remounting until physical removal.
        for d in self.drives:
            if d.disk==disk and d.mount:
                run_command(['udisksctl','unmount','--block-device',d.device,'--no-user-interaction'])
        self.ejected_disk = disk
        self.drive = None
        state.usb_connected = False
        logger.info('USB unmounted; waiting for physical removal: %s',disk)
        notify('USB unmounted - safe to remove',10)

    def _safe_to_remove(self,export_complete=False):
        state.usb_safe_to_remove = True
        state.usb_export_error = False
        state.usb_last_result = 'complete' if export_complete else 'ejected'
        notify('USB EXPORT COMPLETE - SAFE TO REMOVE' if export_complete else
               'USB SAFE TO REMOVE',10)

    def _run(self):
        scan_due = 0.0
        while not self.stop_event.is_set():
            if time.monotonic()>=scan_due:
                try:
                    self.scan()
                except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
                    logger.warning('USB scan unavailable: %s',exc)
                scan_due = time.monotonic()+config.USB_SCAN_SECONDS
            try:
                command = self.commands.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.scan()
                if command in ('latest','all'):
                    self._export(command=='latest')
                    if config.AUTO_USB_EJECT:
                        self._eject()
                        self._safe_to_remove(export_complete=True)
                elif command=='eject':
                    self._eject()
                    self._safe_to_remove(export_complete=state.usb_last_result=='copied')
            except Exception as exc:
                logger.exception('USB operation failed')
                state.usb_export_error = True
                state.usb_safe_to_remove = False
                state.usb_last_result = 'failed'
                notify(str(exc)[:90],10)

    def stop(self):
        self.stop_event.set()
        state.export_cancel = True
        if self.thread:
            self.thread.join(timeout=25)
            return not self.thread.is_alive()
        return True
