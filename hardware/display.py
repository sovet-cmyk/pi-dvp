"""Detect the active HDMI desktop size and scale the logical DVP canvas to it."""
from __future__ import annotations

import re
import subprocess
import time

import cv2

from system.logger import logger


_ACTIVE_MODE = re.compile(r"^\s+(\d+)x(\d+)(?:i)?\s+.*\*", re.MULTILINE)
_CURRENT_SIZE = re.compile(r"\bcurrent\s+(\d+)\s+x\s+(\d+)\b")


def parse_xrandr_size(output: str) -> tuple[int, int] | None:
    """Return the active output mode from ``xrandr --current`` text."""
    active = _ACTIVE_MODE.search(output)
    match = active or _CURRENT_SIZE.search(output)
    if not match:
        return None
    width, height = map(int, match.groups())
    if width < 320 or height < 240:
        return None
    return width, height


def detect_output_size(fallback: tuple[int, int]) -> tuple[int, int]:
    try:
        result = subprocess.run(
            ["xrandr", "--current"], capture_output=True, text=True, timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return fallback
    if result.returncode:
        return fallback
    return parse_xrandr_size(result.stdout) or fallback


class DisplayOutput:
    """Maintain a fixed logical canvas while following HDMI hot-plug mode changes."""

    def __init__(self, logical_size: tuple[int, int], detect=True, interval=2.0):
        self.logical_size = tuple(map(int, logical_size))
        self.detect = bool(detect)
        self.interval = float(interval)
        self.size = self.logical_size
        self._next_check = 0.0

    def refresh(self, force=False) -> bool:
        now = time.monotonic()
        if not force and now < self._next_check:
            return False
        self._next_check = now + self.interval
        detected = detect_output_size(self.size) if self.detect else self.logical_size
        changed = detected != self.size
        if changed:
            self.size = detected
            logger.info("Display mode changed to %dx%d", *self.size)
        return changed

    def scale(self, frame):
        if (frame.shape[1], frame.shape[0]) == self.size:
            return frame
        return cv2.resize(frame, self.size, interpolation=cv2.INTER_LINEAR)
