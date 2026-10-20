# Platform setup

Run from the project directory in Windows PowerShell or cmd. If the local
environment is already installed, only the last command is needed:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.venv\Scripts\python.exe platform_gui.py
```

The GUI uses PySide6 / Qt Quick QML. Select a Trinamic USB candidate, set the
connected motor count manually (2 or 3), and assign X/Y[/Z] to outputs 0/1/2.
Selecting an output already used by another axis swaps their assignments.
Two motors can use any pair of outputs, such as 0 and 2. In two-motor mode,
only X and Y are shown.

**Save settings** writes `platform_settings.json` next to the script. Settings
are loaded on the next launch. Check assignments after changing motor cables.
The setup screen does not open COM ports, move motors, or change controller
parameters. Motion controls are not included in this screen yet.

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

Run all checks without hardware communication:

```powershell
.venv\Scripts\python.exe -B -m unittest test_platform_config test_motor_platform test_platform_gui -v
```

The GUI test uses fake device discovery and offscreen rendering. It saves a
preview to `gui_preview.png` and does not modify the user's configuration.
