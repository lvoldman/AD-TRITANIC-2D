"""Offline motion tests: all serial requests go to a simulated controller."""
from __future__ import annotations
import threading
import unittest
from collections.abc import Callable
from unittest.mock import patch

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication

from src.motion_worker import MotionWorker
from src.platform_types import MotionRow, MotionState, WorkerRequest
from unitests.test_motor_platform import FakeTMCL
from unitests.test_platform_config import board


class MotionController(FakeTMCL):
    # Initialize a simulated connection without opening a serial port.
    def __init__(self, port: str="COM3", address: int=1) -> None:
        super().__init__()
        self.closed: bool = False
        self.encoders: dict[int, int] = {motor: position - 1 for motor, position in self.positions.items()}
        self.encoder_settings: dict[int, int] = {201: 32, 210: 800}

    # Return encoder configuration as well as simulated motion state.
    def get(self, ap: int, axis: int) -> int:
        return self.encoder_settings[ap] if ap in self.encoder_settings else super().get(ap, axis)

    # Keep a separate encoder origin so zeroing it does not change the step counter.
    def encoder_position(self, axis: int) -> int:
        return self.encoders[axis]

    # Simulate an encoder-counter reset while recording every parameter write.
    def set(self, ap: int, value: int, axis: int) -> None:
        super().set(ap, value, axis)
        if ap == 209:
            self.encoders[axis] = value

    # Record a single-axis absolute command and update only that step counter.
    def move_absolute(self, target: int, axis: int=0) -> int:
        self.encoders[axis] += target - self.positions[axis]
        self.calls.append((4, 0, axis, target))
        self.positions[axis] = target
        return 0

    # Record explicit configuration without changing motor hardware.
    def configure_bench(self, axis: int=0, encoder: bool=False) -> None:
        self.calls.append(("configure", axis, encoder))

    # Mark the simulated serial session closed.
    def close(self) -> None:
        self.closed: bool = True


