# Platform setup and motion control

Run from the project directory in Windows PowerShell or cmd. If the local
environment is already installed, only the last command is needed:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.venv\Scripts\python.exe -m src.platform_gui
```

The GUI uses PySide6 / Qt Quick QML. Select a Trinamic USB candidate, set the
connected motor count manually (2 or 3), and assign X/Y[/Z] to outputs 0/1/2.
Selecting an output already used by another axis swaps their assignments.
Two motors can use any pair of outputs, such as 0 and 2. In two-motor mode,
only X and Y are shown.

**Save settings** writes `platform_settings.json` in the project root. Settings
are loaded on the next launch. Check assignments after changing motor cables.
Startup and saving settings do not open COM ports or move motors. Select the
board and output mapping before pressing **Connect**. Mapping and board selection
are locked while connected; disconnect before changing them. Close TMCL-IDE and
stop standalone TMCL applications before connecting. The board address is 1.

## Motion controls

Each active axis has a **Dist** field, an **Absolute** checkbox and a
**Move single axis** button. Distances/targets are signed integer microsteps.
Unchecked means a relative offset from the current step counter; checked means
an absolute target relative to the controller's existing origin. Connecting does
not home or zero any axis. Distance fields start at zero and are not saved.

**Move single axis** sends an ordinary absolute MVP command to that output only.
**Move platform** includes all active rows, resolving each row's absolute or
relative mode into an absolute target, then using MVP COORD interpolation for
one coordinated start. Firmware interpolation on the installed FW1.14 still
requires hardware validation. Physical path accuracy depends on the mechanics
and axis scales; encoder readings are not used for automatic correction.

Speed and acceleration are AP4/AP5 internal units (1..2047), not mm/s or
microsteps/s. Defaults are 200 and 100. Both values remain changed in RAM after
motion. The timeout defaults to 20 seconds and can be adjusted before a move.
The single-axis CLI's one-revolution bench limit does not apply to GUI moves;
the GUI validates signed 32-bit target and distance ranges, not mechanical travel.

**Connect** preserves existing motor settings. If needed, explicitly press
**Apply tested motor settings** while idle. This applies the previously tested
bench settings to all mapped outputs: AP7=16, AP6=48, AP140=4, AP154=7, AP153=7,
AP5=100, AP4=200, AP201=32 and AP210=800. It changes holding current and encoder
scaling but does not issue a movement command or write EEPROM. These bench
settings have not been validated for the loaded platform.

During a move, competing actions are disabled. **STOP** requests a soft stop on
every mapped output and retains holding current. Its acknowledgement does not
guarantee physical standstill. USB/communication failure can prevent stopping;
errors are reported and require explicit reconnection, without retrying motion.
Closing the application attempts to stop active motion before closing the port.

Serial operations run in a separate Qt thread. Polling checks target counters
and zero velocity, then allows 0.3 seconds for settling. Step counters and scaled
encoder readings are displayed after completion. Their agreement is not verified
automatically. Software stop can wait for an in-flight serial exchange to finish.

VID:PID `2A3C:0100` identifies Trinamic candidates, but does not confirm their
model or firmware. For a board with the generic USB serial `TMCSTEP`, the USB
socket location is used to restore selection when the COM number changes.
This identifies the socket, not the physical board. Moving the USB cable may
require selecting the board again. Replacing a board in the same socket cannot
be detected automatically. Ambiguous matches are not selected automatically.
A unique USB serial number, when available, is preferred.

For future controller connections, rediscover devices and resolve the saved
identity using `resolve_board()`. Pass the current COM port to `TMCL`, then
construct `Platform(controller, axes=config['axes'])`. Do not use a saved COM
number without checking the device again. Loading settings never connects to
the controller or starts motion automatically.

Run all checks without hardware communication (fake controllers and USB metadata):

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s unitests -t . -v
```

The GUI test uses fake device discovery and offscreen rendering. It saves a
preview to `docs/gui_preview.png` and does not modify the user's configuration.
