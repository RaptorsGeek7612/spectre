@echo off
rem Start the Spectre assistant (voice + camera) in the background, without a console window that
rem could be closed by accident, then open its interface. Double-click, or: tools\spectre-assistant.cmd
rem Log: %USERPROFILE%\.spectre\assistant\spectre.log   Stop: tools\spectre-stop.cmd
cd /d "%~dp0.."
if not exist "%USERPROFILE%\.spectre\assistant" mkdir "%USERPROFILE%\.spectre\assistant"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0spectre-assistant.ps1" %*
