from __future__ import annotations
__author__: str = "Leonid Voldman"
__copyright__: str = "Copyright 2024"
__credits__: list[str] = ["VoldmanTech"]
__license__: str = "SLA"
__version__: str = "1.0.0"
__maintainer__: str = "Leonid Voldman"
__email__: str = "vleonid@voldman.com"
__status__: str = "Tool"


import enum
from _thread import LockType
from serial.tools.list_ports_common import ListPortInfo
import argparse
import struct
import threading
import time
import serial
from serial.tools import list_ports



"""

Read-only by default. --move configures axis 0 for a free-shaft bench test:
16 microsteps/full step (3200/revolution), conservative run current setting
48 (~0.654 A RMS), hold current 16 (~0.280 A RMS), slow internal velocity 200.
MST stops motion but does NOT remove holding current.
No EEPROM writes; configuration can still remain in RAM after this script.
Close TMCL-IDE and stop any standalone TMCL application before using this.
No automatic retry after communication failures (a move might have executed).
Software stop cannot guarantee stopping when USB or power communication fails.

WIRING (pin numbering: Hardware Manual Figure 3.2, not left/right guesses):
Power: 1 GND -> supply negative; 2 VDRIVER -> +24V DC;
3 VDIGITAL -> same +24V, or leave open (onboard diode supplies logic).
Motor connector 0: 1 black OA1; 2 green OA2; 3 red OB1; 4 blue OB2.
Encoder connector 0: 1 GND -> encoder G; 2 +5V -> encoder V;
3 A+ -> A+; 4 A- -> A-; 5 B+ -> B+; 6 B- -> B-;
7 N+ -> Z+; 8 N- -> Z-. Shield E is not a ninth controller pin:
terminate at chassis/cable shield according to the installation EMC design.
Use encoder differential termination jumpers per Hardware Manual Figure 3.4.
Disconnect external power AND USB before changing wiring.

INFORMATION SOURCES:
https://www.analog.com/media/en/technical-documentation/user-guides/TMCM-3110_hardware_manual_hw1.10_rev1.04.pdf
https://www.analog.com/media/en/dsp-documentation/software-manuals/TMCM-3110-TMCL_firmware_manual_fw1.17_rev1.16.pdf
https://www.analog.com/media/en/technical-documentation/data-sheets/QSH4218-x-10k_datasheet_rev1.50.pdf
Firmware manual: protocol pp.10-12, commands pp.25-32,
axis parameters pp.110-119, units/encoder pp.126-129.
Motor rated phase current 1 A, full step 1.8 degrees.
Encoder 10000 P/R, quadrature 40000 counts/revolution.
--encoder sets decimal scaling 3200/40000*10000=800, no index reset.
Encoder sign must be checked; set AP201=33 instead of 32 if reversed.
AP209 is scaled encoder position; AP1 is the commanded step counter,
not measured physical position. AP8 indicates step-counter target reached,
not encoder verification or closed-loop servo operation.
"""
class TMCL_cmnds(enum.IntEnum):
    """Instruction bytes select commands; axis parameter numbers are separate."""
    ROR = 1       # Rotate right
    ROL = 2       # Rotate left
    MST = 3       # Motor stop
    MVP = 4       # Move to position
    SAP = 5       # Set axis parameter
    GAP = 6       # Get axis parameter
    STAP = 7      # Store axis parameter
    RSAP = 8      # Restore axis parameter
    SGP = 9       # Set global parameter (module specific settings e.g. communication settings or TMCL user variables)
    GGP = 10      # Get global parameter (module specific settings e.g. communication settings or TMCL user variables)
    STGP = 11     # Store global parameter (TMCL user variables only)
    RSGP = 12     # Restore global parameter (TMCL user variables only)


class TMCL_AXIS_parm(enum.IntEnum):
    """Axis parameters for the TMCL module."""
    MAX_POS_SPEED = 4  # Maximum position speed value for the motor phase
    MAX_ACC = 5  # Maximum acceleration value for the motor phase
    MAX_CURRENT = 6  # Maximum current value for the motor phase
    STANDBY_CURRENT = 7  # Standby current value for the motor phase
    MICROSTEP_RESOLUTION = 140   # Microstep resolution (microsteps per full step) value
    RAMP_DIVISOR = 153   # Ramp divisor value
    PULSE_DIVISOR = 154   # Pulse divisor value
    ENC_MODE = 201   # Encoder mode
    ENC_POS = 209   # Encoder counter value
    ENC_PRESCALER = 210   # Encoder prescaler value

