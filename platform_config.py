"""GUI configuration and USB discovery. Never opens a serial port."""
import json
from pathlib import Path

from serial.tools import list_ports


def discover_boards():
    boards = []
    for port in sorted(list_ports.comports()):
        if (port.vid, port.pid) != (0x2A3C, 0x0100):
            continue
        boards.append({"port": port.device, "vid": port.vid, "pid": port.pid,
                       "serial": port.serial_number or "",
                       "location": port.location or "",
                       "description": port.description or ""})
    return boards


def validate_mapping(axes):
    if set(axes) not in ({"x", "y"}, {"x", "y", "z"}):
        raise ValueError("Assign X/Y or X/Y/Z")
    if any(type(v) is not int or v not in (0, 1, 2) for v in axes.values()):
        raise ValueError("Output number must be 0, 1 or 2")
    if len(set(axes.values())) != len(axes):
        raise ValueError("A board output cannot be assigned to two axes")
    return dict(axes)


def select_motor(axes, name, motor):
    """Swap assignments if the chosen output is already used by another axis."""
    result = validate_mapping(axes)
    if name not in result or type(motor) is not int or motor not in (0, 1, 2):
        raise ValueError("Invalid axis or output")
    previous = result[name]
    for other in result:
        if other != name and result[other] == motor:
            result[other] = previous
    result[name] = motor
    return validate_mapping(result)


def resolve_board(saved, boards):
    """Prefer a genuinely unique USB serial; otherwise match USB socket location.

    COM names are deliberately not used as persistent identity. TMCSTEP is a
    generic descriptor, not a per-board serial. Location identifies a socket,
    not a physical board. Return -1 when identification is ambiguous.
    """
    candidates = [(i, b) for i, b in enumerate(boards)
                  if (b["vid"], b["pid"]) == (saved.get("vid"), saved.get("pid"))]
    serial = saved.get("serial", "")
    if serial and serial.upper() != "TMCSTEP":
        matches = [i for i, b in candidates if b["serial"] == serial]
        if len(matches) == 1:
            return matches[0]
    location = saved.get("location", "")
    matches = [i for i, b in candidates if location and b["location"] == location
               and b["serial"] == serial]
    return matches[0] if len(matches) == 1 else -1


def save_config(path, board, axes):
    data = {"version": 1, "board": dict(board), "axes": validate_mapping(axes)}
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_config(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("board"), dict):
        raise ValueError("Unknown configuration format")
    validate_mapping(data["axes"])
    return data
