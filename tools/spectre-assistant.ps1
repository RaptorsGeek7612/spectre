# Start Spectre in the background (no console to close by accident) and open its interface.
# Used by tools\spectre-assistant.cmd; extra arguments are passed to `python -m spectre.assistant`.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $env:USERPROFILE ".spectre\assistant\spectre.log"
$url = "http://127.0.0.1:8765/assistant.html"

function Test-Spectre {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:8765/api/status" | Out-Null; return $true }
    catch { return $false }
}

# --silent: started with the Windows session (shortcut in the Startup folder): no page opened.
$silent = $args -contains "--silent"
$args = @($args | Where-Object { $_ -ne "--silent" })

# The launcher (tools\spectre_launcher.py) stays on even when Spectre is closed, so the phone can
# start Spectre again from https://<pc>/lanceur/. Tiny: standard library only.
function Test-Launcher {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:8764/status" | Out-Null; return $true }
    catch { return $false }
}

# Asked to start: Spectre is no longer "stopped on purpose" (the launcher's watchdog may
# restart it again if it stops on its own).
Remove-Item (Join-Path $env:USERPROFILE ".spectre\assistant\stopped") -ErrorAction SilentlyContinue

if (-not $env:SPECTRE_WEBUI_PASSWORD) {
    $env:SPECTRE_WEBUI_PASSWORD = [Environment]::GetEnvironmentVariable("SPECTRE_WEBUI_PASSWORD", "User")
}
if ($env:SPECTRE_WEBUI_PASSWORD -and -not (Test-Launcher)) {
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "uv run --no-sync python tools\spectre_launcher.py" `
        -WorkingDirectory $repo -WindowStyle Hidden
}

# One start at a time: the shortcut, the Startup folder and the phone's launcher may overlap,
# and two Spectre instances fight over the microphone and the camera.
$mutex = New-Object System.Threading.Mutex($false, "Local\SpectreStart")
if (-not $mutex.WaitOne(0)) {
    if (-not $silent) {
        for ($i = 0; $i -lt 90 -and -not (Test-Spectre); $i++) { Start-Sleep -Milliseconds 500 }
        if (Test-Spectre) { Start-Process $url }
    }
    exit 0
}

# Already running, or still loading (its page may not answer yet while the voice loads).
$alive = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*spectre.assistant*" }
if ((Test-Spectre) -or $alive) {
    for ($i = 0; $i -lt 90 -and -not (Test-Spectre); $i++) { Start-Sleep -Milliseconds 500 }
    if (-not $silent -and (Test-Spectre)) { Start-Process $url }  # just show it
    exit 0
}

# The Intel Fortran runtime shipped with the speech libraries aborts the process on console
# events; disable its handler so Python decides how to shut down.
$env:FOR_DISABLE_CONSOLE_CTRL_HANDLER = "1"
$extra = ($args | ForEach-Object { "`"$_`"" }) -join " "

# Access from the phone, anywhere: when Tailscale is installed and a password is set
# (tools\spectre-password.cmd), publish Spectre on the private tailnet over HTTPS with
# `tailscale serve` (nothing is opened to the Internet) and accept its host name.
$tailscale = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $tailscale -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) {
    $tailscale = "$env:ProgramFiles\Tailscale\tailscale.exe"  # PATH not refreshed yet
}
if ($tailscale -and $env:SPECTRE_WEBUI_PASSWORD) {
    if ($silent) {  # at sign-in Tailscale may still be connecting: give it up to 90 s
        for ($i = 0; $i -lt 45; $i++) {
            try { if ((& $tailscale status --json | ConvertFrom-Json).BackendState -eq "Running") { break } } catch { }
            Start-Sleep -Seconds 2
        }
    }
    try {
        $name = ((& $tailscale status --json | ConvertFrom-Json).Self.DNSName).TrimEnd(".")
        # `serve` waits forever while HTTPS/Serve is not enabled on the tailnet: give it 10 s.
        $serve = Start-Process -FilePath $tailscale -ArgumentList "serve", "--bg", "http://127.0.0.1:8765" `
            -WindowStyle Hidden -PassThru
        if (-not $serve.WaitForExit(10000)) { $serve.Kill() }
        elseif ($name -and $serve.ExitCode -eq 0) { $extra = "--allow-host $name $extra" }
        # and the launcher under /lanceur, so the phone can start Spectre when it is closed
        $lanceur = Start-Process -FilePath $tailscale -WindowStyle Hidden -PassThru `
            -ArgumentList "serve", "--bg", "--set-path", "/lanceur", "http://127.0.0.1:8764"
        if (-not $lanceur.WaitForExit(10000)) { $lanceur.Kill() }
    } catch { }  # Tailscale stopped or logged out: Spectre stays local
}
# The last line notes how Spectre ended (!errorlevel! is read after it exits, thanks to /v:on):
# if it ever vanishes, the log then shows its exit code, or nothing if it was killed.
$command = "uv run python -m spectre.assistant --voice --camera --no-browser $extra >> `"$log`" 2>&1" +
    " & echo [!date! !time!] Spectre s'est arrete (code de sortie !errorlevel!) >> `"$log`""
Start-Process -FilePath "cmd.exe" -ArgumentList "/v:on", "/c", $command -WorkingDirectory $repo -WindowStyle Hidden

$tries = if ($silent) { 240 } else { 60 }  # slower at sign-in, while Windows starts everything
for ($i = 0; $i -lt $tries -and -not (Test-Spectre); $i++) { Start-Sleep -Milliseconds 500 }
if (Test-Spectre) {
    if (-not $silent) { Start-Process $url }
} else {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Spectre n'a pas démarré. Journal : $log", "Spectre") | Out-Null
}
