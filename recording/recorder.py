"""Bounded background encoder; capture timestamps determine the playback timeline."""
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import numpy as np
from app import config
from app.state import state, notify
from system.logger import logger

class Timeline:
    """Resample capture timestamps to CFR, duplicating explicitly rather than speeding up."""
    def __init__(self,fps,write):
        self.fps,self.write = fps,write
        self.origin = None
        self.index = -1
        self.previous = None
        self.duplicates = self.frames = self.skipped = 0

    def push(self,stamp,frame):
        if self.origin is None:
            self.origin = stamp
        target = round((stamp-self.origin)*self.fps)
        if target <= self.index:
            self.skipped += 1
            return
        while self.index+1 < target:
            self.write(self.previous)
            self.index += 1
            self.frames += 1
            self.duplicates += 1
        self.write(frame)
        self.index = target
        self.frames += 1
        self.previous = frame

class VideoRecorder:
    def __init__(self,missions):
        self.missions = missions
        self.condition = threading.Condition()
        self.queue = deque()
        self.accepting = True
        self.thread = None
        self.process = self.stderr = self.timeline = None
        self.path = None
        self.mode = None
        self.shape = None
        self.last_stamp = self.segment_stamp = 0.0
        self.retry_after = 0.0
        self.duplicate_total = 0
        self.segment_counter = 0
        self.last_space_check = 0.0
        self.session_fault = False

    def start(self):
        self.thread = threading.Thread(target=self._run,name="recorder",daemon=True)
        self.thread.start()

    def submit(self,frame,stamp,mode):
        if not config.ENABLE_RECORDING or not self.accepting:
            return
        with self.condition:
            if not self.accepting:
                return
            if sum(x[0]=='frame' for x in self.queue) >= config.RECORD_QUEUE_FRAMES:
                for i,item in enumerate(self.queue):
                    if item[0]=='frame':
                        del self.queue[i]
                        state.record_dropped += 1
                        break
            # OpenCV capture returns a new frame; producers must not modify submitted arrays.
            self.queue.append(('frame',stamp,frame,mode))
            self.condition.notify()

    def boundary(self,wait=False):
        event = threading.Event()
        result = {}
        with self.condition:
            if not self.accepting:
                return None
            self.queue.append(('close',event,result))
            self.condition.notify()
        if wait:
            if not event.wait(20):
                raise TimeoutError("Recording did not close in time; export cancelled")
            if result.get('error'):
                raise RuntimeError(result['error'])
            return result.get('folder')

    def _space_check(self):
        if shutil.disk_usage(self.missions.root).free < config.RECORD_MIN_FREE_MB*1024**2:
            raise OSError("Recording paused: insufficient free space")

    def _open(self,frame,stamp,mode):
        self._space_check()
        new_mission = self.missions.current is None
        folder = self.missions.start(mode)
        self.segment_counter += 1
        name = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+f'_{mode}'
        self.path = folder/(name+'.partial.mp4')
        self.stderr = open(config.LOGS_DIR/'encoder.log','wb')
        h,w = frame.shape[:2]
        if w%2 or h%2:
            raise ValueError("H.264 recording needs even frame dimensions")
        cmd = ['ffmpeg','-hide_banner','-loglevel','warning','-nostdin','-y',
               '-f','rawvideo','-pixel_format','bgr24','-video_size',f'{w}x{h}',
               '-framerate',str(config.RECORD_FPS),'-i','pipe:0','-an',
               '-c:v','libx264','-preset','ultrafast','-tune','zerolatency',
               '-crf',str(config.RECORD_CRF),'-threads',str(config.ENCODER_THREADS),
               '-pix_fmt','yuv420p','-g',str(config.RECORD_FPS),
               '-movflags','+frag_keyframe+empty_moov+default_base_moof',
               '-f','mp4',str(self.path)]
        self.process = subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=self.stderr)
        self.timeline = Timeline(config.RECORD_FPS,self._write)
        self.mode,self.shape = mode,frame.shape
        self.last_stamp = self.segment_stamp = stamp
        self.wall_start = datetime.now(timezone.utc).isoformat()
        self.segment_drop_start = state.record_dropped
        state.recording = True
        state.record_error = ""
        logger.info("Recording %s",self.path.name)
        if new_mission:
            notify('RECORDING STARTED - WITH UI' if mode=='ui' else
                   'RECORDING STARTED - RAW CAMERA',5)

    def _write(self,frame):
        self.process.stdin.write(np.ascontiguousarray(frame).tobytes())

    def _close_segment(self):
        ok = True
        try:
            if self.process:
                try:
                    self.process.stdin.close()
                except BrokenPipeError:
                    ok = False
                try:
                    code = self.process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
                    code = -1
                ok = ok and code==0 and self.path.is_file() and self.path.stat().st_size>0
                if ok:
                    final = self.path.with_name(self.path.name.replace('.partial.mp4','.mp4'))
                    with open(self.path,'rb') as f:
                        os.fsync(f.fileno())
                    self.path.replace(final)
                    self.missions.add_segment({"file":final.name,"started_utc":self.wall_start,
                        "mode":self.mode,"width":self.shape[1],"height":self.shape[0],
                        "fps":config.RECORD_FPS,"frames":self.timeline.frames,
                        "duration_seconds":self.timeline.frames/config.RECORD_FPS,
                        "capture_span_seconds":self.last_stamp-self.segment_stamp,
                        "duplicated_frames":self.timeline.duplicates,
                        "same_slot_skips":self.timeline.skipped,
                        "queue_drops":state.record_dropped-self.segment_drop_start})
                else:
                    self.session_fault = True
                    state.record_error = "ENCODER ERROR"
                    notify("Recording error - partial file retained",8)
                self.duplicate_total += self.timeline.duplicates
        except Exception as exc:
            ok = False
            self.session_fault = True
            state.record_error = "Recording close failed: " + str(exc)[:50]
            logger.exception("Could not finalize recording")
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=3)
        finally:
            if self.stderr:
                self.stderr.close()
            self.stderr = self.process = self.timeline = None
            state.recording = False
        return ok

    def _finish(self):
        ok = self._close_segment() and not self.session_fault
        folder = self.missions.finish('finished' if ok else 'interrupted')
        self.session_fault = False
        if not ok:
            raise RuntimeError("Recording could not be finalized; partial files retained")
        return folder

    def _run(self):
        while True:
            with self.condition:
                while not self.queue:
                    self.condition.wait(timeout=0.5)
                    if self.process and time.monotonic()-self.last_stamp > config.CAMERA_STALE_SECONDS:
                        break
                item = self.queue.popleft() if self.queue else ('idle',)
            if item[0] in ('close','stop'):
                _,event,result = item
                try:
                    result['folder'] = self._finish()
                except Exception as exc:
                    result['error'] = str(exc)
                    state.record_error = str(exc)[:70]
                    logger.exception("Recording close failed")
                event.set()
                if item[0]=='stop':
                    return
                continue
            if item[0]=='idle':
                if self.process and time.monotonic()-self.last_stamp > config.CAMERA_STALE_SECONDS:
                    try:
                        self._finish()
                    except Exception as exc:
                        state.record_error = str(exc)[:70]
                        logger.exception("Idle recording close failed")
                continue
            _,stamp,frame,mode = item
            if time.monotonic()<self.retry_after:
                continue
            try:
                if self.process and (mode != self.mode or frame.shape != self.shape or stamp-self.last_stamp > config.RECORD_MAX_GAP_SECONDS):
                    self._finish()
                if self.process and stamp-self.segment_stamp >= config.RECORD_SEGMENT_SECONDS:
                    self._close_segment()
                if self.process is None:
                    self._open(frame,stamp,mode)
                if time.monotonic()-self.last_space_check>1:
                    self._space_check()
                    self.last_space_check = time.monotonic()
                self.timeline.push(stamp,frame)
                self.last_stamp = stamp
                state.record_duplicates = self.duplicate_total+self.timeline.duplicates
            except Exception as exc:
                logger.exception("Recording paused: %s",exc)
                state.record_error = str(exc)[:70]
                notify(state.record_error,8)
                try:
                    self._finish()
                except Exception:
                    logger.exception("Recorder recovery failed")
                self.retry_after = time.monotonic()+5

    def stop(self):
        if self.thread is None:
            self.accepting = False
            return True
        event,result = threading.Event(),{}
        with self.condition:
            self.accepting = False
            self.queue.append(('stop',event,result))
            self.condition.notify()
        if not event.wait(22):
            # Break a blocked encoder pipe; mark shutdown unsafe rather than claiming success.
            if self.process:
                self.process.kill()
            logger.error("Encoder shutdown timed out")
            return False
        if self.thread:
            self.thread.join(timeout=2)
        # A previous recoverable error (for example low space) is not an open file.
        return not bool(result.get('error')) and not self.thread.is_alive()
