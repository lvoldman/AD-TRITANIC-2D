"""Offline protocol/behavior checks; no serial port is opened."""
import unittest

from motor_platform import Platform


class FakeTMCL:
    def __init__(self):
        self.calls = []
        self.positions = {0: 10, 1: 20, 2: 30}
        self.slots = {}
        self.fail_start = False
        self.reached = True

    def get(self, ap, axis):
        return {3: 0, 8: int(self.reached), 140: 4, 153: 7, 154: 7}[ap]

    def position(self, axis):
        return self.positions[axis]

    def encoder_position(self, axis):
        return self.positions[axis] - 1

    def set(self, ap, value, axis):
        self.calls.append((5, ap, axis, value))

    def command(self, instruction, kind, axis, value):
        self.calls.append((instruction, kind, axis, value))
        if instruction == 30:
            self.slots[axis] = value
        if instruction == 4:
            if self.fail_start:
                raise IOError("reply lost")
            self.positions.update(self.slots)

    def stop(self, axis):
        self.calls.append((3, 0, axis, 0))


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeTMCL()
        self.platform = Platform(self.device, {"x": 2, "y": 0})

    def test_constructor_and_mapping(self):
        self.assertEqual(self.device.calls, [])
        self.assertEqual(self.platform.position(), {"x": 30, "y": 10})
        with self.assertRaises(ValueError):
            Platform(self.device, {"x": 0, "y": 0})

    def test_relative_group_start_after_all_targets(self):
        targets = self.platform.move_relative(x=800, y=-400)
        self.assertEqual(targets, {"x": 830, "y": -390})
        self.assertEqual(self.device.calls[-1], (4, 2, 0x45, 0))
        self.assertEqual([c for c in self.device.calls if c[0] == 30],
                         [(30, 0, 2, 830), (30, 0, 0, -390)])
        with self.assertRaises(RuntimeError):
            self.platform.move_relative(x=1)
        self.platform.wait(settle=0)
        self.platform.move_absolute(x=0)

    def test_xyz_mask_and_omitted_axis(self):
        platform = Platform(self.device, {"x": 1, "y": 2, "z": 0})
        platform.move_relative(x=1, y=2, z=3)
        self.assertEqual(self.device.calls[-1], (4, 2, 0x47, 0))

    def test_zero_and_bad_input_do_not_write(self):
        self.platform.move_relative(x=0)
        for args in ({"z": 1}, {"x": 1.5}, {"x": True},
                     {"x": 2**31 - 1}, {"x": 1, "speed": 0}):
            with self.assertRaises(ValueError):
                self.platform.move_relative(**args)
        self.assertEqual(self.device.calls, [])

    def test_failed_start_is_not_retried_and_stops_all(self):
        self.device.fail_start = True
        with self.assertRaises(IOError):
            self.platform.move_relative(x=5, y=5)
        self.assertEqual(sum(c[0] == 4 for c in self.device.calls), 1)
        self.assertEqual([c[2] for c in self.device.calls if c[0] == 3], [2, 0])

    def test_timeout_stops_every_mapped_axis(self):
        self.platform.move_relative(x=5)
        self.device.reached = False
        with self.assertRaises(TimeoutError):
            self.platform.wait(timeout=0.001, settle=0)
        self.assertEqual([c[2] for c in self.device.calls if c[0] == 3], [2, 0])

    def test_stop_attempts_other_axis_and_exposes_failure(self):
        def stop(axis):
            self.device.calls.append((3, 0, axis, 0))
            if axis == 2:
                raise IOError("disconnected")
        self.device.stop = stop
        with self.assertRaisesRegex(RuntimeError, "STOP not confirmed"):
            self.platform.stop()
        self.assertEqual([c[2] for c in self.device.calls], [2, 0])


if __name__ == "__main__":
    unittest.main()
