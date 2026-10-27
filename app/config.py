"""DVP processing-unit configuration. Edit settings.json, not this file."""
import json
import math
import os
from pathlib import Path

VERSION = "3.2.5"
LEGACY_IGNORED_SETTINGS = {
    "USB_SAFE_BEEP_SECONDS", "BUZZER_ENABLED", "BUZZER_GPIO",
    "BUZZER_ACTIVE_HIGH", "BUZZER_FREQUENCY_HZ", "BUZZER_DUTY_CYCLE",
}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "CAMERA_DEVICE": 0, "CAMERA_WIDTH": 1280, "CAMERA_HEIGHT": 720,
    "CAMERA_FPS": 30, "CAMERA_FOURCC": "MJPG", "RECONNECT_SECONDS": 2.0,
    "CAMERA_STALE_SECONDS": 1.0, "DISPLAY_WIDTH": 800, "DISPLAY_HEIGHT": 480,
    "FULLSCREEN": True, "SHOW_SPLASH": True, "SPLASH_SECONDS": 2.0,
    "HUMAN_ENABLED": True, "MOTION_ENABLED": True, "AI_MAX_FPS": 5.0,
    "AI_THREADS": 2, "CONFIDENCE_THRESHOLD": 0.45, "IOU_THRESHOLD": 0.45,
    "DETECTION_TTL_SECONDS": 0.8, "MOTION_WIDTH": 320,
    "MOTION_MIN_AREA": 60, "MOTION_PIXEL_THRESHOLD": 25,
    "MOTION_GLOBAL_FRACTION": 0.40, "MOTION_HOLD_SECONDS": 1.0,
    "ENABLE_RECORDING": True, "RECORD_MODE": "raw", "RECORD_FPS": 30,
    "RECORD_QUEUE_FRAMES": 8, "RECORD_SEGMENT_SECONDS": 300,
    "RECORD_MAX_GAP_SECONDS": 1.0, "ENCODER_THREADS": 2, "RECORD_CRF": 23,
    "RECORD_MIN_FREE_MB": 256, "USB_AUTOMOUNT": True, "AUTO_USB_EXPORT": True,
    "AUTO_USB_EJECT": True, "USB_SCAN_SECONDS": 2.0, "VERIFY_EXPORT": True,
    "STORAGE_WARN_GB": 5.0, "STORAGE_DELETE_GB": 2.0,
    "STORAGE_TARGET_GB": 3.0, "AUTO_DELETE_OLDEST": True,
    "TOUCH_MODE": "udp", "TOUCH_UDP_BIND": "0.0.0.0", "TOUCH_UDP_PORT": 4210,
    "TOUCH_SHARED_KEY": "dvp3-touch-v1-7F4m9Q2x8K6p",
    "TOUCH_SERIAL_PORT": "", "TOUCH_BAUD": 115200,
    "TOUCH_TIMEOUT_SECONDS": 0.7, "MAX_ZOOM": 10.0, "ZOOM_STEP": 0.5,
    "INA226_ENABLED": True, "INA226_I2C_BUS": 1, "INA226_ADDRESS": 64,
    "INA226_SHUNT_OHMS": 0.005, "INA226_CURRENT_LSB_A": 0.0005,
    "BATTERY_LOAD_COMPENSATION_OHMS": 0.03,
    "BATTERY_FILTER_ALPHA": 0.25, "BATTERY_BAR_1_V": 6.5,
    "BATTERY_BAR_2_V": 7.0, "BATTERY_BAR_3_V": 7.4,
    "BATTERY_BAR_4_V": 7.8, "ALLOW_SYSTEM_POWEROFF": True,
}
settings_path = Path(os.environ.get("DVP_SETTINGS", PROJECT_ROOT / "settings.json"))
pairing_path = Path(os.environ.get("DVP_PAIRING", PROJECT_ROOT / "pairing.json"))
settings = DEFAULTS.copy()
if settings_path.is_file():
    supplied = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(supplied, dict):
        raise ValueError("settings.json must contain a JSON object")
    for legacy_key in LEGACY_IGNORED_SETTINGS:
        supplied.pop(legacy_key,None)
    unknown = set(supplied) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    settings.update(supplied)
