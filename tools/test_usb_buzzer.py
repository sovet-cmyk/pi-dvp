#!/usr/bin/env python3
"""Wait for a USB storage insertion and sound the GPIO17 buzzer once."""

import json
import subprocess
import time

import lgpio


BUZZER_GPIO = 17
BUZZER_FREQUENCY_HZ = 2000
BUZZER_DUTY_PERCENT = 50
BUZZER_SECONDS = 0.35
POLL_SECONDS = 0.5


def usb_storage_disks():
    completed = subprocess.run(
        ["lsblk", "--json", "--paths", "--output", "NAME,TYPE,TRAN"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    tree = json.loads(completed.stdout)
    return {
        node["name"]
        for node in tree.get("blockdevices", [])
        if node.get("type") == "disk" and node.get("tran") == "usb"
    }


def beep(chip):
    lgpio.tx_pwm(
        chip,
        BUZZER_GPIO,
        BUZZER_FREQUENCY_HZ,
        BUZZER_DUTY_PERCENT,
    )
    time.sleep(BUZZER_SECONDS)
    lgpio.tx_pulse(chip, BUZZER_GPIO, 0, 0)
    lgpio.gpio_write(chip, BUZZER_GPIO, 0)


def main():
    chip = lgpio.gpiochip_open(0)
    try:
        lgpio.gpio_claim_output(chip, BUZZER_GPIO, 0)

        present = usb_storage_disks()
        if present:
            print("Remove the USB storage device before starting the insertion test.")
            while usb_storage_disks():
                time.sleep(POLL_SECONDS)

        print("USB WAIT - insert the pendrive now (Ctrl+C cancels).", flush=True)
        baseline = usb_storage_disks()
        while True:
            current = usb_storage_disks()
            added = current - baseline
            if added:
                device = sorted(added)[0]
                print(f"USB DETECTED: {device}", flush=True)
                beep(chip)
                print("BEEP COMPLETE", flush=True)
                return
            baseline = current
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nTest cancelled.")
    finally:
        try:
            lgpio.tx_pulse(chip, BUZZER_GPIO, 0, 0)
            lgpio.gpio_write(chip, BUZZER_GPIO, 0)
        finally:
            lgpio.gpiochip_close(chip)


if __name__ == "__main__":
    main()
