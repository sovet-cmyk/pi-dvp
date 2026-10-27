#!/usr/bin/env python3
"""Short hardware check for the installed R005 battery monitor."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hardware.ina226 import INA226Monitor  # noqa: E402


def main() -> int:
    monitor = INA226Monitor()
    print("Battery-monitor test: keep DVP stationary and do not change wiring.")
    try:
        for index in range(10):
            sample = monitor.read()
            if sample is None:
                print(
                    "No valid sample. Check 3.3 V logic power, SDA/SCL and "
                    "the VBS-to-IN- sense wire."
                )
                return 1
            if index == 0:
                print(
                    f"Detected {monitor.description} at "
                    f"0x{monitor.address:02x}."
                )
            print(
                f"{index + 1:02d}: {sample.voltage:6.3f} V  "
                f"{sample.current:7.3f} A  {sample.power:7.2f} W  "
                f"bars={sample.bars}/4"
            )
            time.sleep(1)
    except KeyboardInterrupt:
        return 130
    finally:
        monitor.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
