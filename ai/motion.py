import time
import cv2
from app import config
from app.state import state

class MotionDetector:
    def __init__(self):
        self.previous = None
        self.last_motion = -100.0

    def reset(self):
        self.previous = None
        self.last_motion = -100.0
        state.motion_detected = state.scene_moving = False

    def detect(self, frame):
        if not state.motion_enabled:
            self.reset()
            return
        h,w = frame.shape[:2]
        small = cv2.resize(frame,(config.MOTION_WIDTH,max(2,round(h*config.MOTION_WIDTH/w))))
        gray = cv2.GaussianBlur(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY),(5,5),0)
        if self.previous is None or self.previous.shape != gray.shape:
            self.previous = gray
            return
        mask = cv2.threshold(cv2.absdiff(gray,self.previous),config.MOTION_PIXEL_THRESHOLD,255,cv2.THRESH_BINARY)[1]
        self.previous = gray
        fraction = cv2.countNonZero(mask)/mask.size
        state.scene_moving = fraction > config.MOTION_GLOBAL_FRACTION
        if state.scene_moving:
            # Suppress widespread change (camera motion / lighting). Not full stabilization.
            self.last_motion = -100.0
        else:
            mask = cv2.dilate(mask,None,iterations=1)
            contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if any(cv2.contourArea(c)>=config.MOTION_MIN_AREA for c in contours):
                self.last_motion = time.monotonic()
        state.motion_detected = time.monotonic()-self.last_motion < config.MOTION_HOLD_SECONDS