if pairing_path.is_file():
    pairing = json.loads(pairing_path.read_text(encoding="utf-8"))
    if not isinstance(pairing, dict):
        raise ValueError("pairing.json must contain a JSON object")
    allowed_pairing = {"unit_id", "ssid", "wifi_password", "touch_shared_key"}
    unknown_pairing = set(pairing) - allowed_pairing
    if unknown_pairing:
        raise ValueError(f"Unknown pairing settings: {sorted(unknown_pairing)}")
    touch_key = pairing.get("touch_shared_key")
    if not isinstance(touch_key, str):
        raise ValueError("pairing.json touch_shared_key must be a string")
    settings["TOUCH_SHARED_KEY"] = touch_key
for key, default in DEFAULTS.items():
    value = settings[key]
    if isinstance(default, bool) and not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    if key == "CAMERA_DEVICE":
        if isinstance(value,bool) or not isinstance(value,(str,int)) or (isinstance(value,int) and value<0):
            raise ValueError("CAMERA_DEVICE must be a non-negative index or a /dev/video path")
        continue
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a positive number")
        if isinstance(default, int) and not isinstance(value, int):
            raise ValueError(f"{key} must be an integer")
    if isinstance(default, str) and not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
if settings["RECORD_MODE"] not in ("raw", "ui"):
    raise ValueError("RECORD_MODE must be raw or ui")
if not 0 < settings["CONFIDENCE_THRESHOLD"] < 1 or not 0 < settings["IOU_THRESHOLD"] < 1:
    raise ValueError("Detection thresholds must be between 0 and 1")
if not settings["STORAGE_DELETE_GB"] < settings["STORAGE_TARGET_GB"] <= settings["STORAGE_WARN_GB"]:
    raise ValueError("Storage thresholds must satisfy DELETE < TARGET <= WARN")
if len(settings["CAMERA_FOURCC"]) != 4:
    raise ValueError("CAMERA_FOURCC must have four characters")
if settings["TOUCH_MODE"] not in ("off", "udp", "serial"):
    raise ValueError("TOUCH_MODE must be off, udp or serial")
if settings["TOUCH_UDP_PORT"] > 65535:
    raise ValueError("TOUCH_UDP_PORT must be between 1 and 65535")
if settings["TOUCH_MODE"] == "udp" and len(settings["TOUCH_SHARED_KEY"]) < 16:
    raise ValueError("TOUCH_SHARED_KEY must contain at least 16 characters in UDP mode")
if settings["TOUCH_MODE"] == "serial" and not settings["TOUCH_SERIAL_PORT"]:
    raise ValueError("TOUCH_SERIAL_PORT is required in serial mode")
if settings["DISPLAY_WIDTH"] < 800 or settings["DISPLAY_HEIGHT"] < 480:
    raise ValueError("This touch layout requires at least 800 x 480")
if settings["DISPLAY_WIDTH"] % 2 or settings["DISPLAY_HEIGHT"] % 2:
    raise ValueError("Display dimensions must be even for UI recording")
if not (settings["BATTERY_BAR_1_V"] < settings["BATTERY_BAR_2_V"] <
        settings["BATTERY_BAR_3_V"] < settings["BATTERY_BAR_4_V"]):
    raise ValueError("Battery bar voltage thresholds must be strictly increasing")
if settings["BATTERY_FILTER_ALPHA"] > 1:
    raise ValueError("BATTERY_FILTER_ALPHA must be at most 1")
if settings["INA226_ADDRESS"] > 127:
    raise ValueError("INA226_ADDRESS must be a 7-bit I2C address")
if settings["RECORD_CRF"] > 51 or settings["MOTION_PIXEL_THRESHOLD"] > 255 or settings["MOTION_GLOBAL_FRACTION"] > 1:
    raise ValueError("Invalid encoder quality or motion threshold")
globals().update(settings)
DATA_DIR = Path(os.environ.get("DVP_DATA_DIR", PROJECT_ROOT / "data")).expanduser().resolve()
RECORDINGS_DIR = DATA_DIR / "recordings"
LOGS_DIR = DATA_DIR / "logs"
MODEL_PATH = PROJECT_ROOT / "models/yolov8n.onnx"
SPLASH_PATH = PROJECT_ROOT / "assets/splash.png"
for directory in (RECORDINGS_DIR, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
