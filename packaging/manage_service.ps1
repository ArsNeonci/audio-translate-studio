<#
.SYNOPSIS
  Install / remove / control the Audio Translate security service. Requires an elevated shell.

  The native core runs as a Windows service (its `service` argument hands control to the SCM).
  Use the TEST name against a copied binary when verifying Phase 2; never point the test name at
  the real installation. The real service name is AudioTranslate; the throwaway test name is
  AudioTranslateSecTest.

.EXAMPLE
  # Verify Phase 2 against a copied binary, then clean up:
  .\manage_service.ps1 -Action install -Name AudioTranslateSecTest -ExePath C:\test\core.exe
  .\manage_service.ps1 -Action start   -Name AudioTranslateSecTest
  .\manage_service.ps1 -Action stop    -Name AudioTranslateSecTest
  .\manage_service.ps1 -Action remove  -Name AudioTranslateSecTest
#>
param(
  [Parameter(Mandatory = $true)][ValidateSet('install','remove','start','stop','status')][string]$Action,
  [Parameter(Mandatory = $true)][string]$Name,
  [string]$ExePath
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($id)
  if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "This action needs an elevated (Administrator) PowerShell."
  }
}

switch ($Action) {
  'install' {
    Assert-Admin
    if (-not $ExePath) { throw "-ExePath is required for install." }
    $exe = (Resolve-Path $ExePath).Path
    # LocalSystem, demand start. The service owns the pipe before any user process.
    $bin = '"{0}" service' -f $exe
    sc.exe create $Name binPath= $bin start= demand obj= LocalSystem DisplayName= "Audio Translate Security ($Name)" | Out-Host
    sc.exe description $Name "Audio Translate local security authority (license, integrity, lease)." | Out-Host
    Write-Host "Installed service '$Name'. Start it with: .\manage_service.ps1 -Action start -Name $Name"
  }
  'remove' {
    Assert-Admin
    cmd /c "sc.exe stop $Name" | Out-Host
    sc.exe delete $Name | Out-Host
    Write-Host "Removed service '$Name'."
  }
  'start'  { Assert-Admin; sc.exe start $Name | Out-Host }
  'stop'   { Assert-Admin; sc.exe stop  $Name | Out-Host }
  'status' { sc.exe query $Name | Out-Host }
}
