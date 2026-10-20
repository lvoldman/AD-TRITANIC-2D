import uuid
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from platform_config import (discover_boards, load_config, resolve_board,
                             save_config, select_motor, validate_mapping)


def board(port="COM3", location="1-8", serial="TMCSTEP"):
    return dict(port=port, location=location, serial=serial,
                vid=0x2A3C, pid=0x0100, description="Trinamic")


class ConfigurationTests(unittest.TestCase):
    def test_duplicate_or_invalid_mapping_rejected(self):
        for axes in ({"x": 0, "y": 0}, {"x": 0, "z": 1},
                     {"x": True, "y": 1}, {"x": 0, "y": 3}):
            with self.assertRaises(ValueError):
                validate_mapping(axes)

    def test_swap_keeps_every_assignment_unique(self):
        axes = {"x": 0, "y": 1, "z": 2}
        self.assertEqual(select_motor(axes, "x", 2), {"x": 2, "y": 1, "z": 0})
        self.assertEqual(axes, {"x": 0, "y": 1, "z": 2})

    def test_xy_can_use_any_two_outputs(self):
        self.assertEqual(select_motor({"x": 0, "y": 1}, "y", 2), {"x": 0, "y": 2})

    def test_generic_serial_requires_location_not_com(self):
        self.assertEqual(resolve_board(board(), [board("COM9")]), 0)
        self.assertEqual(resolve_board(board(), [board(location="1-9")]), -1)
        self.assertEqual(resolve_board(board(), [board(), board()]), -1)

    def test_unique_serial_survives_socket_change(self):
        self.assertEqual(resolve_board(board(serial="ABC123"),
                                      [board("COM8", "1-9", "ABC123")]), 0)

    def test_json_roundtrip(self):
        path = Path(__file__).with_name(f".test-settings-{uuid.uuid4().hex}.json")
        try:
            save_config(path, board(), {"x": 2, "y": 0})
            self.assertEqual(load_config(path)["axes"], {"x": 2, "y": 0})
        finally:
            path.unlink(missing_ok=True)
            path.with_suffix(".json.tmp").unlink(missing_ok=True)

    def test_discovery_filters_without_opening_ports(self):
        ports = [SimpleNamespace(device="COM3", vid=0x2A3C, pid=0x0100,
                                 serial_number="TMCSTEP", location="1-8", description="USB")]
        with patch("platform_config.list_ports.comports", return_value=ports):
            self.assertEqual(discover_boards()[0]["port"], "COM3")


if __name__ == "__main__":
    unittest.main()
