# Tritanic motor platform

Python TMCL controller support for the TMCM-3110 and an XY/XYZ motion control GUI.

## Project layout

```text
src/                       Python source and QML
    bs3ADTritanic.py        TMCL serial transport and single-axis CLI
    motor_platform.py      XY/XYZ platform controller
    platform_config.py     USB discovery and configuration
    platform_types.py      Typed records and controller interfaces
    platform_gui.py        PySide6 application entry point
    motion_worker.py       Serial/motion worker running outside the GUI thread
    PlatformSetup.qml      Setup and motion interface
unitests/                  Offline tests (no motor hardware communication)
docs/                      Documentation and GUI preview
requirements-gui.txt       Python dependencies
platform_settings.json     Local configuration, created by the GUI (not tracked)
```

## Run the GUI

From the project root, using the installed local environment:

```powershell
.venv\Scripts\python.exe -m src.platform_gui
```

The GUI selects a board, assigns motor outputs and starts single-axis or
interpolated platform moves. Startup does not connect or move anything.
**Connect** opens a serial session; **Move** buttons operate physical hardware.
See [GUI guide](docs/GUI_README.md) for units, setup and device identification.

## Offline tests

```powershell
.venv\Scripts\python.exe -B -m unittest discover -s unitests -t . -v
```

## Single-axis CLI

The CLI now lives in `src`. Listing USB candidates does not open serial ports:

```powershell
.venv\Scripts\python.exe -m src.bs3ADTritanic --list
```

Passing `--port` communicates with the controller. Passing `--move` operates
physical hardware; run movement commands only when deliberately testing motion.
Python imports from the project root use `from src.bs3ADTritanic import TMCL`
and `from src.motor_platform import Platform`.
