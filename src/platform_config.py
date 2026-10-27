"""GUI configuration and USB discovery. Never opens a serial port."""
from __future__ import annotations
import json
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import cast
from serial.tools.list_ports_common import ListPortInfo

if __package__:
    from .platform_types import BoardInfo, PlatformConfig
else:
    from platform_types import BoardInfo, PlatformConfig

from serial.tools import list_ports
TMCM_VID: int = 0x2A3C
TMCM_PID: int = 0x0100

# List Trinamic USB candidates without opening their COM ports.
def discover_boards() -> list[BoardInfo]:
    """List Trinamic USB candidates without opening their COM ports."""
    boards: list[BoardInfo] = []
    # VID/PID identifies a device family; it does not prove model or firmware.
    port: ListPortInfo
    for port in sorted(list_ports.comports()):
        if (port.vid, port.pid) != (TMCM_VID, TMCM_PID):
            continue
        boards.append({"port": port.device, "vid": port.vid, "pid": port.pid,
                       "serial": port.serial_number or "",
                       "location": port.location or "",
                       "description": port.description or ""})
    return boards


# Return a copy of an XY/XYZ mapping, rejecting missing or shared outputs.
def validate_mapping(axes: Mapping[str, int]) -> dict[str, int]:
    """Return a copy of an XY/XYZ mapping, rejecting missing or shared outputs."""
    if set(axes) not in ({"x", "y"}, {"x", "y", "z"}):
        raise ValueError("Assign X/Y or X/Y/Z")
    if any(type(v) is not int or v not in (0, 1, 2) for v in axes.values()):
        raise ValueError("Output number must be 0, 1 or 2")
    if len(set(axes.values())) != len(axes):
        raise ValueError("A board output cannot be assigned to two axes")
    return dict(axes)


# Swap assignments if the chosen output is already used by another axis.
def select_motor(axes: Mapping[str, int], name: str, motor: int) -> dict[str, int]:
    """Swap assignments if the chosen output is already used by another axis."""
    result: dict[str, int] = validate_mapping(axes)
    if name not in result or type(motor) is not int or motor not in (0, 1, 2):
        raise ValueError("Invalid axis or output")
    previous: int = result[name]
    # Give the displaced axis the selected axis's former output.
    other: str
    for other in result:
        if other != name and result[other] == motor:
            result[other] = previous
    result[name] = motor
    return validate_mapping(result)


# Prefer a genuinely unique USB serial; otherwise match USB socket location.
def resolve_board(saved: BoardInfo, boards: Sequence[BoardInfo]) -> int:
    """Prefer a genuinely unique USB serial; otherwise match USB socket location.

    COM names are deliberately not used as persistent identity. TMCSTEP is a
    generic descriptor, not a per-board serial. Location identifies a socket,
    not a physical board. Return -1 when identification is ambiguous.
    """
    candidates: list[tuple[int, BoardInfo]] = [(i, b) for i, b in enumerate(boards)
                  if (b["vid"], b["pid"]) == (saved.get("vid"), saved.get("pid"))]
    serial: str = saved.get("serial", "")
    if serial and serial.upper() != "TMCSTEP":
        matches: list[int] = [i for i, b in candidates if b["serial"] == serial]
        if len(matches) == 1:
            return matches[0]
    location: str = saved.get("location", "")
    matches = [i for i, b in candidates if location and b["location"] == location
               and b["serial"] == serial]
    return matches[0] if len(matches) == 1 else -1


# Write validated settings, replacing the old file only after writing succeeds.
def save_config(path: str | Path, board: BoardInfo, axes: Mapping[str, int], address: int = 1) -> None:
    """Write validated settings, replacing the old file only after writing succeeds."""
    data: PlatformConfig = {"version": 1, "board": cast(BoardInfo, dict(board)),
                            "axes": validate_mapping(axes), "address": validate_address(address)}
    target_path: Path = Path(path)
    temporary: Path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target_path)


# Load settings and reject unsupported versions or invalid axis mappings.
def load_config(path: str | Path) -> PlatformConfig:
    """Load settings and reject unsupported versions or invalid axis mappings."""
    data: PlatformConfig = cast(PlatformConfig, json.loads(Path(path).read_text(encoding="utf-8")))
    if data.get("version") != 1 or not isinstance(data.get("board"), dict):
        raise ValueError("Unknown configuration format")
    validate_mapping(data["axes"])
    # Older settings files predate the ID selector and used the fixed address 1.
    data["address"] = validate_address(data.get("address", 1))
    return data


# Validate a TMCL destination ID without changing the address stored on the board.
def validate_address(address: int) -> int:
    if type(address) is not int or not 1 <= address <= 255:
        raise ValueError("Module address must be an integer in 1..255")
    return address
