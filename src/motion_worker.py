"""Serial operations executed in a dedicated Qt thread, never in the GUI thread."""
from __future__ import annotations
import threading
import time
from typing import cast

from PySide6.QtCore import QObject, QTimer, Signal, Slot

if __package__:
    from .platform_types import BoardInfo, ControllerFactory, MotorController, MotionRow, MotionState, WorkerRequest
    from .bs3ADTritanic import TMCL
    from .motor_platform import Platform
    from .platform_config import discover_boards, resolve_board, validate_address
else:
    from platform_types import BoardInfo, ControllerFactory, MotorController, MotionRow, MotionState, WorkerRequest
    from bs3ADTritanic import TMCL
    from motor_platform import Platform
    from platform_config import discover_boards, resolve_board, validate_address


class MotionWorker(QObject):
    updated: Signal = Signal(object)

    # Keep all serial state in the worker; construction opens no ports.
    def __init__(self, cancelled: threading.Event, factory: ControllerFactory | None = None) -> None:
        super().__init__()
        self.cancelled: threading.Event = cancelled
        self.factory: ControllerFactory = factory or TMCL
        self.controller: MotorController | None = None
        self.platform: Platform | None = None
        self.targets: dict[str, int] = {}
        self.timer: QTimer | None = None
        self.deadline: float = 0.0
        self.settled: float | None = None

    # Report state changes through a queued signal instead of touching QML objects.
    def report(self, message: str, **state: dict[str, int]) -> None:
        update: MotionState = cast(MotionState, {
            "message": message, "connected": self.controller is not None,
            "moving": bool(self.targets), **state,
        })
        self.updated.emit(update)

    # Execute one GUI request; serial errors invalidate the session and never retry motion.
    @Slot(str, object)
    def execute(self, action: str, data: WorkerRequest) -> None:
        try:
            if action == "connect":
                boards: list[BoardInfo] = discover_boards()
                index: int = resolve_board(data["board"], boards)
                if index < 0:
                    raise RuntimeError("Board not found unambiguously. Refresh and select it again.")
                address: int = validate_address(data.get("address", 1))
                self.controller: MotorController | None = self.factory(boards[index]["port"], address=address)
                self.platform: Platform | None = Platform(self.controller, data["axes"], before_start=self.check_cancelled)
                self.report("Connected. Existing motor settings are unchanged.",
                            positions=self.platform.position())
            elif action == "disconnect":
                self.close()
                self.report("Disconnected.")
            elif action == "stop":
                self.stop()
            elif action == "configure":
                self.require_idle()
                motor: int
                for motor in self.platform.axes.values():
                    self.check_cancelled()
                    self.controller.configure_bench(motor, encoder=True)
                self.report("Test settings applied in RAM: 16 microsteps, run 48, hold 16; encoder scaled.")
            elif action == "move":
                self.start_move(data)
            elif action == "set_home":
                self.set_home(data["axis"])
            elif action == "go_home":
                self.go_home(data)
            else:
                raise ValueError("Unknown worker request")
        except Exception as exc:
            self.fail(exc)

    # Reject operations until connected and all configured axes are stationary.
    def require_idle(self) -> None:
        if self.controller is None or self.platform is None:
            raise RuntimeError("Connect to a board first.")
        if self.targets or any(self.controller.get(3, m) != 0 for m in self.platform.axes.values()):
            raise RuntimeError("An axis is moving. Stop it before starting another operation.")

    # Honor a Stop request even if it arrived while the worker was preparing a move.
    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise RuntimeError("Operation cancelled by Stop.")

    # Set the current measured position to zero without moving or changing AP1/AP0.
    def set_home(self, name: str) -> None:
        self.require_idle()
        if name not in self.platform.axes:
            raise ValueError("Requested axis is not configured.")
        motor: int = self.platform.axes[name]
        self.check_cancelled()
        self.controller.set(209, 0, motor)
        self.report(f"Home set for {name.upper()}: encoder zero; step counter unchanged.",
                    positions=self.platform.position(), encoders=self.platform.encoder_position())

    # Convert scaled encoder displacement into one relative move toward encoder zero.
    def go_home(self, data: WorkerRequest) -> None:
        self.require_idle()
        name: str = data["axis"]
        if name not in self.platform.axes:
            raise ValueError("Requested axis is not configured.")
        motor: int = self.platform.axes[name]
        resolution: int = self.controller.get(140, motor)
        mode: int = self.controller.get(201, motor)
        prescaler: int = self.controller.get(210, motor)
        # This project uses 200 full steps/rev and 40000 encoder counts/rev.
        # With decimal scaling, AP210 must be 50 * 2**AP140 for microstep units.
        if not 0 <= resolution <= 8 or mode not in (32, 33) or prescaler != 50 * (1 << resolution):
            raise ValueError("Go home requires encoder scaling in microsteps. Apply tested motor settings first.")
        encoder: int = self.controller.encoder_position(motor)
        if abs(encoder) > 2**31 - 1:
            raise ValueError("Encoder displacement exceeds the signed movement range.")
        request: WorkerRequest = {"rows": {name: {"distance": -encoder, "absolute": False}},
                                  "single": True, "speed": data["speed"],
                                  "acceleration": data["acceleration"], "timeout": data["timeout"]}
        # One positioning command only: do not automatically chase residual encoder error.
        self.start_move(request)

    # Resolve mixed absolute/relative rows once and start only the requested outputs.
    def start_move(self, data: WorkerRequest) -> None:
        self.require_idle()
        self.check_cancelled()
        current: dict[str, int] = self.platform.position()
        targets: dict[str, int] = {}
        name: str
        row: MotionRow
        for name, row in data["rows"].items():
            if name not in self.platform.axes:
                raise ValueError("Requested axis is not configured.")
            value: int = row["distance"]
            target: int = value if row["absolute"] else current[name] + value
            if not -(2**31) <= target <= 2**31 - 1 or abs(target - current[name]) > 2**31 - 1:
                raise ValueError("Target exceeds the controller's signed position range.")
            targets[name] = target
        acceleration: int
        speed: int
        speed, acceleration = data["speed"], data["acceleration"]
        if not 1 <= speed <= 2047 or not 1 <= acceleration <= 2047:
            raise ValueError("Speed and acceleration must be 1..2047 (internal units).")
        self.check_cancelled()
        moving_targets: dict[str, int] = {name: target for name, target in targets.items()
                          if current[name] != target}
        if not moving_targets:
            self.report("No movement needed.", positions=current)
            return
        if data["single"]:
            name, target = next(iter(targets.items()))
            motor: int = self.platform.axes[name]
            self.controller.set(4, speed, motor)
            self.controller.set(5, acceleration, motor)
            self.check_cancelled()
            self.controller.move_absolute(target, motor)
        else:
            self.platform.move_absolute(speed=speed, acceleration=acceleration, **targets)
        # An unchanged axis may retain a stale target-reached flag after an earlier stop.
        # Wait only for outputs actually participating in this move.
        self.targets: dict[str, int] = moving_targets
        self.deadline: float = time.monotonic() + data["timeout"]
        self.settled: float | None = None
        if self.timer is None:
            self.timer: QTimer | None = QTimer(self)
            self.timer.setInterval(100)
            self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.report("Moving…")

    # Poll short batches so the worker event loop can process Stop between polls.
    @Slot()
    def poll(self) -> None:
        if not self.targets or self.controller is None:
            return
        try:
            if self.cancelled.is_set():
                self.stop()
                return
            positions: dict[str, int] = self.platform.position()
            reached: bool = all(positions[name] == target
                          and self.controller.get(8, self.platform.axes[name])
                          and self.controller.get(3, self.platform.axes[name]) == 0
                          for name, target in self.targets.items())
            now: float = time.monotonic()
            if reached:
                if self.settled is None:
                    self.settled: float | None = now + 0.3
                if now >= self.settled:
                    self.timer.stop()
                    # Clear Platform's pending group after its counters have reached target.
                    self.platform.wait_to_settle(timeout=1, settle=0)
                    self.targets: dict[str, int] = {}
                    self.report("Move complete.", positions=positions,
                                encoders=self.platform.encoder_position())
                    return
            else:
                self.settled = None
            if now >= self.deadline:
                raise TimeoutError("Motion timed out; stop requested.")
            self.report("Moving…", positions=positions)
        except Exception as exc:
            self.fail(exc)

    # Stop all mapped motors; holding current remains enabled after a soft stop.
    def stop(self, report: bool = True) -> None:
        if self.timer:
            self.timer.stop()
        if self.platform:
            self.platform.stop()
        self.targets: dict[str, int] = {}
        if report:
            self.report("Stop acknowledged. Holding current remains enabled.")

    # Close the session after stopping any motion; never silently discard stop failures.
    def close(self) -> None:
        try:
            if self.targets:
                self.stop(report=False)
        finally:
            if self.timer:
                self.timer.stop()
            if self.controller:
                self.controller.close()
            self.controller: MotorController | None
            self.platform: Platform | None
            self.controller, self.platform = None, None
            self.targets: dict[str, int] = {}

    # Attempt every mapped stop, report failures, and require explicit reconnection.
    def fail(self, error: Exception) -> None:
        message: str = f"{type(error).__name__}: {error}"
        try:
            if self.platform:
                self.stop(report=False)
        except Exception as stop_error:
            message += f" | STOP could not be confirmed: {stop_error}"
        finally:
            try:
                self.close()
            except Exception as close_error:
                message += f" | Close failed: {close_error}"
        self.report(message)

    # Handle application exit in the serial thread, reporting any unconfirmed stop.
    @Slot()
    def shutdown(self) -> None:
        try:
            self.close()
        except Exception as exc:
            self.fail(exc)
