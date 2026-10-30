"""Read-only prerequisite check. Does not open the camera, mount USB, or power off."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import config

def command(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=15)
    return result.returncode,result.stdout+result.stderr

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--camera',action='store_true',help='Also list V4L2 devices and formats')
    args=parser.parse_args()
    report={'platform':platform.platform(),'machine':platform.machine(),
            'python':platform.python_version(),'data_dir':str(config.DATA_DIR)}
    failures=[]
    for name in ('cv2','numpy','onnxruntime','serial','smbus','lgpio'):
        try:
            module=__import__(name)
            report[name]=getattr(module,'__version__','installed')
        except Exception as exc:
            failures.append(name+': '+str(exc))
    for name in ('ffmpeg','ffprobe','lsblk','udisksctl','xrandr','i2cdetect'):
        report[name]=shutil.which(name)
        if not report[name]:
            failures.append(name+' executable not found')
    if report.get('ffmpeg'):
        code,encoders=command(['ffmpeg','-hide_banner','-encoders'])
        if code or 'libx264' not in encoders:
            failures.append('FFmpeg libx264 encoder unavailable')
    try:
        from ai.inference import InferenceEngine
        import numpy as np
        engine=InferenceEngine()
        boxes,ms=engine.infer(np.zeros((720,1280,3),dtype=np.uint8))
        report['model']={'input':[1,3,engine.h,engine.w],'test_ms':round(ms,1),'detections_on_black':len(boxes)}
    except Exception as exc:
        failures.append('Model inference: '+str(exc))
    if args.camera and shutil.which('v4l2-ctl'):
        report['camera_devices']=command(['v4l2-ctl','--list-devices'])[1]
        device='/dev/video'+str(config.CAMERA_DEVICE) if isinstance(config.CAMERA_DEVICE,int) else config.CAMERA_DEVICE
        report['camera_formats']=command(['v4l2-ctl','--device',device,'--list-formats-ext'])[1]
    report['failures']=failures
    print(json.dumps(report,indent=2))
    return 1 if failures else 0

if __name__=='__main__':
    raise SystemExit(main())
