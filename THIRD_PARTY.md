# Bundled model and dependencies

models/yolov8n.onnx is the unchanged model supplied in the user's archive.
Its embedded metadata identifies Ultralytics YOLOv8n, COCO labels, input
[1,3,320,320], output [1,84,2100], opset 12, and AGPL-3.0.
No new model training or model download was performed.

The UI splash image is also retained from that archive.

Runtime packages retain their respective upstream licenses:

- ONNX Runtime: https://github.com/microsoft/onnxruntime
- OpenCV: https://github.com/opencv/opencv
- NumPy: https://numpy.org/
- pyserial: https://github.com/pyserial/pyserial
- FFmpeg / libx264: https://ffmpeg.org/legal.html
- Ultralytics model information: https://github.com/ultralytics/ultralytics

Implementation references:

- ONNX Runtime threading:
  https://onnxruntime.ai/docs/performance/tune-performance/threading.html
- ONNX Runtime Python platforms:
  https://onnxruntime.ai/docs/get-started/with-python.html
- FFmpeg MOV/MP4 formats:
  https://ffmpeg.org/ffmpeg-formats.html
- UDisks command interface:
  https://storaged.org/doc/udisks2-api/latest/udisksctl.1.html
- Raspberry Pi OS:
  https://www.raspberrypi.com/documentation/computers/os.html
- Raspberry Pi desktop/display configuration:
  https://www.raspberrypi.com/documentation/computers/configuration.html
- Desktop startup entry specification:
  https://specifications.freedesktop.org/autostart-spec/latest/
