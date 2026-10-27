"""Battery monitor support for INA226/R005 and compatible fixed-scale boards."""
from __future__ import annotations

from dataclasses import dataclass
import time

from app import config
from system.logger import logger


REG_CONFIG = 0x00
REG_SHUNT_VOLTAGE = 0x01
REG_COMPAT_CURRENT = 0x01
REG_BUS_VOLTAGE = 0x02
REG_POWER = 0x03
REG_CURRENT = 0x04
REG_CALIBRATION = 0x05
REG_MANUFACTURER_ID = 0xFE
REG_DIE_ID = 0xFF

MANUFACTURER_TI = 0x5449
INA226_DIE_IDS = frozenset((0x2260, 0x2261))
COMPAT_DIE_IDS = frozenset((0x2270,))

# INA226: 16 samples averaged, 1.1 ms bus/shunt conversions and continuous mode.
INA226_CONFIGURATION = 0x4527
# Compatible 0x2270 devices provide a factory-scaled current register.
COMPAT_CURRENT_LSB_A = 0.00125


@dataclass(frozen=True)
class BatterySample:
    voltage: float
    current: float
    power: float
    estimated_voltage: float
    bars: int


def battery_bars(voltage: float) -> int:
    thresholds = (
        config.BATTERY_BAR_1_V,
        config.BATTERY_BAR_2_V,
        config.BATTERY_BAR_3_V,
        config.BATTERY_BAR_4_V,
    )
    return sum(voltage >= threshold for threshold in thresholds)


class INA226Monitor:
    """Read the battery bus without making the UI depend on the sensor.

    The retained class name keeps upgrades compatible with earlier DVP releases.
    Detection distinguishes a standard INA226 from the installed R005 board that
    reports TI-compatible die ID 0x2270 at the non-standard address 0x50.
    """

    def __init__(self, bus=None, bus_factory=None):
        self.bus = bus
        self.bus_factory = bus_factory
        self.configured = False
        self.address: int | None = None
        self.variant: str | None = None
        self.filtered_voltage = None
        self.next_retry = 0.0
        self.last_warning = 0.0

    @staticmethod
    def _swap_word(value: int) -> int:
        return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)

    @staticmethod
    def _signed(value: int) -> int:
        return value - 0x10000 if value & 0x8000 else value

    @staticmethod
    def calibration_value() -> int:
        # TI INA226 datasheet: CAL = 0.00512 / (Current_LSB * Rshunt).
        value = int(0.00512 / (
            config.INA226_CURRENT_LSB_A * config.INA226_SHUNT_OHMS
        ))
        if not 1 <= value <= 0x7FFF:
            raise RuntimeError("battery-monitor calibration is outside the register range")
        return value

    @property
    def description(self) -> str:
        if self.variant == "ina226":
            return "INA226/R005"
        if self.variant == "compat2270":
            return "R005 compatible monitor"
        return "undetected monitor"

    def _open(self):
        if self.bus is not None:
            return
        if self.bus_factory is None:
            try:
                from smbus import SMBus
            except ImportError:
                from smbus2 import SMBus
            self.bus_factory = SMBus
        self.bus = self.bus_factory(config.INA226_I2C_BUS)

    def _read_at(self, address: int, register: int) -> int:
        return self._swap_word(self.bus.read_word_data(address, register))

    def _detect(self) -> tuple[int, str]:
        # Try the configured address first, then every standard INA2xx address
        # plus 0x50 used by the installed non-standard R005 module.
        candidates = [config.INA226_ADDRESS]
        candidates.extend(address for address in range(0x40, 0x51)
                          if address != config.INA226_ADDRESS)
        unsupported = []
        for address in candidates:
            try:
                manufacturer = self._read_at(address, REG_MANUFACTURER_ID)
                die_id = self._read_at(address, REG_DIE_ID)
            except OSError:
                continue
            if manufacturer != MANUFACTURER_TI:
                continue
            if die_id in INA226_DIE_IDS:
                return address, "ina226"
            if die_id in COMPAT_DIE_IDS:
                return address, "compat2270"
            unsupported.append(f"0x{address:02x}/0x{die_id:04x}")
        if unsupported:
            raise RuntimeError("unsupported battery monitor " + ", ".join(unsupported))
        raise RuntimeError("no supported battery monitor detected")

    def _write_u16(self, register: int, value: int):
        if self.address is None:
            raise RuntimeError("battery monitor has no detected address")
        self.bus.write_word_data(self.address, register, self._swap_word(value))

    def _configure(self):
        self._open()
        self.address, self.variant = self._detect()
        if self.variant == "ina226":
            self._write_u16(REG_CONFIG, INA226_CONFIGURATION)
            self._write_u16(REG_CALIBRATION, self.calibration_value())
            time.sleep(0.05)
        # The 0x2270-compatible device is already factory-scaled and powers up
        # in continuous mode. Do not write the INA226-only calibration register.
        self.configured = True
        logger.info("Battery monitor ready at 0x%02x (%s)",
                    self.address, self.description)

    def _read_u16(self, register: int) -> int:
        if self.address is None:
            raise RuntimeError("battery monitor has no detected address")
        return self._read_at(self.address, register)

    def _read_s16(self, register: int) -> int:
        return self._signed(self._read_u16(register))

    def _read_electrical(self) -> tuple[float, float]:
        voltage = self._read_u16(REG_BUS_VOLTAGE) * 0.00125
        if self.variant == "compat2270":
            current = self._read_s16(REG_COMPAT_CURRENT) * COMPAT_CURRENT_LSB_A
            return voltage, current

        shunt_voltage = self._read_s16(REG_SHUNT_VOLTAGE) * 2.5e-6
        current = self._read_s16(REG_CURRENT) * config.INA226_CURRENT_LSB_A
        # A second calculation catches an incorrect INA226 shunt/calibration.
        shunt_current = shunt_voltage / config.INA226_SHUNT_OHMS
        tolerance = max(0.15, abs(shunt_current) * 0.03)
        if abs(current - shunt_current) > tolerance:
            raise RuntimeError("battery-monitor current and shunt readings disagree")
        return voltage, current

    def read(self) -> BatterySample | None:
        if not config.INA226_ENABLED:
            return None
        now = time.monotonic()
        if now < self.next_retry:
            return None
        try:
            if not self.configured:
                self._configure()
            voltage, current = self._read_electrical()
            if not 4.0 <= voltage <= 10.0 or abs(current) > 16.5:
                raise RuntimeError("battery monitor returned an implausible sample")
            # Calculate this from the same voltage/current pair. Some compatible
            # R005 modules have a power register that does not track those values.
            power = voltage * current
            estimated = voltage + max(0.0, current) * config.BATTERY_LOAD_COMPENSATION_OHMS
            alpha = config.BATTERY_FILTER_ALPHA
            self.filtered_voltage = estimated if self.filtered_voltage is None else (
                alpha * estimated + (1.0 - alpha) * self.filtered_voltage
            )
            return BatterySample(
                voltage, current, power, self.filtered_voltage,
                battery_bars(self.filtered_voltage),
            )
        except (OSError, RuntimeError, ImportError, ZeroDivisionError) as exc:
            self.configured = False
            self.close()
            self.next_retry = now + 5.0
            if now - self.last_warning >= 30.0:
                logger.warning("Battery monitor unavailable: %s", exc)
                self.last_warning = now
            return None

    def close(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except (AttributeError, OSError):
                pass
        self.bus = None
        self.configured = False
        self.address = None
        self.variant = None
