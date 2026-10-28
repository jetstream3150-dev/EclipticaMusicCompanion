$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'check_defender_exclusions.ps1')

# Mock the preference cmdlet so the path and extension checks are tested
# without changing or depending on the runner's actual antivirus settings.
$script:preferences = [pscustomobject]@{ ExclusionPath = @(); ExclusionExtension = @() }
function Get-MpPreference {
  [CmdletBinding()]
  param()
  return $script:preferences
}
function Expect-Excluded([string] $target, [string] $reason) {
  $rejected = $false
  try { Assert-DefenderTargetNotExcluded -Target $target } catch {
    if ($_.Exception.Message -notlike "*$reason*") { throw }
    $rejected = $true
  }
  if (-not $rejected) { throw "Expected an excluded target to be rejected: $target" }
}

$root = Join-Path $env:RUNNER_TEMP ('ecliptica-exclusion-test-' + [guid]::NewGuid().ToString('N'))
try {
  $folder = Join-Path $root 'app'
  New-Item -ItemType Directory -Path $folder -Force | Out-Null
  $exe = Join-Path $folder 'app.exe'
  Set-Content -LiteralPath $exe -Value 'test data'

  Assert-DefenderTargetNotExcluded -Target $folder
  $script:preferences.ExclusionPath = @($root)
  Expect-Excluded $folder 'path exclusion'
  $script:preferences.ExclusionPath = @($exe)
  Expect-Excluded $folder 'path exclusion'
  $script:preferences.ExclusionPath = @(Join-Path $root '*')
  Expect-Excluded $exe 'path exclusion'
  $script:preferences.ExclusionPath = @(Join-Path $root 'unrelated')
  Assert-DefenderTargetNotExcluded -Target $folder
  $script:preferences.ExclusionPath = @()
  $script:preferences.ExclusionExtension = @('.EXE')
  Expect-Excluded $folder 'extension is excluded'
  Write-Host 'PASS: Defender exclusion checks reject excluded paths and extensions'
} finally {
  if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