class TMCL:
    """Serial connection to one board, with validated replies and no motion retries.

    Command wrappers return the reply's integer value. An acknowledgement means
    the command was accepted, not that the motor has reached its destination.
    """

    # Open the serial connection and prepare a lock for complete request/reply exchanges.
    def __init__(self, port: str, address: int=1, host: int=2, timeout: float=2.0) -> None:
        self.address: int
        self.host: int
        self.timeout: float
        self.address, self.host, self.timeout = address, host, timeout  # Store TMCL module address, host address, and communication timeout
        self.lock: LockType = threading.Lock()        # Lock for thread-safe communication with the TMCL module
        self.link: serial.Serial = serial.Serial(port, baudrate=9600, timeout=timeout,
                                  write_timeout=timeout)        # open serial port for communication with the TMCL module
        self.link.reset_input_buffer()      # Clear any existing data in the input buffer to start fresh communication
        self.broken: bool = False                  # Flag indicating if the communication link is broken

    # Close the serial connection and prevent subsequent commands.
    def close(self) -> None:
        """Close the serial connection and prevent subsequent commands."""
        self.link.close()
        self.broken: bool = True  # Mark the communication link as broken after closing

    # Send one packet and return the signed int32 value from its valid reply.
    def command(self, instruction: int, kind: int=0, axis: int=0, value: int=0) -> int:
        """Send one packet and return the signed int32 value from its valid reply.

        kind selects a parameter or command mode. axis selects a motor output,
        except for global commands, where this field selects a parameter bank.
        A lost reply may hide an executed move, so communication errors are
        never followed by an automatic command retry.
        """
        with self.lock:
            if self.broken:
                raise RuntimeError("Transport desynchronized: reconnect and inspect state")
            payload: bytes = struct.pack(">BBBBi", self.address, instruction, kind, axis, value)
            # The first four fields use one byte each; value uses four bytes.
            # Append the low byte of their sum as the ninth, checksum byte.
            packet: bytes = payload + bytes([sum(payload) & 255])
            # Send the constructed packet to the TMCL module and handle the reply
            try:
                if self.link.write(packet) != 9:
                    raise IOError("Incomplete write")
                reply: bytearray = bytearray()
                deadline: float = time.monotonic() + self.timeout  # Calculate the deadline for the reply based on the timeout

                # Read the reply from the TMCL module until we have 9 bytes or the deadline is reached
                while len(reply) < 9 and time.monotonic() < deadline:
                    reply.extend(self.link.read(9 - len(reply)))
                    # If no data is available, sleep briefly to avoid busy-waiting
                    if not reply:
                        time.sleep(0.01)
                # Check if the reply is complete within the timeout period
                if len(reply) != 9:
                    raise TimeoutError(f"Reply incomplete: {len(reply)}/9 bytes")

                # Verify the checksum of the reply packet before processing it further
                if sum(reply[:8]) & 255 != reply[8]:
                    raise IOError("Reply checksum mismatch")
                echoed: int
                host: int
                module: int
                result: int
                status: int
                host, module, status, echoed, result = struct.unpack(">BBBBi", reply[:8])

                # Check if the reply corresponds to the expected host, module, and instruction
                if (host, module, echoed) != (self.host, self.address, instruction):
                    raise IOError(
                      f"Unexpected reply: {reply.hex(' ')}; "
                      f"host={host}, module={module}, command={echoed}; "
                      f"expected host={self.host}, module={self.address}, "
                      f"command={instruction}"
    )
            except Exception:
                # Block later commands: a delayed reply could be assigned to the wrong request.
                self.broken: bool = True
                raise

            # A valid rejection reply does not desynchronize the serial stream.
            if status != 100:
                raise RuntimeError(f"TMCL rejected command {instruction}: status {status}")
            return result

    # Read a parameter from the specified axis
    def get(self, parameter: int, axis: int=0) -> int:
        """Return an axis parameter from the specified motor output."""
        return self.command(TMCL_cmnds.GAP, parameter, axis)

    # Read a global parameter from the specified bank
    def get_global(self, parameter: int, bank: int=0) -> int:
        """Read a global parameter; bank 2 holds TMCL user variables."""
        return self.command(TMCL_cmnds.GGP, parameter, bank)

    # Set a parameter for the specified axis
    def set(self, parameter: int, value: int, axis: int=0) -> int:
        """Set an axis parameter in RAM and return the command reply value."""
        return self.command(TMCL_cmnds.SAP, parameter, axis, value)

    # Stop the specified axis
    def stop(self, axis: int=0) -> int:
        """Request a soft stop; holding current remains enabled."""
        return self.command(TMCL_cmnds.MST, axis=axis)

    # Move the specified axis by a relative number of microsteps
    def move_relative(self, microsteps: int, axis: int=0) -> int:
        """Start an offset move; wait_position() checks controller completion."""
        return self.command(TMCL_cmnds.MVP, 1, axis, microsteps)

    # Move the specified axis to an absolute position
    def move_absolute(self, microsteps: int, axis: int=0) -> int:
        """Absolute position relative to the controller's current origin."""
        return self.command(TMCL_cmnds.MVP, 0, axis, microsteps)

    # Rotate the specified axis at the given velocity
    def rotate(self, velocity: int, axis: int=0) -> int:
        """Signed velocity in INTERNAL units, not RPM. FYI: max is 2047."""
        if not -2047 <= velocity <= 2047:
            raise ValueError("Velocity must be -2047..2047")

        # Choose the correct command based on the sign of the velocity
        return self.command(TMCL_cmnds.ROR if velocity >= 0 else TMCL_cmnds.ROL, 0, axis, abs(velocity))

    # Get the current position of the specified axis
    def position(self, axis: int=0) -> int:
        """Return the commanded step counter, not a measured physical position."""
        return self.get(1, axis)

    # Get the current encoder position of the specified axis
    def encoder_position(self, axis: int=0) -> int:
        """Return the encoder counter using the axis's existing scaling."""
        return self.get(TMCL_AXIS_parm.ENC_POS, axis)

    # Wait until the specified axis reaches its target position or timeout occurs
    def wait_position(self, timeout: float=20, axis: int=0) -> None:
        """Wait for target reached and zero velocity; request a stop on timeout.

        Completion is based on controller counters, not encoder agreement.
        """
        deadline: float = time.monotonic() + timeout  # Calculate the time at which the wait should timeout

        while time.monotonic() < deadline:
            if self.get(8, axis) and self.get(3, axis) == 0:
                return
            time.sleep(0.05)
        self.stop(axis)
        raise TimeoutError("Target not reached; stop requested")

    # Configure the bench for the specified axis, optionally enabling the encoder
    def configure_bench(self, axis: int=0, encoder: bool=False) -> None:
        """Free-shaft test; does not alter limit-switch settings."""
        if self.get(TMCL_cmnds.MST, axis) != 0:
            raise RuntimeError("Axis already moving")
        # Hold current first; then conservative run current.
        parameter: int
        value: int
        for parameter, value in [(TMCL_AXIS_parm.STANDBY_CURRENT, 16), (TMCL_AXIS_parm.MAX_CURRENT, 48), (TMCL_AXIS_parm.MICROSTEP_RESOLUTION, 4),
                                 (TMCL_AXIS_parm.PULSE_DIVISOR, 7), (TMCL_AXIS_parm.RAMP_DIVISOR, 7), (TMCL_AXIS_parm.MAX_ACC, 100),
                                 (TMCL_AXIS_parm.MAX_POS_SPEED, 200)]:
            self.set(parameter, value, axis)

        # Configure encoder if requested
        if encoder:
            self.set(TMCL_AXIS_parm.ENC_MODE, 32, axis)  # decimal scaling; no index clear
            self.set(TMCL_AXIS_parm.ENC_PRESCALER, 800, axis)

