"""DVP camera, recording, detection, HDMI display, and touch application."""
import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import cv2
if __name__ == '__main__' and '--demo' in sys.argv and not os.environ.get('DVP_DATA_DIR'):
    os.environ['DVP_DATA_DIR'] = tempfile.mkdtemp(prefix='dvp-demo-')
    print('Demo data:', os.environ['DVP_DATA_DIR'], flush=True)
from app import config
from app.state import state,notify
from app.app import DVPApplication
from hardware.camera import CameraManager
from hardware.demo_camera import DemoCamera
from hardware.display import DisplayOutput
from system.logger import logger
from ui.ui import DVPUI
from ui.touch import TouchHandler

def keyboard(key,touch):
    if key in (27,ord('q'),ord('Q')):
        if state.dialog:
            state.dialog=''
        else:
            state.running=False
        return
    mapping={ord('+'):'ZOOM_IN',ord('='):'ZOOM_IN',ord('-'):'ZOOM_OUT',
             ord('w'):'UP',ord('s'):'DOWN',ord('a'):'LEFT',ord('d'):'RIGHT',
             ord('c'):'CENTER',ord('h'):'HUMAN',ord('m'):'MOTION',ord('p'):'POWER',
             ord('u'):'UI',ord('r'):'RECORD_MODE',ord('e'):'USB',ord('f'):'STORAGE'}
    if key in mapping:
        touch.execute(mapping[key])

def main():
    parser=argparse.ArgumentParser(description='DVP camera and HDMI application')
    parser.add_argument('--windowed',action='store_true')
    parser.add_argument('--headless',action='store_true',help='No display window; camera and recording remain active')
    parser.add_argument('--demo',action='store_true',help='Synthetic video; disables USB operations and real poweroff')
    parser.add_argument('--seconds',type=float,default=0,help='Stop after this many seconds (0 runs until exit)')
    parser.add_argument('--snapshot',help='Save last rendered frame as PNG when exiting')
    args=parser.parse_args()
    runtime_dir=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))
    poweroff_marker=runtime_dir/'dvp-poweroff-requested'
    try:
        poweroff_marker.unlink(missing_ok=True)
    except OSError:
        pass
    if args.demo:
        config.AUTO_DELETE_OLDEST=False
    cv2.setNumThreads(1)
    lock=open(config.DATA_DIR/'dvp.lock','a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('DVP is already running with this data directory')
    def stop(*_):
        state.running=False
    signal.signal(signal.SIGINT,stop)
    signal.signal(signal.SIGTERM,stop)
    app=DVPApplication(DemoCamera if args.demo else CameraManager,enable_usb=not args.demo)
    ui=DVPUI()
    touch=TouchHandler(ui,app)
    output=DisplayOutput((config.DISPLAY_WIDTH,config.DISPLAY_HEIGHT),detect=not args.windowed)
    display=None
    safe=False
    start=time.monotonic()
    try:
        if not args.headless:
            if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
                raise RuntimeError('Start from the DVP display session, or use --headless for diagnostics')
            output.refresh(force=True)
            touch.set_output_size(*output.size)
            cv2.namedWindow('DVP',cv2.WINDOW_NORMAL|cv2.WINDOW_FREERATIO)
            cv2.resizeWindow('DVP',*output.size)
            if config.FULLSCREEN and not args.windowed:
                cv2.setWindowProperty('DVP',cv2.WND_PROP_FULLSCREEN,cv2.WINDOW_FULLSCREEN)
            cv2.setMouseCallback('DVP',touch.mouse_callback)
        app.startup()
        splash=cv2.imread(str(config.SPLASH_PATH)) if config.SHOW_SPLASH else None
        if args.demo:
            notify('SOFTWARE DEMO - synthetic camera',10)
        while state.running and (not args.seconds or time.monotonic()-start<args.seconds):
            tick=time.monotonic()
            for message in app.bridge.drain():
                touch.remote_message(message)
            touch.tick()
            packet,view,boxes=app.update()
            display=ui.draw(view,boxes)
            app.record_display(packet,display)
            if not args.headless:
                if output.refresh():
                    touch.set_output_size(*output.size)
                    cv2.resizeWindow('DVP',*output.size)
                shown=cv2.resize(splash,(config.DISPLAY_WIDTH,config.DISPLAY_HEIGHT)) if splash is not None and tick-start<config.SPLASH_SECONDS else display
                cv2.imshow('DVP',output.scale(shown))
                key=cv2.waitKey(1)&0xff
                if key!=255:
                    keyboard(key,touch)
            time.sleep(max(0,1/config.CAMERA_FPS-(time.monotonic()-tick)))
    finally:
        safe=app.shutdown()
        if args.snapshot and display is not None:
            if not cv2.imwrite(args.snapshot,display):
                logger.error('Could not save snapshot')
        if not args.headless:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
        lock.close()
        metrics={k:getattr(state,k) for k in ('camera_fps','display_fps','ai_ms','record_dropped','record_duplicates','preview_skips','free_gb')}
        print(json.dumps({'clean_shutdown':safe,'metrics':metrics},indent=2))
    if state.shutdown_requested and config.ALLOW_SYSTEM_POWEROFF and not args.demo:
        if not safe:
            raise SystemExit('Poweroff cancelled: recording/export did not close cleanly; inspect data/logs')
        try:
            poweroff_marker.touch(exist_ok=True)
        except OSError as exc:
            logger.warning('Could not create poweroff marker: %s',exc)
        result=subprocess.run(['systemctl','poweroff'],capture_output=True,text=True,timeout=10)
        if result.returncode:
            try:
                poweroff_marker.unlink(missing_ok=True)
            except OSError:
                pass
            raise SystemExit('Poweroff failed: '+result.stderr.strip())

if __name__=='__main__':
    main()
