"""XY/XYZ platform on one TMCM-3110, using its MVP COORD interpolation.

Positions are integer controller microsteps, NOT encoder measurements or mm.
speed/acceleration are AP4/AP5 INTERNAL units (1..2047), not path units/s.
The firmware adjusts participating axes for coordinated arrival. This is simple
firmware interpolation, not a guarantee of geometrically exact physical motion.
Equal axis scaling is required for interpreting step-space geometry physically.

Uses coordinate slot 0 (RAM only, irrespective of global parameter 84).
Reserve that slot and exclusive controller ownership for this platform: do not
issue commands through another instance, TMCL-IDE or a standalone TMCL program.
No EEPROM writes, encoder correction, homing or automatic motion retries.
Construction/import does not open a port or send commands. The caller owns TMCL.

Reference: TMCM-3110 firmware manual FW1.17 / Rev1.16, sections 3.7.4,
3.7.24 and 6.1. Interpolation on installed FW1.14 needs hardware validation.
https://www.analog.com/media/en/dsp-documentation/software-manuals/TMCM-3110-TMCL_firmware_manual_fw1.17_rev1.16.pdf

Usage (calls below would move hardware; this module has no executable demo):
    controller = TMCL("COM3")  # from src.bs3ADTritanic import TMCL
    platform = Platform(controller, axes={"x": 2, "y": 0})
    # Configure motors separately before moving; defaults are not changed here.
    platform.move_relative(x=800, y=400, speed=200, acceleration=100)
    platform.wait(timeout=20)
    # platform.stop() stops all mapped axes, retaining holding current.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable
from types import MappingProxyType
from collections.abc import Mapping

if __package__:
    from .platform_types import AxisController
else:
    from platform_types import AxisController


# Validate an integer range; bool is rejected despite being an int subclass.
def _integer(value: object, label: str, low: int, high: int) -> int:
    """Validate an integer range; bool is rejected despite being an int subclass."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")
    return value


