<#
.SYNOPSIS
    Prove that a scheduled task can wake this laptop from sleep. Two steps.

.DESCRIPTION
    Run from an ELEVATED PowerShell prompt, with the laptop PLUGGED IN.

    Step 1 - arm:
        powershell -ExecutionPolicy Bypass -File scripts\test_wake.ps1
      then put the laptop to SLEEP straight away (Start > Power > Sleep)
      and leave it untouched for 10 minutes.

    Step 2 - check, after you wake it:
        powershell -ExecutionPolicy Bypass -File scripts\test_wake.ps1 -Check

    Step 1 registers a throwaway task, artha-waketest, with the same
    principal (S4U) and WakeToRun setting the real tasks use, due in
    -Minutes minutes. Its action writes a start stamp, stays busy for four
    minutes, then writes an end stamp. Step 2 reads the stamps and the wake
    sources Windows logged, prints one verdict, and deletes the task.

    The verdicts separate the ways this fails:
      never ran     -> wake timers still blocked (power plan, or BIOS)
      no wake event -> it ran on time, but the machine was never asleep
      no/late end   -> it woke, then fell back asleep partway through
    The last one matters because the real daily cycle runs for minutes, and
    a woken laptop with no user input goes back to sleep on its own.

    StartWhenAvailable is deliberately OFF here: a missed wake must show up
    as "never ran", not quietly run later when you open the lid.
#>
param(
    [switch]$Check,
    [int]$Minutes = 3
)

$ErrorActionPreference = "Stop"
$name = "artha-waketest"
$log = Join-Path $env:LOCALAPPDATA "artha_waketest.log"
$busySeconds = 240

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "NOT ELEVATED - right-click PowerShell > Run as administrator." -ForegroundColor Red
    exit 1
}

if (-not $Check) {
    Remove-Item $log -ErrorAction SilentlyContinue
    $due = (Get-Date).AddMinutes($Minutes)
    $cmd = "Add-Content -Path '$log' -Value ('start ' + (Get-Date -Format o)); " +
           "Start-Sleep -Seconds $busySeconds; " +
           "Add-Content -Path '$log' -Value ('end ' + (Get-Date -Format o))"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -Command `"$cmd`""
    $trigger = New-ScheduledTaskTrigger -Once -At $due
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null

    Write-Host ("Armed {0}, due at {1:HH:mm:ss}." -f $name, $due) -ForegroundColor Cyan
    Write-Host ""
    powercfg /waketimers
    Write-Host ""
    Write-Host "NOW: Start > Power > Sleep. Plugged in, lid can stay open, do not touch it for 10 minutes."
    Write-Host "Then wake it and run:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\test_wake.ps1 -Check"
    exit 0
}

$task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No $name task found - run step 1 first." -ForegroundColor Yellow
    exit 1
}
$due = [datetime]$task.Triggers[0].StartBoundary
$info = Get-ScheduledTaskInfo -TaskName $name
$lines = @(if (Test-Path $log) { Get-Content $log })
$start = $lines | Where-Object { $_ -like "start *" } |
    ForEach-Object { [datetime]$_.Substring(6) } | Select-Object -First 1
$end = $lines | Where-Object { $_ -like "end *" } |
    ForEach-Object { [datetime]$_.Substring(4) } | Select-Object -First 1

$wakes = @(Get-WinEvent -ErrorAction SilentlyContinue -FilterHashtable @{
        LogName      = "System"
        ProviderName = "Microsoft-Windows-Power-Troubleshooter"
        Id           = 1
        StartTime    = $due.AddMinutes(-5)
    } | Sort-Object TimeCreated)

Write-Host ("due        {0:HH:mm:ss}" -f $due)
Write-Host ("started    {0}" -f $(if ($start) { $start.ToString("HH:mm:ss") } else { "never" }))
Write-Host ("finished   {0}" -f $(if ($end) { $end.ToString("HH:mm:ss") } else { "never" }))
Write-Host ("last result 0x{0:X}" -f $info.LastTaskResult)
Write-Host "wake events since arming:"
if ($wakes.Count -eq 0) { Write-Host "  (none)" }
foreach ($w in $wakes) {
    $src = ($w.Message -split "`r?`n" | Where-Object { $_ -match "Wake Source" }) -join " "
    Write-Host ("  {0:HH:mm:ss}  {1}" -f $w.TimeCreated, $src.Trim())
}
Write-Host ""

$woke = @($wakes | Where-Object { $_.TimeCreated -le $due.AddMinutes(2) -and $_.TimeCreated -ge $due.AddMinutes(-2) })
$pass = $false
if (-not $start) {
    Write-Host "FAIL - the task never ran: the wake timer did not fire." -ForegroundColor Red
    Write-Host "  Check Power Options > Change advanced power settings > Sleep > Allow wake timers"
    Write-Host "  = Enable (Plugged in), that you used Sleep (not Shut down / Hibernate), and that"
    Write-Host "  the charger was connected. If all three hold, wake timers are off in the BIOS."
} elseif ($woke.Count -eq 0) {
    Write-Host "INCONCLUSIVE - it ran on time, but Windows logged no wake near the due time." -ForegroundColor Yellow
    Write-Host "  The machine was most likely awake the whole time. Re-arm and Sleep immediately."
} elseif (-not $end -or ($end - $start).TotalSeconds -gt $busySeconds + 90) {
    Write-Host "PARTIAL - it woke on time, then went back to sleep before the run finished." -ForegroundColor Yellow
    Write-Host ("  A {0}s job took {1}. The daily cycle must hold the machine awake while it runs." -f `
        $busySeconds, $(if ($end) { "{0:N0}s" -f ($end - $start).TotalSeconds } else { "forever (no end stamp)" }))
} else {
    Write-Host "PASS - the laptop woke itself on time and stayed awake for the whole run." -ForegroundColor Green
    $pass = $true
}

Unregister-ScheduledTask -TaskName $name -Confirm:$false
Remove-Item $log -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Test task removed."
if ($pass) { exit 0 } else { exit 1 }
