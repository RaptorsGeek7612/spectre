@echo off
rem Stop the Spectre assistant started by tools\spectre-assistant.cmd.
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*spectre.assistant*' -and $_.Name -ne 'powershell.exe' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host 'Spectre est arrete.' } else { Write-Host 'Spectre ne tournait pas.' }; Start-Sleep 2"
