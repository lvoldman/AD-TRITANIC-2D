__author__ = "Leonid Voldman"
__copyright__ = "Copyright 2024"
__credits__ = ["VoldmanTech"]
__license__ = "SLA"
__version__ = "1.0.0"
__maintainer__ = "Leonid Voldman"
__email__ = "vleonid@voldman.com"
__status__ = "Tool"


import enum
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
    # Define TMCL command codes here, for example:
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
    ENC_POS = 209   # Encoder counter value


class TMCL:
    def __init__(self, port, address=1, host=2, timeout=2.0):
        self.address, self.host, self.timeout = address, host, timeout
        self.lock = threading.Lock()
        self.link = serial.Serial(port, baudrate=9600, timeout=timeout,
                                  write_timeout=timeout)
        self.link.reset_input_buffer()
        self.broken = False

    def close(self):
        self.link.close()
    def command(self, instruction, kind=0, axis=0, value=0):
        """One nine-byte request and reply; signed int32, big endian."""
        with self.lock:
            if self.broken:
                raise RuntimeError("Transport desynchronized: reconnect and inspect state")
            payload = struct.pack(">BBBBi", self.address, instruction, kind, axis, value)
            packet = payload + bytes([sum(payload) & 255])
            try:
                if self.link.write(packet) != 9:
                    raise IOError("Incomplete write")
                reply = bytearray()
                deadline = time.monotonic() + self.timeout
                while len(reply) < 9 and time.monotonic() < deadline:
                    reply.extend(self.link.read(9 - len(reply)))
                if len(reply) != 9:
                    raise TimeoutError(f"Reply incomplete: {len(reply)}/9 bytes")
                if sum(reply[:8]) & 255 != reply[8]:
                    raise IOError("Reply checksum mismatch")
                host, module, status, echoed, result = struct.unpack(">BBBBi", reply[:8])
                if (host, module, echoed) != (self.host, self.address, instruction):
                    # raise IOError("Unexpected reply address/command")
                    raise IOError(
                      f"Unexpected reply: {reply.hex(' ')}; "
                      f"host={host}, module={module}, command={echoed}; "
                      f"expected host={self.host}, module={self.address}, "
                      f"command={instruction}"
    )
            except Exception:
                self.broken = True
                raise
            if status != 100:
                raise RuntimeError(f"TMCL rejected command {instruction}: status {status}")
            return result

    def get(self, parameter, axis=0):
        return self.command(TMCL_cmnds.GAP, parameter, axis)

    def get_global(self, parameter, bank=0):
        """Read a global parameter; bank 2 holds TMCL user variables."""
        return self.command(TMCL_cmnds.GGP, parameter, bank)

    def set(self, parameter, value, axis=0):
        return self.command(TMCL_cmnds.SAP, parameter, axis, value)

    def stop(self, axis=0):
        return self.command(TMCL_cmnds.MST, axis=axis)

    def move_relative(self, microsteps, axis=0):
        return self.command(TMCL_cmnds.MVP, 1, axis, microsteps)

    def move_absolute(self, microsteps, axis=0):
        """Absolute position relative to the controller's current origin."""
        return self.command(TMCL_cmnds.MVP, 0, axis, microsteps)

    def rotate(self, velocity, axis=0):
        """Signed velocity in INTERNAL units, not RPM."""
        if not -2047 <= velocity <= 2047:
            raise ValueError("Velocity must be -2047..2047")
        return self.command(TMCL_cmnds.ROR if velocity >= 0 else TMCL_cmnds.ROL, 0, axis, abs(velocity))

    def position(self, axis=0):
        return self.get(1, axis)

    def encoder_position(self, axis=0):
        return self.get(TMCL_cmnds.ENC_POS, axis)

    def wait_position(self, timeout=20, axis=0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get(8, axis) and self.get(3, axis) == 0:
                return
            time.sleep(0.05)
        self.stop(axis)
        raise TimeoutError("Target not reached; stop requested")

    def configure_bench(self, axis=0, encoder=False):
        """Free-shaft test; does not alter limit-switch settings."""
        if self.get(3, axis) != 0:
            raise RuntimeError("Axis already moving")
        # Hold current first; then conservative run current.
        for parameter, value in [(7, 16), (6, 48), (140, 4),
                                 (154, 7), (153, 7), (5, 100), (4, 200)]:
            self.set(parameter, value, axis)
        if encoder:
            self.set(201, 32, axis)  # decimal scaling; no index clear
            self.set(210, 800, axis)

#------------------------- U N I T E S T ----------------------------
"""TMCM-3110 / TMCL USB example, Python 3.10+; requires pyserial.

Commands:
  python -m pip install pyserial
  python bs3ADTritanic.py --list
  python bs3ADTritanic.py --port COM5
  python bs3ADTritanic.py --port COM5 --move 800
  python bs3ADTritanic.py --port COM5 --move -800 --encoder

"""


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--port")
    parser.add_argument("--address", type=int, default=1)
    parser.add_argument("--host", type=int, default=2)
    parser.add_argument("--move", type=int, help="Relative microsteps, enables configuration")
    parser.add_argument("--encoder", action="store_true", help="Configure encoder scaling with move")
    args = parser.parse_args()
    if args.list:
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
    controller = TMCL(args.port, args.address, args.host)
    attempted_motion = False
    try:
        print("Commanded position:", controller.position())
        print("Encoder position (existing scaling):", controller.encoder_position())
        print("Actual velocity (internal units):", controller.get(3))
        print("TMCL user variable #0 (bank 2):", controller.get_global(parameter=69, bank=0))
        if args.move is not None:
            controller.configure_bench(encoder=args.encoder)
            before = controller.encoder_position() if args.encoder else None
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
