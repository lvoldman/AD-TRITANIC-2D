"""QML platform setup: python platform_gui.py. Does not open serial ports.

Saved configuration can construct Platform(controller, config['axes']).
Connect controller only after rediscovering/resolving the selected board.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from platform_config import (discover_boards, load_config, resolve_board,
                             save_config, select_motor)


class Setup(QObject):
    changed = Signal()

    def __init__(self, config_path=None):
        super().__init__()
        self.path = Path(config_path or Path(__file__).with_name("platform_settings.json"))
        self._boards = []
        self._selected = -1
        self._axes = {"x": 0, "y": 1}
        self._message = "Select a board and assign the motor outputs."
        self._saved_board = None
        if self.path.exists():
            try:
                data = load_config(self.path)
                self._axes = data["axes"]
                self._saved_board = data["board"]
                self._message = "Configuration loaded. Check the selected board."
            except Exception as exc:
                self._message = f"Could not load settings: {exc}"
        self.refresh()

    @Property('QVariantList', notify=changed)
    def boards(self):
        return [{**b, "label": f"{b['port']} · Trinamic · USB {b['location'] or '—'}"}
                for b in self._boards]

    @Property(int, notify=changed)
    def selected(self):
        return self._selected

    @Property('QVariantList', notify=changed)
    def axisRows(self):
        return [{"name": name.upper(), "motor": motor}
                for name, motor in self._axes.items()]

    @Property(int, notify=changed)
    def motorCount(self):
        return len(self._axes)

    @Property(str, notify=changed)
    def message(self):
        return self._message

    @Property(str, notify=changed)
    def boardDetails(self):
        if self._selected < 0:
            return "No board selected. The list shows Trinamic USB candidates with VID:PID 2A3C:0100."
        b = self._boards[self._selected]
        return (f"{b['description']}\nVID:PID 2A3C:0100   •   S/N: {b['serial'] or '—'}"
                f"\nUSB location: {b['location'] or 'unknown'}")

    @Slot()
    def refresh(self):
        previous = (self._boards[self._selected] if self._selected >= 0
                    else self._saved_board)
        try:
            self._boards = discover_boards()
            self._selected = resolve_board(previous, self._boards) if previous else -1
        except Exception as exc:
            self._boards, self._selected = [], -1
            self._message = f"Discovery failed: {exc}"
        self.changed.emit()

    @Slot(int)
    def chooseBoard(self, index):
        if 0 <= index < len(self._boards):
            self._selected = index
            self._message = "Board selected. Check the output-to-axis assignments."
            self.changed.emit()

    @Slot(int)
    def setMotorCount(self, count):
        if count == 2:
            self._axes.pop("z", None)
        elif count == 3:
            self._axes["z"] = self._axes.get("z", next(iter(set(range(3)) - set(self._axes.values())), 2))
        else:
            return
        self._message = "Motor count set manually. Check the connected motors."
        self.changed.emit()

    @Slot(str, int)
    def assign(self, name, motor):
        try:
            self._axes = select_motor(self._axes, name.lower(), motor)
            self._message = "Assignments updated. Assigned outputs swap places."
        except ValueError as exc:
            self._message = str(exc)
        self.changed.emit()

    @Slot()
    def save(self):
        if self._selected < 0:
            self._message = "Select a board first."
            self.changed.emit()
            return
        try:
            selected = self._boards[self._selected]
            live = discover_boards()
            index = resolve_board(selected, live)
            if index < 0 or live[index]["port"] != selected["port"]:
                raise ValueError("Board disconnected or port changed. Refresh the list.")
            save_config(self.path, live[index], self._axes)
            self._saved_board = live[index]
            self._message = f"Saved: {self.path.name}"
        except Exception as exc:
            self._message = f"Could not save settings: {exc}"
        self.changed.emit()


def load_fonts():
    # Explicit registration also supports offscreen Windows rendering.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("segoeui.ttf", "segoeuib.ttf"):
        path = fonts / filename
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Tritanic · Platform Setup")
    load_fonts()
    QQuickStyle.setStyle("Fusion")
    setup = Setup()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("setup", setup)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("PlatformSetup.qml"))))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
