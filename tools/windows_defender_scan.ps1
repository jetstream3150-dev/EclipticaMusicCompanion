param(
  [Parameter(Mandatory=$true)][string] $ReleaseDir
)
$ErrorActionPreference = 'Stop'
$folder = (Resolve-Path $ReleaseDir).Path
$report = Join-Path $folder 'DEFENDER_SCAN.txt'
$stamp = Get-Date -Format o
"Scan timestamp: $stamp`nTarget: $folder" | Out-File -FilePath $report -Encoding utf8
try {
  . (Join-Path $PSScriptRoot 'check_defender_exclusions.ps1')
  if (-not (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue)) {
    'NOT VERIFIED: Microsoft Defender cmdlets are not available on this runner.' | Add-Content $report
    throw 'Defender is unavailable; artifact must not be uploaded.'
  }
  $s = Get-MpComputerStatus -ErrorAction Stop
  if (-not $s.AMServiceEnabled -or -not $s.AntivirusEnabled) {
    'NOT VERIFIED: Microsoft Defender antivirus is disabled on this runner.' | Add-Content $report
    throw 'Defender is disabled; artifact must not be uploaded.'
  }
  $updated = $false
  try {
    Update-MpSignature -ErrorAction Stop | Out-Null
    $updated = $true
  } catch {
    "Default signature update failed: $($_.Exception.Message)" | Add-Content $report
    try {
      Update-MpSignature -UpdateSource MMPC -ErrorAction Stop | Out-Null
      $updated = $true
      'Signature update succeeded using MMPC.' | Add-Content $report
    } catch {
      "MMPC signature update failed: $($_.Exception.Message)" | Add-Content $report
    }
  }
  if (-not $updated) {
    # Microsoft documents MpCmdRun -SignatureUpdate -MMPC as a fallback.
    $mpcmd = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
    if (Test-Path $mpcmd) {
      try {
        & $mpcmd -SignatureUpdate -MMPC 2>&1 | Out-File -FilePath $report -Append -Encoding utf8
        if ($LASTEXITCODE -eq 0) { $updated = $true }
      } catch {
        "MpCmdRun signature update failed: $($_.Exception.Message)" | Add-Content $report
      }
    }
  }
  if (-not $updated) {
    Get-Content $report | Write-Host
    throw 'Defender signature update failed; artifact must not be uploaded.'
  }
  $s = Get-MpComputerStatus -ErrorAction Stop
  if (-not $s.AntivirusSignatureLastUpdated -or
      $s.AntivirusSignatureLastUpdated -lt (Get-Date).AddDays(-2)) {
    throw 'Defender signature age could not be verified or is over two days old.'
  }
  Assert-DefenderTargetNotExcluded -Target $folder
  "Signatures after update: $($s.AntivirusSignatureVersion); last updated: $($s.AntivirusSignatureLastUpdated.ToString('o'))" | Add-Content $report
  $scanStarted = Get-Date
  Start-MpScan -ScanType CustomScan -ScanPath $folder -ErrorAction Stop
  if (-not (Test-Path (Join-Path $folder 'EclipticaMusicCompanion.exe'))) {
    'FAILED: Antivirus removed or quarantined the executable.' | Add-Content $report
    throw 'Executable missing after Windows Defender scan.'
  }
  $detections = @(Get-MpThreatDetection -ErrorAction Stop | Where-Object {
    $_.InitialDetectionTime -ge $scanStarted.AddMinutes(-1) -and
    (@($_.Resources) -join ' ') -like "*$folder*"
  })
  if ($detections.Count -gt 0) {
    $detections | Format-List * | Out-String | Add-Content $report
    throw "Windows Defender reported $($detections.Count) detection(s)."
  }
  "PASSED: Defender completed a custom scan with no matching detections. Signatures: $($s.AntivirusSignatureVersion)" | Add-Content $report
  Write-Host 'Windows Defender scan completed without a matching threat.'
} catch {
  "SCAN FAILED: $($_.Exception.Message)" | Add-Content $report
  throw
}