class MotionWorkerTests(unittest.TestCase):
    # Provide a Qt event dispatcher for the worker's polling timer.
    @classmethod
    def setUpClass(cls) -> None:
        cls.app: QGuiApplication = QGuiApplication.instance() or QGuiApplication([])

    # Connect each worker to a fresh fake controller using fake USB discovery.
    def setUp(self) -> None:
        self.cancelled: threading.Event = threading.Event()
        self.device: MotionController = MotionController()
        self.worker: MotionWorker = MotionWorker(self.cancelled, factory=lambda *a, **k: self.device)
        self.states: list[MotionState] = []
        self.worker.updated.connect(self.states.append)
        with patch("src.motion_worker.discover_boards", return_value=[board()]):
            self.worker.execute("connect", {"board": board(), "axes": {"x": 2, "y": 0}})
        self.assertTrue(self.states[-1]["connected"])
        self.assertEqual(self.device.calls, [])

    # Stop timers and close the fake session after each test.
    def tearDown(self) -> None:
        self.worker.shutdown()

    # Build a motion request with the same explicit units as the GUI.
    def request(self, rows: dict[str, MotionRow], single: bool = False) -> WorkerRequest:
        return {"rows": rows, "single": single, "speed": 200,
                "acceleration": 100, "timeout": 20}

    # Check that an independent relative move touches only its mapped output.
    def test_single_relative_and_absolute(self) -> None:
        self.worker.execute("move", self.request({"x": {"distance": 800, "absolute": False}}, True))
        self.assertIn((4, 0, 2, 830), self.device.calls)
        self.assertFalse(any(c[0] == 30 for c in self.device.calls))
        self.assertEqual(self.device.positions[0], 10)
        self.worker.stop()
        self.worker.execute("move", self.request({"y": {"distance": -100, "absolute": True}}, True))
        self.assertIn((4, 0, 0, -100), self.device.calls)

    # Verify mixed row modes become absolute coordinates before one group command.
    def test_mixed_platform_modes(self) -> None:
        self.worker.execute("move", self.request({"x": {"distance": 800, "absolute": False},
                                                  "y": {"distance": -100, "absolute": True}}))
        self.assertIn((30, 0, 2, 830), self.device.calls)
        self.assertIn((30, 0, 0, -100), self.device.calls)
        self.assertEqual(self.device.calls[-1], (4, 2, 0x45, 0))

    # Check that completion clears pending group state after shaft settling.
    def test_completion_then_second_move(self) -> None:
        data: WorkerRequest = self.request({"x": {"distance": 8, "absolute": False}})
        self.worker.execute("move", data)
        self.worker.settled = 0
        self.worker.poll()
        self.assertFalse(self.states[-1]["moving"])
        self.assertIn("encoders", self.states[-1])
        self.worker.execute("move", data)
        self.assertTrue(self.states[-1]["moving"])

    # Reject an overflowing relative target before writing any motor parameters.
    def test_overflow_never_starts(self) -> None:
        self.worker.execute("move", self.request({"x": {"distance": 2**31 - 1, "absolute": False}}, True))
        self.assertFalse(any(c[0] == 4 for c in self.device.calls))
        self.assertFalse(self.states[-1]["connected"])

    # Check that timeout stops every configured axis and closes the failed session.
    def test_timeout_and_stop(self) -> None:
        self.worker.execute("move", self.request({"x": {"distance": 10, "absolute": False}}))
        self.device.reached = False
        self.worker.deadline = 0
        self.worker.poll()
        self.assertEqual([c[2] for c in self.device.calls if c[0] == 3], [2, 0])
        self.assertFalse(self.states[-1]["connected"])
        self.assertIn("timed out", self.states[-1]["message"])

    # Simulate Stop during coordinate preparation and check that group start is cancelled.
    def test_cancel_during_preparation(self) -> None:
        original: Callable[..., int | None] = self.device.command
        # Set cancellation as soon as a target is staged, before MVP can be sent.
        def cancel_on_coordinate(instruction: int, kind: int, axis: int, value: int) -> None:
            original(instruction, kind, axis, value)
            if instruction == 30:
                self.cancelled.set()
        self.device.command = cancel_on_coordinate
        self.worker.execute("move", self.request({"x": {"distance": 10, "absolute": False}}))
        self.assertFalse(any(c[0] == 4 for c in self.device.calls))
        self.assertIn("cancelled", self.states[-1]["message"])

    # Confirm that parameter configuration only happens on an explicit request.
    def test_explicit_configuration(self) -> None:
        self.worker.execute("configure", {})
        self.assertEqual(self.device.calls, [("configure", 2, True), ("configure", 0, True)])

    # Ignore stale target-reached flags on axes whose requested displacement is zero.
    def test_unchanged_axis_not_polled_for_target(self) -> None:
        original: Callable[..., int | None] = self.device.get
        # Simulate an idle Y axis that was previously stopped short of its old target.
        def get_with_stale_target(parameter: int, axis: int) -> int:
            return 0 if parameter == 8 and axis == 0 else original(parameter, axis)
        self.device.get = get_with_stale_target
        self.worker.execute("move", self.request({"x": {"distance": 8, "absolute": False},
                                                  "y": {"distance": 0, "absolute": False}}))
        self.assertEqual(set(self.worker.targets), {"x"})
        self.worker.settled = 0
        self.worker.poll()
        self.assertFalse(self.states[-1]["moving"])

    # Pass the selected TMCL ID to the connection instead of using a fixed address.
    def test_selected_board_id(self) -> None:
        with patch("src.motion_worker.discover_boards", return_value=[board()]), \
             patch("src.motion_worker.TMCL", return_value=self.device) as constructor:
            worker: MotionWorker = MotionWorker(threading.Event())
            worker.execute("connect", {"board": board(), "axes": {"x": 2, "y": 0}, "address": 6})
            constructor.assert_called_once_with("COM3", address=6)
            worker.close()

    # Set home must issue no motion and must leave commanded coordinates intact.
    def test_set_home_only_zeroes_selected_encoder(self) -> None:
        self.worker.execute("set_home", {"axis": "x"})
        self.assertEqual(self.device.encoders[2], 0)
        self.assertEqual(self.device.positions[2], 30)
        self.assertEqual(self.device.encoders[0], 9)
        self.assertEqual(self.device.calls, [(5, 209, 2, 0)])
        self.assertEqual(self.states[-1]["encoders"]["x"], 0)

    # Return to the encoder reference after moving away, despite a different step origin.
    def test_set_then_go_home(self) -> None:
        self.worker.execute("set_home", {"axis": "x"})
        self.device.positions[2] += 100
        self.device.encoders[2] += 100
        self.worker.execute("go_home", {"axis": "x", "speed": 200,
                                         "acceleration": 100, "timeout": 20})
        self.assertIn((4, 0, 2, 30), self.device.calls)
        self.assertEqual(self.device.encoders[2], 0)
        self.assertEqual(self.device.positions[0], 10)
        self.assertEqual(sum(c[0] == 4 for c in self.device.calls), 1)

    # Do not assume controller zero equals encoder zero when their origins differ.
    def test_go_home_uses_encoder_displacement(self) -> None:
        self.device.positions[2] = 1000
        self.device.encoders[2] = -200
        self.worker.execute("go_home", {"axis": "x", "speed": 200,
                                         "acceleration": 100, "timeout": 20})
        self.assertIn((4, 0, 2, 1200), self.device.calls)
        self.assertEqual(self.device.encoders[2], 0)

    # Unknown encoder units must not be used to calculate a physical movement.
    def test_go_home_rejects_wrong_encoder_scale(self) -> None:
        self.device.encoder_settings[210] = 1
        self.worker.execute("go_home", {"axis": "x", "speed": 200,
                                         "acceleration": 100, "timeout": 20})
        self.assertFalse(any(c[0] == 4 for c in self.device.calls))
        self.assertIn("scaling", self.states[-1]["message"])

    # Do not reset an encoder reference while a requested move is still pending.
    def test_set_home_rejected_during_motion(self) -> None:
        self.worker.execute("move", self.request({"x": {"distance": 10, "absolute": False}}, True))
        self.worker.execute("set_home", {"axis": "x"})
        self.assertNotIn((5, 209, 2, 0), self.device.calls)


if __name__ == "__main__":
    unittest.main()
