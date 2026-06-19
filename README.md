# Kinetic Runner

The local client for [Kinetic](https://tracekinetic.com) — captures raw mouse input on your machine, normalizes it, and sends it to your Kinetic account for analysis.

This repository is public so anyone can verify exactly what the downloadable installer does before running it on their machine.

## What this does

- Captures raw mouse movement ("mickeys") during a recording session you start manually
- Normalizes the data locally
- Uploads the session to your Kinetic account when you stop recording
- Includes a calibration tool to measure your mouse's sensitivity accurately

## What this does NOT do

- No background tracking outside of an active, user-started session
- No keystroke logging
- No access to files, clipboard, or other applications
- No data collection beyond mouse movement during recording

## How it works

The runner is a lightweight Python application, packaged into a standalone Windows executable with [PyInstaller](https://pyinstaller.org/). The build is fully reproducible from this source using the included `.spec` file.

The installer is built with [Inno Setup](https://jrsoftware.org/isinfo.php) using `PositionAnalyzerInstaller.iss`, included in this repo — you can read exactly what it installs and where.

## Files

| File | Purpose |
|---|---|
| `run_web_gui.py` | Main runner application — recording, session upload, login |
| `calibrate_gui.py` | Desktop calibration tool |
| `calibrate_web.py` | Browser-based calibration flow |
| `stats.py` | Local stats helpers |
| `PositionAnalyzer.spec` | PyInstaller build specification |
| `PositionAnalyzerInstaller.iss` | Inno Setup installer script |
| `build_runner.ps1` | Build script for the executable |
| `build_installer.ps1` | Build script for the installer |

## License

MIT — see [LICENSE](LICENSE).

## Questions or concerns

If you have a question about what this software does, reach out via my email cbb430@gmail.com or open an issue on this repo.
