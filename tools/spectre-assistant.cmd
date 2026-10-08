@echo off
rem Lance l'assistant Spectre (voix + camera) dans sa propre fenetre.
rem Double-clic, ou : tools\spectre-assistant.cmd   (journal : %USERPROFILE%\.spectre\assistant\spectre.log)
title Spectre
cd /d "%~dp0.."
rem The Intel Fortran runtime shipped with the speech libraries aborts the whole process on any
rem console event (Ctrl+C, window close): let Python handle them and shut down cleanly instead.
set FOR_DISABLE_CONSOLE_CTRL_HANDLER=1
if not exist "%USERPROFILE%\.spectre\assistant" mkdir "%USERPROFILE%\.spectre\assistant"
echo Spectre demarre... Garde cette fenetre ouverte (journal : %USERPROFILE%\.spectre\assistant\spectre.log)
uv run python -m spectre.assistant --voice --camera %* >> "%USERPROFILE%\.spectre\assistant\spectre.log" 2>&1
echo.
echo Spectre s'est arrete. Dernieres lignes du journal :
powershell -NoProfile -Command "Get-Content -Tail 15 \"$env:USERPROFILE\.spectre\assistant\spectre.log\""
pause
