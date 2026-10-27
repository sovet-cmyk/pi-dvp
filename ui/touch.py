import time
import cv2
from app import config
from app.state import state, notify

REPEATABLE={'ZOOM_IN','ZOOM_OUT','UP','DOWN','LEFT','RIGHT'}

class TouchHandler:
    def __init__(self,ui,app):
        self.ui,self.app=ui,app
        self.output_w,self.output_h=ui.w,ui.h
        self.held=None
        self.remote=False
        self.repeat_due=0.0
        self.last_touch=0.0

    def set_output_size(self,width,height):
        self.output_w=max(1,int(width))
        self.output_h=max(1,int(height))

    def local_to_logical(self,x,y):
        return (x*self.ui.w/self.output_w,y*self.ui.h/self.output_h)

    def release(self):
        self.held=None

    def at(self,x,y):
        for name,(x1,y1,x2,y2) in self.ui.rects().items():
            if x1<=x<x2 and y1<=y<y2:
                return name
        return None

    def press(self,x,y,remote=False):
        self.release()
        command=self.at(x,y)
        if command:
            self.execute(command)
            if command in REPEATABLE:
                self.held=command
                self.remote=remote
                self.last_touch=time.monotonic()
                self.repeat_due=self.last_touch+0.4

    def mouse_callback(self,event,x,y,flags,param):
        x,y=self.local_to_logical(x,y)
        if event==cv2.EVENT_LBUTTONDOWN:
            self.press(x,y)
        elif event==cv2.EVENT_LBUTTONUP:
            self.release()
        elif event==cv2.EVENT_MOUSEMOVE and self.held:
            if not flags & cv2.EVENT_FLAG_LBUTTON or self.at(x,y)!=self.held:
                self.release()

    def remote_message(self,message):
        kind=message['type']
        if kind in ('command','touch') and time.monotonic()-message.get('received_at',time.monotonic())>config.TOUCH_TIMEOUT_SECONDS:
            self.release()
            return
        if kind=='release':
            self.release()
        elif kind=='command':
            self.execute(message['command'])
        elif kind=='touch':
            x=message['x']*(self.ui.w-1)
            y=message['y']*(self.ui.h-1)
            if message['event']=='down':
                self.press(x,y,True)
            elif message['event']=='up':
                self.release()
            elif self.held and self.at(x,y)==self.held:
                self.last_touch=time.monotonic()
            else:
                self.release()

    def tick(self):
        now=time.monotonic()
        if self.held and self.remote and now-self.last_touch>config.TOUCH_TIMEOUT_SECONDS:
            self.release()
        if self.held and now>=self.repeat_due:
            self.execute(self.held)
            self.repeat_due=now+0.14

    def execute(self,command):
        # A displayed confirmation/dialog owns input, including serial command shortcuts.
        if state.dialog and command not in self.ui.rects():
            return
        if command=='CANCEL':
            state.dialog=''
        elif command=='POWER':
            state.dialog='power'
        elif command=='POWER_CONFIRM':
            # Send before stopping the application: shutdown closes the UDP socket
            # and the DVP hotspot disappears shortly afterwards.
            self.app.bridge.request_remote_poweroff()
            state.shutdown_requested=True
            state.running=False
        elif command=='ZOOM_IN':
            state.zoom=min(config.MAX_ZOOM,state.zoom+config.ZOOM_STEP)
            notify(f'ZOOM {state.zoom:.1f}x',2)
        elif command=='ZOOM_OUT':
            state.zoom=max(1,state.zoom-config.ZOOM_STEP)
            notify(f'ZOOM {state.zoom:.1f}x',2)
        elif command in ('UP','DOWN','LEFT','RIGHT'):
            step=max(4,round(40/state.zoom)) if state.zoom>1 else 0
            state.pan_x += step*((command=='RIGHT')-(command=='LEFT'))
            state.pan_y += step*((command=='DOWN')-(command=='UP'))
        elif command=='CENTER':
            state.pan_x=state.pan_y=0
            notify('VIEW CENTERED',2)
        elif command=='MOTION':
            state.motion_enabled=not state.motion_enabled
            self.app.motion.reset()
            notify('MOTION DETECTION '+('ON' if state.motion_enabled else 'OFF'),4)
        elif command=='HUMAN':
            state.human_enabled=not state.human_enabled
            self.app.detector.clear()
            if state.human_enabled and not state.ai_ready:
                notify('HUMAN DETECTION ON - INITIALIZING',5)
            else:
                notify('HUMAN DETECTION '+('ON' if state.human_enabled else 'OFF'),4)
        elif command=='UI':
            state.ui_visible=not state.ui_visible
            notify('CONTROLS SHOWN' if state.ui_visible else 'CONTROLS HIDDEN',3)
        elif command=='RECORD_MODE':
            state.record_mode='ui' if state.record_mode=='raw' else 'raw'
            self.app.recorder.boundary()
            notify('RECORDING WITH UI' if state.record_mode=='ui' else 'RECORDING RAW CAMERA',5)
        elif command=='USB':
            state.dialog='usb'
        elif command=='STORAGE':
            state.dialog='storage'
        elif command=='DELETE_REQUEST':
            state.dialog='delete'
        elif command=='DELETE_CONFIRM':
            self.app.storage.request_delete_oldest()
            state.dialog=''
        elif command in ('EXPORT_LATEST','EXPORT_ALL','EJECT'):
            self.app.usb.request({'EXPORT_LATEST':'latest','EXPORT_ALL':'all','EJECT':'eject'}[command])
        elif command=='EXPORT_CANCEL':
            state.export_cancel=True
            notify('CANCELLING USB EXPORT',5)
