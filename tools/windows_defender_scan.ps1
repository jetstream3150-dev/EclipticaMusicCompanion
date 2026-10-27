param(
  [Parameter(Mandatory=$true)][string] $ReleaseDir
)
$ErrorActionPreference = 'Stop'
$folder = (Resolve-Path $ReleaseDir).Path
$report = Join-Path $folder 'DEFENDER_SCAN.txt'
$stamp = Get-Date -Format o
"Scan timestamp: $stamp`nTarget: $folder" | Out-File -FilePath $report -Encoding utf8
try {
  if (-not (Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue)) {
    'NOT VERIFIED: Microsoft Defender cmdlets are not available on this runner.' | Add-Content $report
    throw 'Defender is unavailable; artifact must not be uploaded.'
  }
  $s = Get-MpComputerStatus -ErrorAction Stop
  if (-not $s.AMServiceEnabled -or -not $s.AntivirusEnabled) {
    'NOT VERIFIED: Microsoft Defender antivirus is disabled on this runner.' | Add-Content $report
    throw 'Defender is disabled; artifact must not be uploaded.'
  }
  try { Update-MpSignature -ErrorAction Stop | Out-Null }
  catch { "SIGNATURE UPDATE WARNING: $($_.Exception.Message)" | Add-Content $report }
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
