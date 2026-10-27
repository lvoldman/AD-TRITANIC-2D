"""Shared static types for controller access, configuration and queued GUI messages."""
from collections.abc import Callable
from typing import Protocol, TypeAlias, TypedDict


AxisMapping: TypeAlias = dict[str, int]
Positions: TypeAlias = dict[str, int]


class BoardInfo(TypedDict):
    """USB metadata; a COM name is a current endpoint, not a persistent identity."""

    port: str
    vid: int
    pid: int
    serial: str
    location: str
    description: str


class BoardChoice(BoardInfo):
    """USB candidate with an additional display label for QML."""

    label: str


class PlatformConfig(TypedDict):
    """Local settings: USB identity, TMCL destination ID and axis assignments."""

    version: int
    board: BoardInfo
    axes: AxisMapping
    address: int


class AxisInput(TypedDict):
    """Unvalidated text retained while the user edits a motion row."""

    distance: str
    absolute: bool


class AxisRow(AxisInput):
    """Active axis assignment and editable fields presented to QML."""

    name: str
    motor: int


class MotionRow(TypedDict):
    """Validated microstep distance/target and its coordinate mode."""

    distance: int
    absolute: bool


class WorkerRequest(TypedDict, total=False):
    """Action-specific data: Connect uses board/axes/address; Move uses rows/limits.

    Home actions use axis, with Go home also supplying motion limits. Stop,
    Disconnect and Configure carry an empty record. The action string is sent
    separately through the existing Qt signal.
    """

    board: BoardInfo
    axes: AxisMapping
    address: int
    axis: str
    rows: dict[str, MotionRow]
    single: bool
    speed: int
    acceleration: int
    timeout: int


class MotionReadings(TypedDict, total=False):
    """Optional counter snapshots attached to a worker status update."""

    positions: Positions
    encoders: Positions


class MotionState(MotionReadings):
    """Status delivered from the serial thread to the GUI thread."""

    message: str
    connected: bool
    moving: bool


class AxisController(Protocol):
    """Controller operations required by Platform; also implemented by offline fakes."""

    # Read an axis parameter without changing controller state.
    def get(self, parameter: int, axis: int, /) -> int: ...

    # Write one axis parameter; some test doubles have no acknowledgement value.
    def set(self, parameter: int, value: int, axis: int, /) -> int | None: ...

    # Request a soft stop for one output.
    def stop(self, axis: int, /) -> int | None: ...

    # Send one TMCL request and return its reply value when available.
    def command(self, instruction: int, kind: int, axis: int, value: int, /) -> int | None: ...

    # Read the commanded position counter for one output.
    def position(self, axis: int, /) -> int: ...

    # Read an encoder counter using its existing scaling.
    def encoder_position(self, axis: int, /) -> int: ...


class MotorController(AxisController, Protocol):
    """Additional connection and single-axis operations used by the GUI worker."""

    # Start one motor toward an absolute step-counter target.
    def move_absolute(self, microsteps: int, axis: int, /) -> int: ...

    # Apply the explicit bench settings without issuing a movement command.
    def configure_bench(self, axis: int = 0, encoder: bool = False) -> None: ...

    # Release the serial connection.
    def close(self) -> None: ...


ControllerFactory: TypeAlias = Callable[..., MotorController]
