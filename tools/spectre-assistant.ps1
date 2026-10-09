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

if (Test-Spectre) {
    Start-Process $url  # already running: just show it
    exit 0
}

# The Intel Fortran runtime shipped with the speech libraries aborts the process on console
# events; disable its handler so Python decides how to shut down.
$env:FOR_DISABLE_CONSOLE_CTRL_HANDLER = "1"
$extra = ($args | ForEach-Object { "`"$_`"" }) -join " "

# Access from the phone, anywhere: when Tailscale is installed and a password is set
# (tools\spectre-password.cmd), publish Spectre on the private tailnet over HTTPS with
# `tailscale serve` (nothing is opened to the Internet) and accept its host name.
if (-not $env:SPECTRE_WEBUI_PASSWORD) {
    $env:SPECTRE_WEBUI_PASSWORD = [Environment]::GetEnvironmentVariable("SPECTRE_WEBUI_PASSWORD", "User")
}
$tailscale = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $tailscale -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) {
    $tailscale = "$env:ProgramFiles\Tailscale\tailscale.exe"  # PATH not refreshed yet
}
if ($tailscale -and $env:SPECTRE_WEBUI_PASSWORD) {
    try {
        $name = ((& $tailscale status --json | ConvertFrom-Json).Self.DNSName).TrimEnd(".")
        # `serve` waits forever while HTTPS/Serve is not enabled on the tailnet: give it 10 s.
        $serve = Start-Process -FilePath $tailscale -ArgumentList "serve", "--bg", "http://127.0.0.1:8765" `
            -WindowStyle Hidden -PassThru
        if (-not $serve.WaitForExit(10000)) { $serve.Kill() }
        elseif ($name -and $serve.ExitCode -eq 0) { $extra = "--allow-host $name $extra" }
    } catch { }  # Tailscale stopped or logged out: Spectre stays local
}
$command = "uv run python -m spectre.assistant --voice --camera --no-browser $extra >> `"$log`" 2>&1"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $command -WorkingDirectory $repo -WindowStyle Hidden

for ($i = 0; $i -lt 60 -and -not (Test-Spectre); $i++) { Start-Sleep -Milliseconds 500 }
if (Test-Spectre) {
    Start-Process $url
} else {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Spectre n'a pas démarré. Journal : $log", "Spectre") | Out-Null
}
