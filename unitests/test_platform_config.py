from __future__ import annotations
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from src.platform_types import BoardInfo
import json

from src.platform_config import (discover_boards, load_config, resolve_board,
                             save_config, select_motor, validate_mapping)


# Build a fake USB board record for discovery and configuration tests.
def board(port: str = "COM3", location: str = "1-8", serial: str = "TMCSTEP") -> BoardInfo:
    return dict(port=port, location=location, serial=serial,
                vid=0x2A3C, pid=0x0100, description="Trinamic")


class ConfigurationTests(unittest.TestCase):
    # Reject duplicate outputs, unsupported axis sets and invalid output numbers.
    def test_duplicate_or_invalid_mapping_rejected(self) -> None:
        axes: dict[str, int]
        for axes in ({"x": 0, "y": 0}, {"x": 0, "z": 1},
                     {"x": True, "y": 1}, {"x": 0, "y": 3}):
            with self.assertRaises(ValueError):
                validate_mapping(axes)

    # Verify that choosing an occupied output swaps axes without changing the input mapping.
    def test_swap_keeps_every_assignment_unique(self) -> None:
        axes: dict[str, int] = {"x": 0, "y": 1, "z": 2}
        self.assertEqual(select_motor(axes, "x", 2), {"x": 2, "y": 1, "z": 0})
        self.assertEqual(axes, {"x": 0, "y": 1, "z": 2})

    # Check that XY can use any distinct pair of the three board outputs.
    def test_xy_can_use_any_two_outputs(self) -> None:
        self.assertEqual(select_motor({"x": 0, "y": 1}, "y", 2), {"x": 0, "y": 2})

    # Check that generic serial strings require an unambiguous USB location match.
    def test_generic_serial_requires_location_not_com(self) -> None:
        self.assertEqual(resolve_board(board(), [board("COM9")]), 0)
        self.assertEqual(resolve_board(board(), [board(location="1-9")]), -1)
        self.assertEqual(resolve_board(board(), [board(), board()]), -1)

    # Verify that a unique serial identifies a board after its USB socket changes.
    def test_unique_serial_survives_socket_change(self) -> None:
        self.assertEqual(resolve_board(board(serial="ABC123"),
                                      [board("COM8", "1-9", "ABC123")]), 0)

    # Save and reload a configuration, then remove the temporary test files.
    def test_json_roundtrip(self) -> None:
        path: Path = Path(__file__).with_name(f".test-settings-{uuid.uuid4().hex}.json")
        try:
            save_config(path, board(), {"x": 2, "y": 0}, address=6)
            self.assertEqual(load_config(path)["axes"], {"x": 2, "y": 0})
            self.assertEqual(load_config(path)["address"], 6)
            # Files saved before the ID selector must keep using the former default.
            path.write_text(json.dumps({"version": 1, "board": board(), "axes": {"x": 0, "y": 1}}), encoding="utf-8")
            self.assertEqual(load_config(path)["address"], 1)
            with self.assertRaises(ValueError):
                save_config(path, board(), {"x": 0, "y": 1}, address=0)
        finally:
            path.unlink(missing_ok=True)
            path.with_suffix(".json.tmp").unlink(missing_ok=True)

    # Check USB discovery against fake OS metadata without opening serial ports.
    def test_discovery_filters_without_opening_ports(self) -> None:
        ports: list[SimpleNamespace] = [SimpleNamespace(device="COM3", vid=0x2A3C, pid=0x0100,
                                 serial_number="TMCSTEP", location="1-8", description="USB")]
        with patch("src.platform_config.list_ports.comports", return_value=ports):
            self.assertEqual(discover_boards()[0]["port"], "COM3")


if __name__ == "__main__":
    unittest.main()
