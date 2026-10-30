@echo off
rem Bring the team's portraits to life for the video call (LivePortrait, see animate_portraits.py).
rem   tools\animate_portraits.cmd               every agent whose loops are missing
rem   tools\animate_portraits.cmd opus lexy     only these agents
rem   tools\animate_portraits.cmd --force       redo them all
set "PYTHONPATH=%USERPROFILE%\Apps\liveportrait\pkgs;%USERPROFILE%\ComfyUI\.venv\Lib\site-packages"
set "PY=%APPDATA%\uv\python\cpython-3.12-windows-x86_64-none\python.exe"
"%PY%" "%~dp0animate_portraits.py" %*
