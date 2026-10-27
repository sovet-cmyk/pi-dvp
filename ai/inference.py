"""The supplied 320px YOLOv8n model, person class only. No PyTorch dependency."""
import time
import cv2
import numpy as np
from app import config

class InferenceEngine:
    def __init__(self, model_path=None):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = config.AI_THREADS
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self.session = ort.InferenceSession(str(model_path or config.MODEL_PATH), options,
                                           providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        shape = inp.shape
        if len(shape) != 4 or shape[0] != 1 or shape[1] != 3 or inp.type != "tensor(float)":
            raise ValueError(f"Expected static float32 NCHW model, found {shape}/{inp.type}")
        self.h, self.w = int(shape[2]), int(shape[3])
        self.name = inp.name

    def infer(self, frame):
        start = time.monotonic()
        h,w = frame.shape[:2]
        scale = min(self.w/w, self.h/h)
        nw,nh = round(w*scale),round(h*scale)
        left,top = (self.w-nw)//2,(self.h-nh)//2
        canvas = np.full((self.h,self.w,3),114,dtype=np.uint8)
        canvas[top:top+nh,left:left+nw] = cv2.resize(frame,(nw,nh))
        tensor = np.ascontiguousarray(canvas[:,:,::-1].transpose(2,0,1)[None], dtype=np.float32)/255.0
        output = self.session.run(None,{self.name:tensor})[0]
        boxes = decode(output, (h,w), (nw/w,nh/h,left,top))
        return boxes, (time.monotonic()-start)*1000

def decode(output, frame_shape, transform):
    rows = np.asarray(output)
    if rows.ndim == 3 and rows.shape[0] == 1:
        rows = rows[0]
    if rows.ndim != 2:
        raise ValueError(f"Unexpected YOLO output: {rows.shape}")
    if rows.shape[0] == 84:
        rows = rows.T
    if rows.shape[1] != 84:
        raise ValueError("This decoder expects YOLOv8 COCO output [1,84,N], without embedded NMS")
    # Preserve person-only decisions, without a Python loop through every anchor.
    mask = (rows[:,4] >= config.CONFIDENCE_THRESHOLD) & (rows[:,4:].argmax(axis=1) == 0)
    rows = rows[mask]
    if not len(rows):
        return []
    sx,sy,left,top = transform
    h,w = frame_shape[:2]
    scores = rows[:,4].astype(float)
    xy = rows[:,:4].copy()
    x1 = np.clip((xy[:,0]-xy[:,2]/2-left)/sx,0,w-1)
    y1 = np.clip((xy[:,1]-xy[:,3]/2-top)/sy,0,h-1)
    x2 = np.clip((xy[:,0]+xy[:,2]/2-left)/sx,0,w-1)
    y2 = np.clip((xy[:,1]+xy[:,3]/2-top)/sy,0,h-1)
    valid = (x2>x1)&(y2>y1)&np.isfinite(rows).all(axis=1)
    boxes = np.stack((x1,y1,x2-x1,y2-y1),axis=1)[valid]
    scores = scores[valid]
    indices = cv2.dnn.NMSBoxes(boxes.tolist(),scores.tolist(),config.CONFIDENCE_THRESHOLD,config.IOU_THRESHOLD)
    result = []
    for i in np.asarray(indices).reshape(-1):
        x,y,bw,bh = boxes[int(i)]
        result.append({"box": (float(x),float(y),float(x+bw),float(y+bh)), "confidence": float(scores[int(i)])})
    return result

