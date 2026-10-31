"""UI-facing telemetry. Workers publish scalars; frames/results use their own locks."""
from dataclasses import dataclass, field
import time
from app import config

@dataclass
class State:
    running: bool = True
    camera_connected: bool = False
    camera_fps: float = 0.0
    display_fps: float = 0.0
    camera_size: str = ""
    preview_skips: int = 0
    human_enabled: bool = config.HUMAN_ENABLED
    motion_enabled: bool = config.MOTION_ENABLED
    ai_ready: bool = False
    ai_status: str = "LOADING"
    ai_ms: float = 0.0
    motion_detected: bool = False
    scene_moving: bool = False
    recording: bool = False
    record_mode: str = config.RECORD_MODE
    record_dropped: int = 0
    record_duplicates: int = 0
    record_error: str = ""
    current_mission: str = ""
    free_gb: float = 0.0
    storage_low: bool = False
    storage_items: list = field(default_factory=list)
    storage_selected: set = field(default_factory=set)
    storage_page: int = 0
    usb_connected: bool = False
    usb_label: str = ""
    export_busy: bool = False
    export_progress: float = 0.0
    export_cancel: bool = False
    usb_safe_to_remove: bool = False
    usb_export_error: bool = False
    usb_last_result: str = ""
    zoom: float = 1.0
    pan_x: int = 0
    pan_y: int = 0
    ui_visible: bool = True
    dialog: str = ""
    shutdown_requested: bool = False
    status: str = "Starting DVP"
    status_until: float = 0.0
    touch_status: str = "LOCAL"
    touch_last_seen: float = 0.0
    battery_available: bool = False
    battery_bars: int = 0
    battery_voltage: float | None = None
    battery_current: float | None = None

state = State()

def notify(message, seconds=5):
    state.status = str(message)
    state.status_until = time.monotonic() + seconds

