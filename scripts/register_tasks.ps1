<#
.SYNOPSIS
    Register (or repair) every Artha scheduled task. Idempotent.

.DESCRIPTION
    Run from an ELEVATED PowerShell prompt (right-click > Run as administrator):

        powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1

    Then prove the machine really wakes itself:

        powershell -ExecutionPolicy Bypass -File scripts\test_wake.ps1

    WHY THIS SCRIPT EXISTS (2026-07-22): the tasks were originally created
    with `schtasks /TR "<quoted path>"`. The shell stripped the quotes, so
    Windows stored a repo path containing spaces as
        Execute   = C:\Users\vivaa\OneDrive\Desktop\Personal
        Arguments = Projects\Quant\artha\scripts\artha_daily.cmd
    and every run failed with 0x80070002 (file not found). The failure was
    silent for three days — the tasks showed "Ready", they simply never
    did anything — until the heartbeat's staleness alarm caught it.

    The fix is structural: invoke cmd.exe with the wrapper as a quoted
    ARGUMENT, so no path is ever parsed as an executable, and set an
    explicit working directory.

    It also sets the power/availability options that matter on a laptop:
      StartWhenAvailable      - run a missed task as soon as possible
      AllowStartIfOnBatteries - do not skip the run on battery
      DontStopIfGoingOnBatteries
      WakeToRun               - wake a SLEEPING machine for the run
    Without these, unplugging or sleeping the machine silently stops the
    B1 clock.

    WAKETORUN IS ONLY HALF OF WAKING (2026-09-11). Windows ignores a task's
    wake timer unless the power plan's "Allow wake timers" is Enable. This
    machine shipped with "Important wake timers only" on AC, which Task
    Scheduler timers do not qualify for: the flag would have read True and
    woken nothing. So this script also sets Allow wake timers = Enable on AC
    for the active plan. Battery (DC) is deliberately left alone — a laptop
    that wakes itself inside a bag drains and overheats — so keep it plugged
    in at 19:00. Wake works from Sleep (S3), never from Shut down, and not
    reliably from Hibernate.

    ELEVATION IS REQUIRED (2026-09-11). Unelevated, this script used to fall
    back to an Interactive principal and still print OK. Interactive tasks
    die with 0xC000013A when the desktop session is torn down, which cost
    the restarted B1 clock both 2026-09-09 and 2026-09-11. It now refuses to
    run unelevated rather than produce that configuration.
#>

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "NOT ELEVATED - nothing was changed." -ForegroundColor Red
    Write-Host "Right-click PowerShell > Run as administrator, then run this again."
    Write-Host "(Unelevated, only Interactive tasks can be registered, and those die with 0xC000013A.)"
    exit 1
}

$repo = Split-Path -Parent $PSScriptRoot
$scripts = Join-Path $repo "scripts"

$tasks = @(
    @{ Name = "artha-daily";     Wrapper = "artha_daily.cmd";     Trigger = "daily";     Time = "19:00" },
    @{ Name = "artha-heartbeat"; Wrapper = "artha_heartbeat.cmd"; Trigger = "daily";     Time = "21:00" },
    @{ Name = "artha-weekly";    Wrapper = "artha_weekly.cmd";    Trigger = "weekly";    Time = "10:00" },
    @{ Name = "artha-monthly";   Wrapper = "artha_monthly.cmd";   Trigger = "monthly";   Time = "10:00" },
    @{ Name = "artha-quarterly"; Wrapper = "artha_quarterly.cmd"; Trigger = "quarterly"; Time = "10:00" }
)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

# S4U = "run whether the user is logged on or not", without storing a password.
# An Interactive-logon task is bound to the desktop session, so a long cycle dies
# with 0xC000013A when that session is torn down. The daily cycle needs no
# desktop — it writes files and calls the network.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

foreach ($t in $tasks) {
    $wrapper = Join-Path $scripts $t.Wrapper
    if (-not (Test-Path $wrapper)) { throw "missing wrapper: $wrapper" }

    # cmd.exe is the executable; the space-containing path is a quoted ARGUMENT.
    $action = New-ScheduledTaskAction -Execute "cmd.exe" `
        -Argument ('/c "' + $wrapper + '"') -WorkingDirectory $repo

    $trigger = switch ($t.Trigger) {
        "daily"     { New-ScheduledTaskTrigger -Daily -At $t.Time }
        "weekly"    { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $t.Time }
        "monthly"   { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -WeeksInterval 4 -At $t.Time }
        "quarterly" { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -WeeksInterval 12 -At $t.Time }
    }

    # -Force overwrites in place. Never Unregister-then-Register: if the second
    # half fails the task is left DELETED, not merely stale.
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description "Artha $($t.Name) - see docs/RUNBOOK.md" | Out-Null

    # read back what Windows STORED, not what we asked for — "Ready" has lied before
    $stored = Get-ScheduledTask -TaskName $t.Name
    Write-Host ("{0,-18} OK  logon={1}  wake={2}  execute={3}" -f $t.Name,
        $stored.Principal.LogonType, $stored.Settings.WakeToRun, $stored.Actions[0].Execute)
}

# Allow wake timers: power sub-group SLEEP, setting RTCWAKE.
# 0 = Disable, 1 = Enable, 2 = Important wake timers only.
$sleepGroup = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
$rtcWake = "bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d"
powercfg /setacvalueindex SCHEME_CURRENT $sleepGroup $rtcWake 1
if ($LASTEXITCODE -ne 0) { throw "powercfg could not enable wake timers (exit $LASTEXITCODE)" }
powercfg /setactive SCHEME_CURRENT
if ($LASTEXITCODE -ne 0) { throw "powercfg could not re-apply the active plan (exit $LASTEXITCODE)" }
$ac = (powercfg /q SCHEME_CURRENT $sleepGroup $rtcWake |
    Select-String "Current AC Power Setting Index") -replace ".*:\s*", ""

Write-Host ""
Write-Host ("Allow wake timers, plugged in: {0}   (0x00000001 = Enable; battery left off on purpose)" -f $ac)
Write-Host ""
Write-Host "Armed wake timers (expect a Task Scheduler entry naming an artha task):"
powercfg /waketimers
Write-Host ""
Write-Host "Next, prove the machine really wakes itself:"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\test_wake.ps1"
