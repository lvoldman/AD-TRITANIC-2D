"""QML smoke test with fake discovery; no serial commands or user profile writes."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from platform_gui import Setup, load_fonts
from test_platform_config import board


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        load_fonts()
        QQuickStyle.setStyle("Fusion")

    def test_qml_xy_xyz_swap_and_save(self):
        with patch("platform_gui.discover_boards", return_value=[board()]), \
             patch("platform_gui.load_config", side_effect=FileNotFoundError), \
             patch("platform_gui.save_config") as save:
            setup = Setup(Path(__file__).with_name(".gui-smoke-unused.json"))
            engine = QQmlApplicationEngine()
            warnings = []
            engine.warnings.connect(lambda items: warnings.extend(i.toString() for i in items))
            engine.rootContext().setContextProperty("setup", setup)
            engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("PlatformSetup.qml"))))
            self.assertTrue(engine.rootObjects(), warnings)
            QTest.qWait(150)
            self.assertEqual(len(setup.axisRows), 2)
            setup.setMotorCount(3)
            setup.assign("X", 2)
            self.assertEqual(len({r["motor"] for r in setup.axisRows}), 3)
            setup.setMotorCount(2)
            setup.chooseBoard(0)
            setup.save()
            self.assertEqual(set(save.call_args.args[2]), {"x", "y"})
            QTest.qWait(150)
            image = engine.rootObjects()[0].grabWindow()
            self.assertFalse(image.isNull())
            image.save(str(Path(__file__).with_name("gui_preview.png")))
            self.assertEqual(warnings, [])
            engine.rootObjects()[0].close()
            del engine


if __name__ == "__main__":
    unittest.main()