# Command-line bench interface; offline tests live in unitests/.
"""TMCM-3110 / TMCL USB example, Python 3.10+; requires pyserial.

Commands:
  python -m pip install pyserial
  python -m src.bs3ADTritanic --list
  python -m src.bs3ADTritanic --port COM3
  python -m src.bs3ADTritanic --port COM3 --move 800
  python -m src.bs3ADTritanic --port COM3 --move -800 --encoder

"""


# Run discovery, read-only diagnostics, or the explicitly requested bench move.
def main() -> None:
    """Run discovery, read-only diagnostics, or the explicitly requested bench move."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--port")
    parser.add_argument("--address", type=int, default=1)
    parser.add_argument("--host", type=int, default=2)
    parser.add_argument("--move", type=int, help="Relative microsteps, enables configuration")
    parser.add_argument("--encoder", action="store_true", help="Configure encoder scaling with move")
    args: argparse.Namespace = parser.parse_args()
    if args.list:
      port: ListPortInfo
      for port in sorted(list_ports.comports()):
        if (port.vid, port.pid) == (0x2A3C, 0x0100):
          print(port.device, port.description)
      return
    if not args.port:
        parser.error("--port is required, or use --list")
    if args.encoder and args.move is None:
        parser.error("--encoder requires --move")
    if not 1 <= args.address <= 255 or not 0 <= args.host <= 255:
        parser.error("Invalid address")
    if args.move is not None and not -3200 <= args.move <= 3200:
        parser.error("Bench CLI limits motion to one revolution")
    controller: TMCL = TMCL(args.port, args.address, args.host)
    attempted_motion: bool = False
    try:
        print("Commanded position:", controller.position())
        print("Encoder position (existing scaling):", controller.encoder_position())
        print("Actual velocity (internal units):", controller.get(3))
        print("TMCL user variable #0 (bank 2):", controller.get_global(parameter=69, bank=0))
        if args.move is not None:
            controller.configure_bench(encoder=args.encoder)
            before: int | None = controller.encoder_position() if args.encoder else None
            attempted_motion = True
            controller.move_relative(args.move)
            controller.wait_position()
            time.sleep(0.3)
            print("Commanded position:", controller.position())
            if before is not None:
                print("Encoder delta:", controller.encoder_position() - before)
    finally:
        if attempted_motion:
            try:
                controller.stop()
            except Exception as exc:
                print("STOP could not be confirmed:", exc)
        controller.close()


if __name__ == "__main__":
  main()
