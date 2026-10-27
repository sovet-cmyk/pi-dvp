"""Minimal DVP controls with shared geometry for local and wireless touch."""
import time
import cv2
from app import config
from app.state import state

WHITE=(240,240,240)
GREEN=(85,220,95)
YELLOW=(0,215,255)
RED=(65,70,235)
DARK=(24,28,31)
GRAY=(70,76,80)

class DVPUI:
    def __init__(self):
        self.w,self.h = config.DISPLAY_WIDTH,config.DISPLAY_HEIGHT

    def rects(self):
        w,h = self.w,self.h
        if state.dialog=='power':
            return {'CANCEL':(w//2-205,h//2+40,w//2-25,h//2+92),
                    'POWER_CONFIRM':(w//2+25,h//2+40,w//2+205,h//2+92)}
        if state.dialog=='usb':
            if state.export_busy:
                return {'EXPORT_CANCEL':(w//2-120,h//2+55,w//2+120,h//2+105),
                        'CANCEL':(w//2-120,h//2+115,w//2+120,h//2+158)}
            return {'EXPORT_LATEST':(w//2-210,h//2-30,w//2-10,h//2+20),
                    'EXPORT_ALL':(w//2+10,h//2-30,w//2+210,h//2+20),
                    'EJECT':(w//2-210,h//2+38,w//2-10,h//2+88),
                    'CANCEL':(w//2+10,h//2+38,w//2+210,h//2+88)}
        if state.dialog in ('storage','delete'):
            command = 'DELETE_CONFIRM' if state.dialog=='delete' else 'DELETE_REQUEST'
            return {command:(w//2-210,h//2+35,w//2-10,h//2+88),
                    'CANCEL':(w//2+10,h//2+35,w//2+210,h//2+88)}
        if not state.ui_visible:
            return {'UI':(w-64,6,w-6,45)}
        cy = h-100
        regions = {'ZOOM_IN':(15,80,62,127),'ZOOM_OUT':(15,175,62,222),
                   'POWER':(w-58,4,w-4,34)}
        for name,dx,dy in [('UP',0,-42),('DOWN',0,42),('LEFT',-42,0),('RIGHT',42,0),('CENTER',0,0)]:
            regions[name] = (85+dx-20,cy+dy-20,85+dx+20,cy+dy+20)
        for i,name in enumerate(('MOTION','HUMAN','UI','RECORD_MODE','USB','STORAGE')):
            regions[name]=(w-68,75+i*62,w-10,123+i*62)
        return regions

    def text(self,img,text,x,y,size=0.5,colour=WHITE,thickness=1):
        cv2.putText(img,str(text),(int(x),int(y)),cv2.FONT_HERSHEY_SIMPLEX,size,colour,thickness,cv2.LINE_AA)

    def button(self,img,rect,label,colour=GRAY):
        x1,y1,x2,y2=rect
        cv2.rectangle(img,(x1,y1),(x2,y2),colour,-1)
        cv2.rectangle(img,(x1,y1),(x2,y2),WHITE,1)
        scale=0.47 if len(label)>4 else 0.6
        tw,th=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0]
        self.text(img,label,(x1+x2-tw)//2,(y1+y2+th)//2,scale)

    def battery(self,img):
        """Draw four approximate charge bars without exposing diagnostic numbers."""
        if not state.battery_available:
            return
        x1,y1,x2,y2=self.w-126,7,self.w-74,31
        colour=RED if state.battery_bars<=1 else GREEN
        cv2.rectangle(img,(x1,y1),(x2,y2),WHITE,1)
        cv2.rectangle(img,(x2+1,y1+7),(x2+5,y2-7),WHITE,-1)
        gap=3
        inner_w=x2-x1-6
        bar_w=(inner_w-gap*3)//4
        for index in range(4):
            left=x1+3+index*(bar_w+gap)
            cv2.rectangle(img,(left,y1+4),(left+bar_w,y2-4),
                          colour if index<state.battery_bars else DARK,-1)

    def recording_badge(self,img):
        """Show recording state and mode without exposing maintenance telemetry."""
        if state.record_error:
            label,colour='REC ERROR',RED
        elif not config.ENABLE_RECORDING:
            label,colour='REC OFF',GRAY
        elif state.recording:
            label='REC UI' if state.record_mode=='ui' else 'REC RAW'
            colour=RED
        elif state.camera_connected:
            label,colour='REC START',YELLOW
        else:
            label,colour='REC STOPPED',GRAY
        x1,y1,x2,y2=6,4,126,35
        cv2.rectangle(img,(x1,y1),(x2,y2),DARK,-1)
        cv2.rectangle(img,(x1,y1),(x2,y2),colour,1)
        tw,th=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,0.43,1)[0]
        self.text(img,label,(x1+x2-tw)//2,(y1+y2+th)//2,0.43,colour,1)

    def touch_badge(self,img):
        """Show the screen-control link without exposing network details."""
        status=state.touch_status
        if status=='OK':
            label,colour='TOUCH READY',GREEN
        elif status=='WAIT':
            label,colour='TOUCH SEARCHING',YELLOW
        elif status=='LOST':
            label,colour='TOUCH LOST',RED
        elif status in ('PORT ERR','NO DRIVER'):
            label,colour='TOUCH ERROR',RED
        elif status=='LOCAL':
            label,colour='TOUCH READY',GREEN
        else:
            return
        x1,y1,x2,y2=134,4,288,35
        scale=0.40
        maximum=x2-x1-12
        while scale>0.30 and cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0][0]>maximum:
            scale-=0.02
        cv2.rectangle(img,(x1,y1),(x2,y2),DARK,-1)
        cv2.rectangle(img,(x1,y1),(x2,y2),colour,1)
        tw,th=cv2.getTextSize(label,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0]
        self.text(img,label,(x1+x2-tw)//2,(y1+y2+th)//2,scale,colour,1)

    def status_banner(self,img):
        """Render temporary operator messages or the last persistent USB result."""
        colour=YELLOW
        if state.status and time.monotonic()<state.status_until:
            message=str(state.status).strip()
        elif state.usb_export_error or state.usb_last_result=='failed':
            message='LAST USB EXPORT FAILED'
            colour=RED
        elif state.usb_safe_to_remove and state.usb_last_result=='complete':
            message='USB EXPORT COMPLETE - SAFE TO REMOVE'
            colour=GREEN
        elif state.usb_safe_to_remove:
            message='USB SAFE TO REMOVE'
            colour=GREEN
        elif state.usb_last_result=='complete':
            message='LAST USB EXPORT COMPLETE'
            colour=GREEN
        elif state.usb_last_result=='copied':
            message='USB EXPORT VERIFIED - EJECT REQUIRED'
            colour=GREEN
        elif state.usb_last_result=='ejected':
            message='USB WAS SAFELY EJECTED'
            colour=GREEN
        else:
            return
        if not message:
            return
        x1,y1,x2,y2=296,4,self.w-134,35
        maximum=x2-x1-14
        scale=0.48
        while scale>0.32 and cv2.getTextSize(message,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0][0]>maximum:
            scale-=0.04
        while message and cv2.getTextSize(message,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0][0]>maximum:
            message=message[:-1]
        cv2.rectangle(img,(x1,y1),(x2,y2),DARK,-1)
        cv2.rectangle(img,(x1,y1),(x2,y2),colour,1)
        tw,th=cv2.getTextSize(message,cv2.FONT_HERSHEY_SIMPLEX,scale,1)[0]
        self.text(img,message,(x1+x2-tw)//2,(y1+y2+th)//2,scale,colour,1)

    def draw(self,view,boxes=()):
        img=view.copy()
        w,h=self.w,self.h
        if state.ui_visible:
            for box in boxes:
                a,b,c,d=map(int,box['box'])
                cv2.rectangle(img,(a,b),(c,d),GREEN,2)
            self.battery(img)
            labels={'ZOOM_IN':'+','ZOOM_OUT':'-','UP':'U','DOWN':'D','LEFT':'L','RIGHT':'R',
                    'CENTER':'C','MOTION':'M','HUMAN':'H','UI':'U',
                    'RECORD_MODE':'RAW' if state.record_mode=='raw' else 'UIR',
                    'USB':'USB','STORAGE':'S','POWER':'PWR'}
            if not state.dialog:
                for command,rect in self.rects().items():
                    colour=GRAY
                    if (command=='MOTION' and state.motion_enabled) or (command=='HUMAN' and state.human_enabled and state.ai_ready):
                        colour=(45,115,45)
                    self.button(img,rect,labels[command],colour)
            if state.zoom>1:
                cx,cy=w//2,h//2
                cv2.line(img,(cx-13,cy),(cx+13,cy),GREEN,1)
                cv2.line(img,(cx,cy-13),(cx,cy+13),GREEN,1)
            self.recording_badge(img)
        elif not state.dialog:
            self.button(img,self.rects()['UI'],'UI')
        if not state.camera_connected:
            self.text(img,'CAMERA DISCONNECTED',w//2-160,h//2-12,0.75,RED,2)
            self.text(img,'Waiting for USB camera...',w//2-132,h//2+24,0.55)
        if state.export_busy and not state.dialog:
            self.text(img,f'USB EXPORT {state.export_progress:.0f}%',w//2-92,h-42,0.5,YELLOW)
        if state.dialog:
            self.draw_dialog(img)
        self.touch_badge(img)
        self.status_banner(img)
        return img

    def draw_dialog(self,img):
        w,h=self.w,self.h
        cv2.rectangle(img,(w//2-245,80),(w//2+245,h-62),DARK,-1)
        cv2.rectangle(img,(w//2-245,80),(w//2+245,h-62),WHITE,1)
        title={'power':'SHUT DOWN DVP?','usb':'USB EXPORT','storage':'STORAGE','delete':'DELETE OLDEST MISSION?'}[state.dialog]
        self.text(img,title,w//2-220,119,0.7,YELLOW,2)
        if state.dialog=='power':
            self.text(img,'Close recordings and shut down safely.',w//2-220,168,0.5)
            self.text(img,'An active USB export will be cancelled.',w//2-220,195,0.5)
        elif state.dialog=='usb':
            label=state.usb_label if state.usb_connected else 'No mounted USB drive'
            self.text(img,label[:42],w//2-220,159,0.53)
            if state.export_busy:
                self.text(img,f'Copy / verify: {state.export_progress:.0f}%',w//2-220,200,0.6,YELLOW)
                cv2.rectangle(img,(w//2-215,222),(w//2+215,241),GRAY,-1)
                cv2.rectangle(img,(w//2-215,222),(w//2-215+int(430*state.export_progress/100),241),GREEN,-1)
        else:
            self.text(img,f'Free space: {state.free_gb:.2f} GB',w//2-220,160,0.56)
            self.text(img,'Active recordings and exports are protected.',w//2-220,194,0.47)
            if state.dialog=='storage':
                self.text(img,f'Auto-delete below {config.STORAGE_DELETE_GB:g} GB: '+('ON' if config.AUTO_DELETE_OLDEST else 'OFF'),w//2-220,224,0.48)
            else:
                self.text(img,'Deletion cannot be undone.',w//2-220,224,0.5,YELLOW)
        labels={'CANCEL':'BACK','POWER_CONFIRM':'SHUT DOWN','EXPORT_LATEST':'LATEST MISSION',
                'EXPORT_ALL':'ALL MISSIONS','EJECT':'EJECT USB','EXPORT_CANCEL':'CANCEL EXPORT',
                'DELETE_REQUEST':'DELETE OLDEST','DELETE_CONFIRM':'CONFIRM DELETE'}
        for command,rect in self.rects().items():
            self.button(img,rect,labels[command],RED if command in ('POWER_CONFIRM','DELETE_CONFIRM') else GRAY)