class Platform:
    """One shared implementation for XY and XYZ with explicit motor mapping.

    Methods are serialized, except wait() releases the lock between polls so
    stop() can be used from a GUI thread. Axis mapping is immutable; construct a
    new instance while idle to change the mapping. Constructor performs no I/O.
    """

    # Validate the XY/XYZ output mapping and initialize shared motion state without I/O.
    def __init__(self, controller: AxisController, axes: Mapping[str, int], before_start: Callable[[], None] | None = None) -> None:
        mapping: dict[str, int] = dict(axes)
        if set(mapping) not in ({"x", "y"}, {"x", "y", "z"}):
            raise ValueError("axes must map x/y or x/y/z to motor outputs")
        motor: int
        name: str
        for name, motor in mapping.items():
            _integer(motor, f"motor for {name}", 0, 2)
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Each coordinate must use a different motor output")
        self.controller: AxisController = controller
        self.axes: MappingProxyType[str, int] = MappingProxyType(mapping)
        self._lock: threading.RLock = threading.RLock()
        self._targets: dict[str, int] | None = None
        self._before_start: Callable[[], None] | None = before_start

    # Read commanded step counters; this is not a physical measurement.
    def position(self) -> dict[str, int]:
        """Read commanded step counters; this is not a physical measurement."""
        with self._lock:
            return {name: self.controller.position(motor)
                    for name, motor in self.axes.items()}

    # Read encoder counters using their existing scaling, without changing it.
    def encoder_position(self) -> dict[str, int]:
        """Read encoder counters using their existing scaling, without changing it."""
        with self._lock:
            return {name: self.controller.encoder_position(motor)
                    for name, motor in self.axes.items()}

    # Start a coordinated relative move; omitted axes remain stationary.
    def move_relative(self, *, speed: int=200, acceleration: int=100, **offsets: int) -> dict[str, int]:
        """Start a coordinated relative move; omitted axes remain stationary.

        Returns absolute targets. Call wait() before starting another move.
        AP4/AP5 remain changed in RAM after completion. Other motor settings,
        current, encoder scaling and limit switches are not configured here.
        """
        return self._move(offsets, True, speed, acceleration)

    # Move relative to existing controller origins; no homing is implied.
    def move_absolute(self, *, speed: int=200, acceleration: int=100, **positions: int) -> dict[str, int]:
        """Move relative to existing controller origins; no homing is implied."""
        return self._move(positions, False, speed, acceleration)

    # Validate every target before preparing RAM coordinates and group start.
    def _move(self, coordinates: Mapping[str, int], relative: bool, speed: int, acceleration: int) -> dict[str, int]:
        """Validate every target before preparing RAM coordinates and group start."""
        _integer(speed, "speed (AP4)", 1, 2047)
        _integer(acceleration, "acceleration (AP5)", 1, 2047)
        if not coordinates or not set(coordinates) <= set(self.axes):
            raise ValueError("Supply at least one mapped coordinate: x, y or z")
        name: str
        value: int
        for name, value in coordinates.items():
            _integer(value, name, -(2**31), 2**31 - 1)
        with self._lock:
            if self._targets is not None:
                raise RuntimeError("Previous move pending; call wait() or stop()")
            motor: int
            for motor in self.axes.values():
                if self.controller.get(3, motor) != 0:
                    raise RuntimeError("Platform is already moving")
            current: dict[str, int] = self.position()
            targets: dict[str, int] = {}
            for name, value in coordinates.items():
                target: int = current[name] + value if relative else value
                _integer(target, f"target {name}", -(2**31), 2**31 - 1)
                if abs(target - current[name]) > 2**31 - 1:
                    raise ValueError("Move exceeds signed position distance range")
                if target != current[name]:
                    targets[name] = target
            if not targets:
                return dict(current)
            # Equal units are required before giving all axes the same limits.
            units: list[tuple[int, ...]] = [tuple(self.controller.get(ap, motor)
                           for ap in (140, 153, 154))
                     for motor in self.axes.values()]
            if len(set(units)) != 1:
                raise RuntimeError("Axes must have equal AP140/AP153/AP154 settings")
            _: int
            pulse_div: int
            ramp_div: int
            _, ramp_div, pulse_div = units[0]
            # Positioning ramps have divisor-dependent acceleration limits.
            lower: int = max(1, math.ceil(2 ** (ramp_div - pulse_div - 1)))
            upper: float = min(2047, 2 ** (ramp_div - pulse_div + 12) - 1)
            if not lower <= acceleration <= upper:
                raise ValueError("Acceleration is incompatible with axis divisors")
            try:
                mask: int = 0
                # Prepare all targets first: SCO stores a position but starts no motion.
                for name, target in targets.items():
                    motor = self.axes[name]
                    self.controller.set(4, speed, motor)
                    self.controller.set(5, acceleration, motor)
                    self.controller.command(30, 0, motor, target)  # SCO slot 0
                    mask |= 1 << motor
                # Remember targets BEFORE sending: a lost reply can hide a start.
                if self._before_start is not None:
                    self._before_start()
                self._targets: dict[str, int] | None = targets
                # Bit 6 selects interpolation; bits 0..2 select motor outputs.
                self.controller.command(4, 2, 0x40 | mask, 0)
            except BaseException:
                self._stop_after_failure()
                raise
            result: dict[str, int] = dict(current)
            result.update(targets)
            return result

    # Request soft stop on ALL mapped axes; attempt every axis on failure.
    def stop(self) -> None:
        """Request soft stop on ALL mapped axes; attempt every axis on failure.

        Holding current remains enabled. A transport failure can prevent stops.
        Returns after command acknowledgements, not after physical standstill.
        """
        with self._lock:
            failures: list[str] = []
            motor: int
            name: str
            for name, motor in self.axes.items():
                try:
                    self.controller.stop(motor)
                except Exception as exc:
                    failures.append(f"{name}: {exc}")
            if failures:
                raise RuntimeError("STOP not confirmed: " + "; ".join(failures))
            self._targets: dict[str, int] | None = None

    # Attempt to stop all mapped axes while preserving the original operation error.
    def _stop_after_failure(self) -> None:
        # Preserve the original failure and expose any stop failure as its cause.
        import sys
        original: BaseException | None = sys.exc_info()[1]
        try:
            self.stop()
        except Exception as stop_error:
            raise original from stop_error

    # Wait for target counters/zero velocity, then allow shaft settling.
    # settle: time to allow shaft to settle after reaching target position
    def wait_to_settle(self, timeout: float=20, settle: float=0.3) -> None:
        """Wait for target counters/zero velocity, then allow shaft settling.

        Does not verify encoder agreement. On timeout or read failure requests
        stop on every mapped axis; never retries a move. One waiter per instance.
        """
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if not math.isfinite(settle) or settle < 0:
            raise ValueError("settle must be nonnegative and finite")
        deadline: float = time.monotonic() + timeout
        with self._lock:
            pending: dict[str, int] | None = self._targets
        try:
            while True:
                with self._lock:
                    if self._targets is None or self._targets is not pending:
                        return
                    reached: bool = True
                    name: str
                    target: int
                    for name, target in self._targets.items():
                        motor: int = self.axes[name]
                        if not (self.controller.get(8, motor)
                                and self.controller.get(3, motor) == 0
                                and self.controller.position(motor) == target):
                            reached = False
                    if reached:
                        # Keep move pending throughout settling.
                        break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Platform target not reached")
                time.sleep(0.05)
            time.sleep(settle)
            with self._lock:
                if self._targets is pending:
                    # A concurrent stop/new move must not be cleared by this waiter.
                    self._targets: dict[str, int] | None = None
        except BaseException:
            self._stop_after_failure()
            raise
