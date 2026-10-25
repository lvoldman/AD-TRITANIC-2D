"""QML smoke test with fake discovery; no serial commands or user profile writes."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from src.platform_gui import Setup, load_fonts
from src.platform_types import WorkerRequest
from unitests.test_platform_config import board
from unitests.test_motion_worker import MotionController


# Search the visual tree because Repeater delegates need not share QObject parents.
def find_item(window: QQuickWindow, name: str) -> QObject | None:
    pending: list[QQuickItem] = [window.contentItem()]
    while pending:
        item: QQuickItem = pending.pop()
        if item.objectName() == name:
            return item
        pending.extend(item.childItems())
    return None


class GuiTests(unittest.TestCase):
    # Create the offscreen Qt application and load fonts once for GUI tests.
    @classmethod
    def setUpClass(cls) -> None:
        cls.app: QGuiApplication = QGuiApplication.instance() or QGuiApplication([])
        load_fonts()
        QQuickStyle.setStyle("Fusion")

    # Load QML with fake discovery and verify axis mode, swapping, saving and rendering.
    def test_qml_xy_xyz_swap_and_save(self) -> None:
        with patch("src.platform_gui.discover_boards", return_value=[board()]), \
             patch("src.platform_gui.load_config", side_effect=FileNotFoundError), \
             patch("src.platform_gui.save_config") as save:
            setup: Setup = Setup(Path(__file__).with_name(".gui-smoke-unused.json"))
            engine: QQmlApplicationEngine = QQmlApplicationEngine()
            warnings: list[str] = []
            engine.warnings.connect(lambda items: warnings.extend(i.toString() for i in items))
            engine.rootContext().setContextProperty("setup", setup)
            root: Path = Path(__file__).resolve().parent.parent
            engine.load(QUrl.fromLocalFile(str(root / "src" / "PlatformSetup.qml")))
            self.assertTrue(engine.rootObjects(), warnings)
            QTest.qWait(150)
            window: QQuickWindow = engine.rootObjects()[0]
            self.assertIsNotNone(find_item(window, "distanceX"))
            self.assertIsNotNone(find_item(window, "distanceY"))
            self.assertIsNone(find_item(window, "distanceZ"))
            self.assertFalse(find_item(window, "movePlatform").property("enabled"))
            self.assertEqual(find_item(window, "motionAcceleration").property("value"), 100)
            self.assertEqual(len(setup.axisRows), 2)
            setup.setMotorCount(3)
            QTest.qWait(50)
            self.assertIsNotNone(find_item(window, "distanceZ"))
            setup.assign("X", 2)
            self.assertEqual(len({r["motor"] for r in setup.axisRows}), 3)
            setup.setMotorCount(2)
            setup.chooseBoard(0)
            setup.save()
            self.assertEqual(set(save.call_args.args[2]), {"x", "y"})
            QTest.qWait(150)
            image: QImage = engine.rootObjects()[0].grabWindow()
            self.assertFalse(image.isNull())
            image.save(str(root / "docs" / "gui_preview.png"))
            self.assertEqual(warnings, [])
            engine.rootObjects()[0].close()
            del engine

    # Reject invalid distance text without queuing any motion or creating a worker.
    def test_motion_input_validation(self) -> None:
        with patch("src.platform_gui.discover_boards", return_value=[]):
            setup: Setup = Setup(Path(__file__).with_name(".gui-smoke-unused.json"))
        requests: list[tuple[str, WorkerRequest]] = []
        setup.request.connect(lambda action, data: requests.append((action, data)))
        setup._connected = True
        setup.setMotionInput("X", "invalid", False)
        setup.move("X", 200, 100, 20)
        self.assertEqual(requests, [])
        self.assertIn("integer", setup.message)
        setup.setMotionInput("X", "800", False)
        setup.setMotionInput("Y", "-100", True)
        setup.move("", 200, 100, 20)
        self.assertEqual(requests[-1][1]["rows"], {
            "x": {"distance": 800, "absolute": False},
            "y": {"distance": -100, "absolute": True}})
        setup.move("X", 200, 100, 20)
        self.assertEqual(len(requests), 1)

    # Exercise queued connection, motion and shutdown in a real QThread with fake serial I/O.
    def test_worker_thread_connection_and_shutdown(self) -> None:
        device: MotionController = MotionController()
        with patch("src.platform_gui.discover_boards", return_value=[board()]), \
             patch("src.motion_worker.discover_boards", return_value=[board()]), \
             patch("src.motion_worker.TMCL", return_value=device):
            setup: Setup = Setup(Path(__file__).with_name(".gui-smoke-unused.json"))
            setup.chooseBoard(0)
            try:
                setup.toggleConnection()
                _: int
                for _ in range(100):
                    QTest.qWait(10)
                    if not setup.busy:
                        break
                self.assertTrue(setup.connected, setup.message)
                setup.setMotionInput("X", "800", False)
                setup.move("X", 200, 100, 20)
                for _ in range(150):
                    QTest.qWait(10)
                    if not setup.busy:
                        break
                self.assertFalse(setup.busy, setup.message)
                self.assertEqual(device.positions[0], 810)
                self.assertIn("complete", setup.message)
                # Backend guards must prevent mapping changes during a connection too.
                setup.setMotorCount(3)
                self.assertEqual(setup.motorCount, 2)
            finally:
                setup.shutdown()
            self.assertTrue(device.closed)
            self.assertFalse(setup._thread.isRunning())


if __name__ == "__main__":
    unittest.main()
