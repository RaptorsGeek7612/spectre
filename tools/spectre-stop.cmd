@echo off
rem Stop the Spectre assistant started by tools\spectre-assistant.cmd.
rem The "stopped" mark tells the launcher's watchdog not to restart it: it was stopped on purpose.
if not exist "%USERPROFILE%\.spectre\assistant" mkdir "%USERPROFILE%\.spectre\assistant"
echo %date% %time%> "%USERPROFILE%\.spectre\assistant\stopped"
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*spectre.assistant*' -and $_.Name -ne 'powershell.exe' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host 'Spectre est arrete.' } else { Write-Host 'Spectre ne tournait pas.' }; Start-Sleep 2"
