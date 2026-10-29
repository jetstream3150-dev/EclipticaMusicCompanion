# Identify Defender exclusions that could prevent a custom scan from covering
# a target. Removal is permitted only on an ephemeral GitHub-hosted runner.
function Get-DefenderTargetExclusions {
  param([Parameter(Mandatory=$true)][string] $Target)

  $item = Get-Item -LiteralPath $Target -ErrorAction Stop
  $targets = @($item)
  if ($item.PSIsContainer) {
    $targets += @(Get-ChildItem -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop)
  }
  $prefs = Get-MpPreference -ErrorAction Stop
  $seen = @{}
  foreach ($entry in $targets) {
    foreach ($exclusion in @($prefs.ExclusionPath)) {
      if (-not $exclusion) { continue }
      $pattern = [Environment]::ExpandEnvironmentVariables([string]$exclusion).TrimEnd('\', '/')
      if ($entry.FullName -like $pattern -or $entry.FullName -like ($pattern + '\*')) {
        $key = 'path:' + $exclusion
        if (-not $seen.ContainsKey($key)) {
          $seen[$key] = $true
          [pscustomobject]@{ Kind = 'Path'; Value = $exclusion; Target = $entry.FullName }
        }
      }
    }
    if (-not $entry.PSIsContainer) {
      $extension = $entry.Extension.TrimStart('.').ToLowerInvariant()
      foreach ($exclusion in @($prefs.ExclusionExtension)) {
        if ($exclusion -and $extension -and
            ([string]$exclusion).TrimStart('.').ToLowerInvariant() -eq $extension) {
          $key = 'extension:' + $exclusion
          if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            [pscustomobject]@{ Kind = 'Extension'; Value = $exclusion; Target = $entry.FullName }
          }
        }
      }
    }
  }
}

function Assert-DefenderTargetNotExcluded {
  param([Parameter(Mandatory=$true)][string] $Target)
  $matches = @(Get-DefenderTargetExclusions -Target $Target)
  if ($matches.Count -gt 0) {
    $first = $matches[0]
    if ($first.Kind -eq 'Path') {
      throw "A scan target is under a Defender path exclusion '$($first.Value)': $($first.Target)"
    }
    throw "A scan target's extension is excluded from Defender '$($first.Value)': $($first.Target)"
  }
  Write-Host "PASS: no Defender path or extension exclusions match $Target"
}

function Enable-DefenderTargetScanOnHostedRunner {
  param([Parameter(Mandatory=$true)][string] $Target)
  if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Refusing to change Defender exclusions outside a GitHub-hosted runner.'
  }
  foreach ($match in @(Get-DefenderTargetExclusions -Target $Target)) {
    Write-Host "Removing runner Defender $($match.Kind) exclusion: $($match.Value)"
    if ($match.Kind -eq 'Path') {
      Remove-MpPreference -ExclusionPath $match.Value -ErrorAction Stop
    } else {
      Remove-MpPreference -ExclusionExtension $match.Value -ErrorAction Stop
    }
  }
  # Group policy or tamper protection may prevent a removal from taking effect.
  Assert-DefenderTargetNotExcluded -Target $Target
}
