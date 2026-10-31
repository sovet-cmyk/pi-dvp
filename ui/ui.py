"""Minimal DVP controls with shared geometry for local and wireless touch."""
import time
from datetime import datetime
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
        if state.dialog=='storage':
            regions = {}
            start = state.storage_page*4
            for row,item in enumerate(state.storage_items[start:start+4]):
                regions['STORAGE_ITEM_'+item['name']] = (w//2-225,156+row*44,w//2+225,194+row*44)
            y1,y2=h-107,h-65
            regions.update({
                'STORAGE_PREV':(w//2-225,y1,w//2-145,y2),
                'STORAGE_NEXT':(w//2-137,y1,w//2-57,y2),
                'STORAGE_SELECT_ALL':(w//2-49,y1,w//2+49,y2),
                'STORAGE_DELETE':(w//2+57,y1,w//2+137,y2),
                'CANCEL':(w//2+145,y1,w//2+225,y2),
            })
            return regions
        if state.dialog=='delete_confirm':
            return {'DELETE_SELECTED_CONFIRM':(w//2-210,h//2+55,w//2-10,h//2+108),
                    'CANCEL':(w//2+10,h//2+55,w//2+210,h//2+108)}
        if not state.ui_visible:
            return {'UI':(w-64,6,w-6,45)}
        cy = h-100
        regions = {'ZOOM_IN':(15,80,62,127),'ZOOM_OUT':(15,175,62,222),
                   'POWER':(w-58,4,w-4,34)}
        for name,dx,dy in [('UP',0,-42),('DOWN',0,42),('LEFT',-42,0),('RIGHT',42,0),('CENTER',0,0)]:
            regions[name] = (85+dx-20,cy+dy-20,85+dx+20,cy+dy+20)
        for i,name in enumerate(('MOTION','HUMAN','UI','RECORD_MODE','STORAGE')):
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
                    'STORAGE':'S','POWER':'PWR'}
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
        title={'power':'SHUT DOWN DVP?','storage':'RECORDING STORAGE',
               'delete_confirm':'DELETE SELECTED RECORDINGS?'}[state.dialog]
        self.text(img,title,w//2-220,119,0.7,YELLOW,2)
        if state.dialog=='power':
            self.text(img,'Close recordings and shut down safely.',w//2-220,168,0.5)
            self.text(img,'An active USB export will be cancelled.',w//2-220,195,0.5)
        elif state.dialog=='storage':
            self.draw_storage_list(img)
        else:
            count=len(state.storage_selected)
            self.text(img,f'{count} recording'+('s' if count!=1 else '')+' selected.',w//2-220,165,0.58)
            self.text(img,'Deleted recordings cannot be recovered.',w//2-220,203,0.50,YELLOW)
            names=sorted(state.storage_selected)
            preview=', '.join(names[:3])+(' ...' if len(names)>3 else '')
            self.text(img,preview[:55],w//2-220,238,0.44)
        labels={'CANCEL':'BACK','POWER_CONFIRM':'SHUT DOWN',
                'STORAGE_PREV':'<','STORAGE_NEXT':'>','STORAGE_SELECT_ALL':'ALL',
                'STORAGE_DELETE':'DELETE','DELETE_SELECTED_CONFIRM':'CONFIRM'}
        for command,rect in self.rects().items():
            if command.startswith('STORAGE_ITEM_'):
                continue
            colour=RED if command in ('POWER_CONFIRM','STORAGE_DELETE','DELETE_SELECTED_CONFIRM') else GRAY
            self.button(img,rect,labels[command],colour)

    @staticmethod
    def _size_label(size_bytes):
        size=float(size_bytes)
        for unit in ('B','KB','MB','GB'):
            if size<1024 or unit=='GB':
                return f'{size:.1f} {unit}' if unit in ('MB','GB') else f'{size:.0f} {unit}'
            size/=1024

    @staticmethod
    def _date_label(value):
        try:
            return datetime.fromisoformat(value.replace('Z','+00:00')).strftime('%d-%m-%Y %H:%M')
        except (TypeError,ValueError):
            return 'DATE UNKNOWN'

    def draw_storage_list(self,img):
        w,h=self.w,self.h
        items=state.storage_items
        pages=max(1,(len(items)+3)//4)
        self.text(img,f'Free: {state.free_gb:.2f} GB   Recordings: {len(items)}   Page {state.storage_page+1}/{pages}',
                  w//2-220,148,0.43)
        visible=items[state.storage_page*4:state.storage_page*4+4]
        if not visible:
            self.text(img,'No completed recordings available.',w//2-185,205,0.55,YELLOW)
        for row,item in enumerate(visible):
            y1=156+row*44
            selected=item['name'] in state.storage_selected
            protected=item.get('protected',False)
            colour=(45,115,45) if selected else GRAY
            if protected:
                colour=(65,65,90)
            cv2.rectangle(img,(w//2-225,y1),(w//2+225,y1+38),colour,-1)
            cv2.rectangle(img,(w//2-225,y1),(w//2+225,y1+38),WHITE,1)
            mark='[X]' if selected else '[ ]'
            self.text(img,mark,w//2-215,y1+25,0.46,GREEN if selected else WHITE)
            self.text(img,item['name'].replace('Mission_','REC '),w//2-168,y1+25,0.46)
            self.text(img,self._date_label(item.get('ended_utc','')),w//2-73,y1+25,0.39)
            self.text(img,self._size_label(item.get('size_bytes',0)),w//2+103,y1+25,0.39)
            if protected:
                self.text(img,'BUSY',w//2+181,y1+25,0.36,YELLOW)

