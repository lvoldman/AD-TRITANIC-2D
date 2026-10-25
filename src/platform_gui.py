"""QML setup and motion control: python -m src.platform_gui.

Startup only discovers USB metadata. Serial access and motion require GUI actions.
"""
from __future__ import annotations
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, QThread, QMetaObject, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

if __package__:
    from .platform_types import (AxisInput, AxisRow, BoardChoice, BoardInfo,
                                 MotionRow, MotionState, PlatformConfig, WorkerRequest)
    from .motion_worker import MotionWorker
    from .platform_config import (discover_boards, load_config, resolve_board,
                                  save_config, select_motor)
else:
    from platform_types import (AxisInput, AxisRow, BoardChoice, BoardInfo,
                                MotionRow, MotionState, PlatformConfig, WorkerRequest)
    from motion_worker import MotionWorker
    from platform_config import (discover_boards, load_config, resolve_board,
                                 save_config, select_motor)


class Setup(QObject):
    """Expose setup and explicit motion actions; perform serial I/O in a worker."""

    # One notification refreshes all QML properties derived from the configuration.
    changed: Signal = Signal()
    motionChanged: Signal = Signal()
    request: Signal = Signal(str, object)

    # Load local setup preferences and discover USB candidates without connecting.
    def __init__(self, config_path: str | Path | None = None) -> None:
        super().__init__()
        self.changed.connect(self.motionChanged.emit)
        self._thread: QThread | None = None
        self._worker: MotionWorker | None = None
        self._cancelled: threading.Event = threading.Event()
        self._connected: bool = False
        self._busy: bool = False
        self._moving: bool = False
        self._inputs: dict[str, AxisInput] = {name: {"distance": "0", "absolute": False} for name in ("x", "y", "z")}
        self._summary: str = ""
        self.path: Path = Path(config_path or Path(__file__).resolve().parent.parent / "platform_settings.json")
        self._boards: list[BoardInfo] = []
        self._selected: int = -1
        self._axes: dict[str, int] = {"x": 0, "y": 1}
        self._message: str = "Select a board and assign the motor outputs."
        self._saved_board: BoardInfo | None = None
        if self.path.exists():
            try:
                data: PlatformConfig = load_config(self.path)
                self._axes = data["axes"]
                self._saved_board = data["board"]
                self._message = "Configuration loaded. Check the selected board."
            except Exception as exc:
                self._message = f"Could not load settings: {exc}"
        self.refresh()

    # Return device records with a readable label for the board selector.
    @Property('QVariantList', notify=changed)
    def boards(self) -> list[BoardChoice]:
        """Return device records with a readable label for the board selector."""
        return [{**b, "label": f"{b['port']} · Trinamic · USB {b['location'] or '—'}"}
                for b in self._boards]

    # Return the selected list index, or -1 when selection is unresolved.
    @Property(int, notify=changed)
    def selected(self) -> int:
        """Return the selected list index, or -1 when selection is unresolved."""
        return self._selected

    # Return only active axes; two-motor mode has no Z row.
    @Property('QVariantList', notify=changed)
    def axisRows(self) -> list[AxisRow]:
        """Return only active axes; two-motor mode has no Z row."""
        return [{"name": name.upper(), "motor": motor, **self._inputs[name]}
                for name, motor in self._axes.items()]

    # Return the manually configured motor count, not a detected count.
    @Property(int, notify=changed)
    def motorCount(self) -> int:
        """Return the manually configured motor count, not a detected count."""
        return len(self._axes)

    # Return the latest status or error message displayed by QML.
    @Property(str, notify=motionChanged)
    def message(self) -> str:
        """Return the latest status or error message displayed by QML."""
        return self._message

    # Describe the selected USB candidate without querying its firmware.
    @Property(str, notify=changed)
    def boardDetails(self) -> str:
        """Describe the selected USB candidate without querying its firmware."""
        if self._selected < 0:
            return "No board selected. The list shows Trinamic USB candidates with VID:PID 2A3C:0100."
        b: BoardInfo = self._boards[self._selected]
        return (f"{b['description']}\nVID:PID 2A3C:0100   •   S/N: {b['serial'] or '—'}"
                f"\nUSB location: {b['location'] or 'unknown'}")

    # Rescan USB metadata and restore selection only when identity resolves.
    @Slot()
    def refresh(self) -> None:
        """Rescan USB metadata and restore selection only when identity resolves."""
        if self._connected or self._busy:
            return
        previous: BoardInfo | None = (self._boards[self._selected] if self._selected >= 0
                    else self._saved_board)
        try:
            self._boards: list[BoardInfo] = discover_boards()
            self._selected: int = resolve_board(previous, self._boards) if previous else -1
        except Exception as exc:
            self._boards, self._selected = [], -1
            self._message: str = f"Discovery failed: {exc}"
        self.changed.emit()

    # Accept a valid selector index; choosing a board does not connect to it.
    @Slot(int)
    def chooseBoard(self, index: int) -> None:
        """Accept a valid selector index; choosing a board does not connect to it."""
        if not self._connected and not self._busy and 0 <= index < len(self._boards):
            self._selected: int = index
            self._message: str = "Board selected. Check the output-to-axis assignments."
            self.changed.emit()

    # Remove Z for XY mode, or assign the remaining free output to Z.
    @Slot(int)
    def setMotorCount(self, count: int) -> None:
        """Remove Z for XY mode, or assign the remaining free output to Z."""
        if self._connected or self._busy:
            return
        if count == 2:
            self._axes.pop("z", None)
        elif count == 3:
            self._axes["z"] = self._axes.get("z", next(iter(set(range(3)) - set(self._axes.values())), 2))
        else:
            return
        self._message: str = "Motor count set manually. Check the connected motors."
        self.changed.emit()

    # Apply an output selection, swapping assignments when necessary.
    @Slot(str, int)
    def assign(self, name: str, motor: int) -> None:
        """Apply an output selection, swapping assignments when necessary."""
        if self._connected or self._busy:
            return
        try:
            self._axes: dict[str, int] = select_motor(self._axes, name.lower(), motor)
            self._message: str = "Assignments updated. Assigned outputs swap places."
        except ValueError as exc:
            self._message = str(exc)
        self.changed.emit()

    # Recheck device presence before saving the selected board and axes.
    @Slot()
    def save(self) -> None:
        """Recheck device presence before saving the selected board and axes."""
        if self._selected < 0:
            self._message: str = "Select a board first."
            self.changed.emit()
            return
        try:
            selected: BoardInfo = self._boards[self._selected]
            live: list[BoardInfo] = discover_boards()
            index: int = resolve_board(selected, live)
            if index < 0 or live[index]["port"] != selected["port"]:
                raise ValueError("Board disconnected or port changed. Refresh the list.")
            save_config(self.path, live[index], self._axes)
            self._saved_board: BoardInfo | None = live[index]
            self._message = f"Saved: {self.path.name}"
        except Exception as exc:
            self._message = f"Could not save settings: {exc}"
        self.changed.emit()


    # Report whether a serial session has been opened by an explicit Connect action.
    @Property(bool, notify=motionChanged)
    def connected(self) -> bool:
        return self._connected

    # Lock competing operations while a request or motion is in progress.
    @Property(bool, notify=motionChanged)
    def busy(self) -> bool:
        return self._busy

    # Display step-counter and scaled encoder readings returned by the worker.
    @Property(str, notify=motionChanged)
    def motionSummary(self) -> str:
        return self._summary

    # Start the serial worker only when the user first requests a connection.
    def _ensure_worker(self) -> None:
        if self._thread is not None:
            return
        self._thread: QThread | None = QThread(self)
        self._worker: MotionWorker | None = MotionWorker(self._cancelled)
        self._worker.moveToThread(self._thread)
        self.request.connect(self._worker.execute)
        self._worker.updated.connect(self._motion_update)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    # Update GUI state from worker signals without rebuilding the axis input fields.
    @Slot(object)
    def _motion_update(self, state: MotionState) -> None:
        self._connected: bool = state["connected"]
        self._moving: bool = state["moving"]
        self._busy: bool = self._moving
        self._message: str = state["message"]
        if "positions" in state:
            self._summary: str = "Step counters: " + "   ".join(
                f"{name.upper()} = {value}" for name, value in state["positions"].items())
        if "encoders" in state:
            self._summary += "\nEncoders (existing scaling): " + "   ".join(
                f"{name.upper()} = {value}" for name, value in state["encoders"].items())
        self.motionChanged.emit()

    # Queue an operation using a fresh cancellation flag and disable conflicting actions.
    def _submit(self, action: str, data: WorkerRequest) -> None:
        self._cancelled.clear()
        self._busy: bool = True
        self._message: str = "Working…"
        self.motionChanged.emit()
        self.request.emit(action, data)

    # Open the selected board on demand; disconnecting is allowed only while idle.
    @Slot()
    def toggleConnection(self) -> None:
        if self._busy:
            return
        if self._connected:
            self._submit("disconnect", {})
        elif self._selected >= 0:
            self._ensure_worker()
            self._submit("connect", {"board": dict(self._boards[self._selected]),
                                     "axes": dict(self._axes)})

    # Explicitly apply the previously tested motor/encoder settings without moving.
    @Slot()
    def configureMotors(self) -> None:
        if self._connected and not self._busy:
            self._submit("configure", {})

    # Preserve text exactly until Move validates it as an integer number of microsteps.
    @Slot(str, str, bool)
    def setMotionInput(self, name: str, distance: str, absolute: bool) -> None:
        key: str = name.lower()
        if key in self._axes and not self._busy:
            self._inputs[key] = {"distance": distance, "absolute": absolute}

    # Validate a snapshot of one row or all rows and queue exactly one motion request.
    @Slot(str, int, int, int)
    def move(self, name: str, speed: int, acceleration: int, timeout: int) -> None:
        if not self._connected or self._busy:
            return
        try:
            names: list[str] = [name.lower()] if name else list(self._axes)
            if any(key not in self._axes for key in names):
                raise ValueError("Axis is not configured.")
            rows: dict[str, MotionRow] = {}
            key: str
            for key in names:
                raw: str = self._inputs[key]["distance"].strip()
                if not raw or raw.lstrip("+-").isdigit() is False:
                    raise ValueError(f"{key.upper()}: enter an integer distance in microsteps.")
                value: int = int(raw)
                if not -(2**31) <= value <= 2**31 - 1:
                    raise ValueError(f"{key.upper()}: distance exceeds signed 32-bit range.")
                rows[key] = {"distance": value, "absolute": self._inputs[key]["absolute"]}
            if not 1 <= speed <= 2047 or not 1 <= acceleration <= 2047 or timeout <= 0:
                raise ValueError("Invalid speed, acceleration or timeout.")
            self._submit("move", {"rows": rows, "single": bool(name), "speed": speed,
                                  "acceleration": acceleration, "timeout": timeout})
        except ValueError as exc:
            self._message: str = str(exc)
            self.motionChanged.emit()

    # Request cancellation immediately, then let the serial worker stop every mapped axis.
    @Slot()
    def stopMotion(self) -> None:
        if self._connected or self._busy:
            self._cancelled.set()
            self._message: str = "Stop requested…"
            self.motionChanged.emit()
            self.request.emit("stop", {})

    # Stop/close in the serial thread before allowing Qt to destroy that thread.
    @Slot()
    def shutdown(self) -> None:
        if self._thread and self._thread.isRunning():
            self._cancelled.set()
            QMetaObject.invokeMethod(self._worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
            self._thread.quit()
            self._thread.wait()


# Register available Windows fonts for normal and offscreen Qt rendering.
def load_fonts() -> None:
    """Register available Windows fonts for normal and offscreen Qt rendering."""
    # Explicit registration also supports offscreen Windows rendering.
    fonts: Path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    filename: str
    for filename in ("segoeui.ttf", "segoeuib.ttf"):
        path: Path = fonts / filename
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


# Load the QML window and return the application exit code.
def main() -> int:
    """Load the QML window and return the application exit code."""
    app: QGuiApplication = QGuiApplication(sys.argv)
    app.setApplicationName("Tritanic · Platform Setup")
    load_fonts()
    QQuickStyle.setStyle("Fusion")
    setup: Setup = Setup()
    app.aboutToQuit.connect(setup.shutdown)
    # Keep the Python backend alive as long as QML can access its properties.
    engine: QQmlApplicationEngine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("setup", setup)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("PlatformSetup.qml"))))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
