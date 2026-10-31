"""Non-blocking audible USB-export status using a transistor-driven buzzer."""

import importlib
import threading
import time

from app import config
from system.logger import logger


class Buzzer:
    SILENT = "silent"
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"

    def __init__(self, enabled=None, gpio_module=None, *, beep_seconds=None,
                 success_gap_seconds=None, success_repeat_seconds=None,
                 failure_seconds=None):
        self.enabled = config.BUZZER_ENABLED if enabled is None else enabled
        self.gpio_module = gpio_module
        self.pin = config.BUZZER_GPIO
        self.frequency = config.BUZZER_FREQUENCY_HZ
        self.duty_cycle = config.BUZZER_DUTY_CYCLE
        self.beep_seconds = (config.BUZZER_BEEP_SECONDS if beep_seconds is None
                             else beep_seconds)
        self.success_gap_seconds = (config.BUZZER_SUCCESS_GAP_SECONDS
                                    if success_gap_seconds is None
                                    else success_gap_seconds)
        self.success_repeat_seconds = (config.BUZZER_SUCCESS_REPEAT_SECONDS
                                       if success_repeat_seconds is None
                                       else success_repeat_seconds)
        self.failure_seconds = (config.BUZZER_FAILURE_SECONDS
                                if failure_seconds is None else failure_seconds)
        self.condition = threading.Condition()
        self.mode = self.SILENT
        self.generation = 0
        self.stopping = False
        self.thread = None
        self.available = False

    def start(self):
        if not self.enabled or self.thread:
            return
        self.thread = threading.Thread(target=self._run, name="usb-buzzer", daemon=True)
        self.thread.start()

    def export_started(self):
        self._set_mode(self.STARTED)

    def export_succeeded(self):
        self._set_mode(self.SUCCESS)

    def export_failed(self):
        self._set_mode(self.FAILED)

    def silence(self):
        self._set_mode(self.SILENT)

    def _set_mode(self, mode):
        if not self.enabled:
            return
        with self.condition:
            self.mode = mode
            self.generation += 1
            self.condition.notify_all()

    def _wait_unchanged(self, generation, seconds=None):
        with self.condition:
            changed = lambda: self.stopping or self.generation != generation
            self.condition.wait_for(changed, timeout=seconds)
            return not changed()

    def _set_silent_if_unchanged(self, generation):
        with self.condition:
            if not self.stopping and self.generation == generation:
                self.mode = self.SILENT
                self.generation += 1

    def _on(self, gpio, chip):
        gpio.tx_pwm(chip, self.pin, self.frequency, self.duty_cycle)

    def _off(self, gpio, chip):
        # Some installed lgpio builds reject tx_pwm(..., 0, 0). A zero-length
        # pulse is the portable cancellation operation; the write fixes LOW.
        try:
            gpio.tx_pulse(chip, self.pin, 0, 0)
        except Exception:
            pass
        try:
            gpio.gpio_write(chip, self.pin, 0)
        except Exception:
            pass

    def _started_pattern(self, gpio, chip, generation):
        self._on(gpio, chip)
        unchanged = self._wait_unchanged(generation, self.beep_seconds)
        self._off(gpio, chip)
        if unchanged:
            self._set_silent_if_unchanged(generation)

    def _success_pattern(self, gpio, chip, generation):
        cycle_started = time.monotonic()
        for index in range(3):
            self._on(gpio, chip)
            if not self._wait_unchanged(generation, self.beep_seconds):
                self._off(gpio, chip)
                return
            self._off(gpio, chip)
            if index < 2 and not self._wait_unchanged(
                    generation, self.success_gap_seconds):
                return
        remaining = self.success_repeat_seconds - (time.monotonic() - cycle_started)
        if remaining > 0:
            self._wait_unchanged(generation, remaining)

    def _run(self):
        gpio = self.gpio_module
        chip = None
        try:
            if gpio is None:
                gpio = importlib.import_module("lgpio")
            chip = gpio.gpiochip_open(0)
            gpio.gpio_claim_output(chip, self.pin, 0)
            self.available = True
            logger.info("USB audible status ready on GPIO %d", self.pin)
            while True:
                with self.condition:
                    self.condition.wait_for(
                        lambda: self.stopping or self.mode != self.SILENT)
                    if self.stopping:
                        break
                    mode = self.mode
                    generation = self.generation
                if mode == self.STARTED:
                    self._started_pattern(gpio, chip, generation)
                elif mode == self.SUCCESS:
                    self._success_pattern(gpio, chip, generation)
                elif mode == self.FAILED:
                    self._on(gpio, chip)
                    unchanged = self._wait_unchanged(generation, self.failure_seconds)
                    self._off(gpio, chip)
                    if unchanged:
                        self._set_silent_if_unchanged(generation)
        except Exception as exc:
            logger.warning("USB audible status unavailable: %s", exc)
        finally:
            self.available = False
            if gpio is not None and chip is not None:
                self._off(gpio, chip)
                try:
                    gpio.gpiochip_close(chip)
                except Exception:
                    pass

    def stop(self):
        if not self.thread:
            return True
        with self.condition:
            self.stopping = True
            self.generation += 1
            self.condition.notify_all()
        self.thread.join(timeout=3)
        return not self.thread.is_alive()
