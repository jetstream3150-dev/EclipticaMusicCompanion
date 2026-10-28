# Fail closed when a Defender exclusion could prevent a custom scan from
# covering any target file. This is used only on the temporary CI runner.
function Assert-DefenderTargetNotExcluded {
  param([Parameter(Mandatory=$true)][string] $Target)

  $item = Get-Item -LiteralPath $Target -ErrorAction Stop
  $targets = @($item)
  if ($item.PSIsContainer) {
    $targets += @(Get-ChildItem -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop)
  }
  $prefs = Get-MpPreference -ErrorAction Stop
  foreach ($entry in $targets) {
    foreach ($exclusion in @($prefs.ExclusionPath)) {
      if (-not $exclusion) { continue }
      $pattern = [Environment]::ExpandEnvironmentVariables([string]$exclusion).TrimEnd('\', '/')
      if ($entry.FullName -like $pattern -or $entry.FullName -like ($pattern + '\*')) {
        throw "A scan target is under a Defender path exclusion: $($entry.FullName)"
      }
    }
    if (-not $entry.PSIsContainer) {
      $extension = $entry.Extension.TrimStart('.').ToLowerInvariant()
      foreach ($exclusion in @($prefs.ExclusionExtension)) {
        if ($exclusion -and $extension -and
            ([string]$exclusion).TrimStart('.').ToLowerInvariant() -eq $extension) {
          throw "A scan target's extension is excluded from Defender: $($entry.FullName)"
        }
      }
    }
  }
  Write-Host "PASS: no Defender path or extension exclusions match $($item.FullName)"
}
