"""Synthetic input for software checks; does not model USB camera or RF performance."""
import cv2
import numpy as np
import time
from app import config
from app.state import state
from hardware.camera import CameraManager

class DemoCamera(CameraManager):
    def _run(self):
        self.generation=1
        state.camera_size=f'{config.CAMERA_WIDTH}x{config.CAMERA_HEIGHT}'
        due=time.monotonic()
        while not self.stop_event.is_set():
            frame=np.zeros((config.CAMERA_HEIGHT,config.CAMERA_WIDTH,3),dtype=np.uint8)
            frame[:]=(45,40,32)
            x=int((time.monotonic()*60)%(config.CAMERA_WIDTH-80))
            cv2.rectangle(frame,(x,config.CAMERA_HEIGHT//2),(x+60,config.CAMERA_HEIGHT//2+70),(70,210,170),-1)
            cv2.putText(frame,'DVP SOFTWARE DEMO - NOT LIVE',(90,130),cv2.FONT_HERSHEY_SIMPLEX,0.7,(240,240,240),2)
            self._publish(frame)
            state.camera_fps=config.CAMERA_FPS
            due+=1/config.CAMERA_FPS
            self.stop_event.wait(max(0,due-time.monotonic()))
        with self.lock:
            self.latest=None

