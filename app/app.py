import time
import numpy as np
from app import config
from app.state import state,notify
from ai.detection import DetectionWorker
from ai.motion import MotionDetector
from hardware.camera import CameraManager
from hardware.ina226 import INA226Monitor
from hardware.touch_bridge import TouchBridge
from hardware.usb import USBMonitor
from hardware.zoom import make_view,map_boxes
from recording.mission import MissionManager
from recording.recorder import VideoRecorder
from recording.storage import StorageManager
from system.logger import logger

class DVPApplication:
    def __init__(self,camera_type=CameraManager,enable_usb=True):
        self.missions=MissionManager()
        self.recorder=VideoRecorder(self.missions)
        self.storage=StorageManager(self.missions)
        self.detector=DetectionWorker()
        self.motion=MotionDetector()
        self.bridge=TouchBridge()
        self.battery=INA226Monitor()
        self.usb=USBMonitor(self.missions,self.recorder)
        self.camera=camera_type(self._on_frame,self._on_disconnect)
        self.enable_usb=enable_usb
        self.accepting=True
        self.last_sequence=0
        self.last_generation=0
        self.last_ui_record_sequence=0
        self.view_count=0
        self.fps_start=time.monotonic()
        self.telemetry_due=0.0
        self.log_due=0.0
        self.blank=np.zeros((config.DISPLAY_HEIGHT,config.DISPLAY_WIDTH,3),dtype=np.uint8)
        self.started=False

    def startup(self):
        self.started=True
        self.recorder.start()
        self.storage.start()
        self.detector.start()
        self.bridge.start()
        if self.enable_usb:
            self.usb.start()
        self.camera.start()
        logger.info('DVP %s started. Camera USB; display HDMI; record mode %s',config.VERSION,state.record_mode)

    def _on_frame(self,packet):
        if not self.accepting:
            return
        self.detector.submit(packet)
        if state.record_mode=='raw':
            self.recorder.submit(packet.frame,packet.timestamp,'raw')

    def _on_disconnect(self):
        if self.accepting:
            self.recorder.boundary()
            self.detector.clear()
            notify('RECORDING STOPPED - CAMERA DISCONNECTED',8)

    def update(self):
        now=time.monotonic()
        packet=self.camera.get_latest()
        was_connected=state.camera_connected
        state.camera_connected=packet is not None
        if packet is None:
            if was_connected:
                self._on_disconnect()
                self.motion.reset()
            state.camera_fps=state.display_fps=0.0
            self.view_count=0
            self.fps_start=now
            view,boxes=self.blank,[]
        else:
            if packet.generation != self.last_generation:
                self.motion.reset()
                self.last_generation=packet.generation
            if packet.sequence != self.last_sequence:
                state.preview_skips += max(0,packet.sequence-self.last_sequence-1) if self.last_sequence else 0
                self.last_sequence=packet.sequence
                self.view_count += 1
                self.motion.detect(packet.frame)
            view,transform=make_view(packet.frame)
            boxes=map_boxes(self.detector.latest(packet.generation),transform)
        elapsed=now-self.fps_start
        if elapsed>=1:
            state.display_fps=self.view_count/elapsed
            self.view_count=0
            self.fps_start=now
        if now>=self.telemetry_due:
            self.telemetry_due=now+2
            self._telemetry()
        if now>=self.log_due:
            self.log_due=now+30
            battery=('unavailable' if (not state.battery_available or
                     state.battery_voltage is None or state.battery_current is None) else
                     f'{state.battery_voltage:.3f}V {state.battery_current:.3f}A {state.battery_bars}/4')
            logger.info('Metrics capture=%.1ffps preview=%.1ffps inference=%.0fms record_drops=%d duplicates=%d preview_skips=%d free=%.2fGB battery=%s',
                state.camera_fps,state.display_fps,state.ai_ms,state.record_dropped,
                state.record_duplicates,state.preview_skips,state.free_gb,battery)
        return packet,view,boxes

    def record_display(self,packet,display):
        if state.record_mode=='ui' and packet and packet.sequence!=self.last_ui_record_sequence:
            self.recorder.submit(display,packet.timestamp,'ui')
            self.last_ui_record_sequence=packet.sequence

    def _telemetry(self):
        if not self.enable_usb:
            state.battery_available=False
            return
        sample=self.battery.read()
        state.battery_available=sample is not None
        if sample is not None:
            state.battery_bars=sample.bars
            state.battery_voltage=sample.voltage
            state.battery_current=sample.current

    def shutdown(self):
        self.accepting=False
        self.bridge.stop()
        self.camera.stop()
        usb_ok=self.usb.stop()
        self.battery.close()
        self.detector.stop()
        self.storage.stop()
        recording_ok=self.recorder.stop() if self.started else True
        logger.info('Stopped; recordings closed=%s, USB worker stopped=%s',recording_ok,usb_ok)
        return recording_ok and usb_ok

