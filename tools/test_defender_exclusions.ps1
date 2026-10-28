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
function Remove-MpPreference {
  [CmdletBinding()]
  param([string[]] $ExclusionPath, [string[]] $ExclusionExtension)
  if ($PSBoundParameters.ContainsKey('ExclusionPath')) {
    $script:preferences.ExclusionPath = @($script:preferences.ExclusionPath | Where-Object { $_ -notin $ExclusionPath })
  }
  if ($PSBoundParameters.ContainsKey('ExclusionExtension')) {
    $script:preferences.ExclusionExtension = @($script:preferences.ExclusionExtension | Where-Object { $_ -notin $ExclusionExtension })
  }
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
$originalActions = $env:GITHUB_ACTIONS
$originalRunner = $env:RUNNER_ENVIRONMENT
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

  $unrelated = Join-Path $root 'unrelated'
  $script:preferences.ExclusionPath = @($root, $unrelated)
  $script:preferences.ExclusionExtension = @('.EXE', '.unrelated')
  $env:GITHUB_ACTIONS = 'true'
  $env:RUNNER_ENVIRONMENT = 'self-hosted'
  $rejected = $false
  try { Enable-DefenderTargetScanOnHostedRunner -Target $folder } catch {
    if ($_.Exception.Message -notlike '*outside a GitHub-hosted runner*') { throw }
    $rejected = $true
  }
  if (-not $rejected) { throw 'Exclusion removal must reject self-hosted runners.' }
  $env:RUNNER_ENVIRONMENT = 'github-hosted'
  Enable-DefenderTargetScanOnHostedRunner -Target $folder
  if ($root -in $script:preferences.ExclusionPath -or '.EXE' -in $script:preferences.ExclusionExtension -or
      $unrelated -notin $script:preferences.ExclusionPath -or '.unrelated' -notin $script:preferences.ExclusionExtension) {
    throw 'Only exclusions matching the scan target should be removed.'
  }
  Write-Host 'PASS: Defender exclusion checks and hosted-runner-only removal'
} finally {
  $env:GITHUB_ACTIONS = $originalActions
  $env:RUNNER_ENVIRONMENT = $originalRunner
  if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
