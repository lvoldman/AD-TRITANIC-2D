"""Offline protocol/behavior checks; no serial port is opened."""
from __future__ import annotations
import unittest

from src.motor_platform import Platform


class FakeTMCL:
    # Initialize simulated positions and an empty command log without hardware access.
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int, int] | tuple[str, int, bool]] = []
        self.positions: dict[int, int] = {0: 10, 1: 20, 2: 30}
        self.slots: dict[int, int] = {}
        self.fail_start: bool = False
        self.reached: bool = True

    # Return simulated controller state and the tested microstep/ramp settings.
    def get(self, ap: int, axis: int) -> int:
        return {3: 0, 8: int(self.reached), 140: 4, 153: 7, 154: 7}[ap]

    # Return the simulated step counter for a motor output.
    def position(self, axis: int) -> int:
        return self.positions[axis]

    # Return a simulated encoder reading with a fixed one-count offset.
    def encoder_position(self, axis: int) -> int:
        return self.positions[axis] - 1

    # Record an axis parameter write instead of sending it to hardware.
    def set(self, ap: int, value: int, axis: int) -> None:
        self.calls.append((5, ap, axis, value))

    # Simulate coordinate storage and group start, including a lost-reply failure.
    def command(self, instruction: int, kind: int, axis: int, value: int) -> None:
        self.calls.append((instruction, kind, axis, value))
        if instruction == 30:
            self.slots[axis] = value
        if instruction == 4:
            if self.fail_start:
                raise IOError("reply lost")
            self.positions.update(self.slots)

    # Record the requested stop without operating hardware.
    def stop(self, axis: int) -> None:
        self.calls.append((3, 0, axis, 0))


class PlatformTests(unittest.TestCase):
    # Create a fresh simulated controller and platform for each test.
    def setUp(self) -> None:
        self.device: FakeTMCL = FakeTMCL()
        self.platform: Platform = Platform(self.device, {"x": 2, "y": 0})

    # Check that construction performs no I/O and rejects shared motor outputs.
    def test_constructor_and_mapping(self) -> None:
        self.assertEqual(self.device.calls, [])
        self.assertEqual(self.platform.position(), {"x": 30, "y": 10})
        with self.assertRaises(ValueError):
            Platform(self.device, {"x": 0, "y": 0})

    # Verify mapped targets are prepared before one interpolated group start.
    def test_relative_group_start_after_all_targets(self) -> None:
        targets: dict[str, int] = self.platform.move_relative(x=800, y=-400)
        self.assertEqual(targets, {"x": 830, "y": -390})
        self.assertEqual(self.device.calls[-1], (4, 2, 0x45, 0))
        self.assertEqual([c for c in self.device.calls if c[0] == 30],
                         [(30, 0, 2, 830), (30, 0, 0, -390)])
        with self.assertRaises(RuntimeError):
            self.platform.move_relative(x=1)
        self.platform.wait_to_settle(settle=0)
        self.platform.move_absolute(x=0)

    # Verify that a three-axis move selects all three motor outputs.
    def test_xyz_mask_and_omitted_axis(self) -> None:
        platform: Platform = Platform(self.device, {"x": 1, "y": 2, "z": 0})
        platform.move_relative(x=1, y=2, z=3)
        self.assertEqual(self.device.calls[-1], (4, 2, 0x47, 0))

    # Check that zero moves and invalid inputs send no controller writes.
    def test_zero_and_bad_input_do_not_write(self) -> None:
        self.platform.move_relative(x=0)
        args: dict[str, int | float]
        for args in ({"z": 1}, {"x": 1.5}, {"x": True},
                     {"x": 2**31 - 1}, {"x": 1, "speed": 0}):
            with self.assertRaises(ValueError):
                self.platform.move_relative(**args)
        self.assertEqual(self.device.calls, [])

    # Check that a lost start reply triggers stops without repeating the move.
    def test_failed_start_is_not_retried_and_stops_all(self) -> None:
        self.device.fail_start = True
        with self.assertRaises(IOError):
            self.platform.move_relative(x=5, y=5)
        self.assertEqual(sum(c[0] == 4 for c in self.device.calls), 1)
        self.assertEqual([c[2] for c in self.device.calls if c[0] == 3], [2, 0])

    # Verify a wait timeout requests a stop on every mapped motor output.
    def test_timeout_stops_every_mapped_axis(self) -> None:
        self.platform.move_relative(x=5)
        self.device.reached = False
        with self.assertRaises(TimeoutError):
            self.platform.wait_to_settle(timeout=0.001, settle=0)
        self.assertEqual([c[2] for c in self.device.calls if c[0] == 3], [2, 0])

    # Check that stopping continues on other axes when one stop fails.
    def test_stop_attempts_other_axis_and_exposes_failure(self) -> None:
        # Simulate one failed stop while recording every attempted motor output.
        def stop(axis: int) -> None:
            self.device.calls.append((3, 0, axis, 0))
            if axis == 2:
                raise IOError("disconnected")
        self.device.stop = stop
        with self.assertRaisesRegex(RuntimeError, "STOP not confirmed"):
            self.platform.stop()
        self.assertEqual([c[2] for c in self.device.calls], [2, 0])


if __name__ == "__main__":
    unittest.main()
