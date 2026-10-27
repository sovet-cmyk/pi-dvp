import cv2
import numpy as np
from app import config
from app.state import state

def make_view(frame):
    """Letterbox a digitally zoomed view; recording in RAW mode never calls this."""
    h, w = frame.shape[:2]
    z = min(config.MAX_ZOOM, max(1.0, state.zoom))
    cw, ch = max(2, int(w / z)), max(2, int(h / z))
    if z == 1:
        state.pan_x = state.pan_y = 0
    state.pan_x = max(-(w-cw)//2, min((w-cw)//2, state.pan_x))
    state.pan_y = max(-(h-ch)//2, min((h-ch)//2, state.pan_y))
    x = max(0, min(w-cw, (w-cw)//2 + state.pan_x))
    y = max(0, min(h-ch, (h-ch)//2 + state.pan_y))
    dw, dh = config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT
    scale = min(dw/cw, dh/ch)
    vw, vh = round(cw*scale), round(ch*scale)
    ox, oy = (dw-vw)//2, (dh-vh)//2
    view = np.zeros((dh, dw, 3), dtype=np.uint8)
    view[oy:oy+vh, ox:ox+vw] = cv2.resize(frame[y:y+ch, x:x+cw], (vw, vh))
    return view, (x, y, cw, ch, vw/cw, vh/ch, ox, oy)

def map_boxes(detections, transform):
    x, y, w, h, sx, sy, ox, oy = transform
    mapped = []
    for d in detections:
        a,b,c,e = d["box"]
        a,b,c,e = max(a,x),max(b,y),min(c,x+w),min(e,y+h)
        if c > a and e > b:
            mapped.append({"box": (int((a-x)*sx+ox),int((b-y)*sy+oy),
                                   int((c-x)*sx+ox),int((e-y)*sy+oy)),
                           "confidence": d["confidence"]})
    return mapped

