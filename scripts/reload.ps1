# 平滑重启：先走 stop.ps1（自己退出，到点才结束本目录的进程），确认没有接收进程，再 start.ps1 一次。
# 还有本目录的 agentbot 时不要再启动，避免两个接收进程。失败时把配置改回这次的备份。
# 不在这里扩大结束范围。结束进程仍只由原来的停止脚本做。
# 等待的预算按秒算（-StopWaitSec，默认 45）：每轮都要问一次进程表，机器快慢不同，按轮数等能差出好几倍。
param([string]$Config = "agents\example.json", [int]$StopWaitSec = 45)
$ErrorActionPreference = "Continue"
$base = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $PSScriptRoot "botproc.ps1")

function Get-ReceiverLeft([string]$Base) {
  # 返回第一个还留着的接收进程，没有则 $null。只取三列：整张 Win32_Process 表很慢，
  # 等待期间每一轮都要问一次。留下进程本身是因为拒绝启动时得说清是谁还占着。
  foreach ($p in @(Get-CimInstance Win32_Process -Property ProcessId,Name,CommandLine -ErrorAction SilentlyContinue)) {
    if (Test-OurAgent $p $Base) { return $p }
  }
  return $null
}

function Restore-SwitchBackup([string]$Base) {
  $job = Join-Path $Base "state\switch_job.json"
  if (-not (Test-Path -LiteralPath $job)) { return }
  try {
    $parsed = [IO.File]::ReadAllText($job) | ConvertFrom-Json
  } catch {
    return
  }
  $backup = [string]$parsed.backup
  $cfg = [string]$parsed.cfg
  if (-not $backup -or -not $cfg) { return }
  if (-not (Test-UnderBase $backup $Base)) { return }
  if (-not (Test-UnderBase $cfg $Base)) { return }
  if (-not (Test-Path -LiteralPath $backup)) { return }
  if (-not (Test-Path -LiteralPath $cfg)) { return }
  Copy-Item -LiteralPath $backup -Destination $cfg -Force
}

& (Join-Path $PSScriptRoot "stop.ps1")
$left = Get-ReceiverLeft $base
$deadline = (Get-Date).AddSeconds([Math]::Max(0, $StopWaitSec))
while ($left -and (Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 1
  $left = Get-ReceiverLeft $base
}
if ($left) {
  Restore-SwitchBackup $base
  $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
  if (-not $py) { $py = "C:\Program Files\Python312\python.exe" }
  if (Test-Path -LiteralPath $py) {
    & $py (Join-Path $base "feature_switch.py") --reload-failed --base $base --reason still_running
  }
  $cl = [string]$left.CommandLine
  if ($cl.Length -gt 160) { $cl = $cl.Substring(0, 160) + "..." }
  "refused: receiver still running (pid $($left.ProcessId), waited $StopWaitSec s): $cl"
  exit 3
}
& (Join-Path $PSScriptRoot "start.ps1") -Config $Config
if ($LASTEXITCODE -is [int] -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
exit 0
