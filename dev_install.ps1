<#
.SYNOPSIS
  Switch the installed addon between the released build and the repo checkout.

.DESCRIPTION
  David works in Blender as an artist and only dips into development for short
  sessions, so the DEFAULT state is 'prod': the same released build the rest of
  the team is running. 'dev' points Blender at the repo working tree through a
  junction, which is only wanted while actively testing a change -- leave it
  there and a half-finished commit on main becomes a broken Lightgroups tab in
  the middle of a job.

  This exists because the swap is easy to forget in both directions. After a
  release the folder is a real install and repo edits silently never reach
  Blender; a whole new tool once appeared to be "missing" for exactly that
  reason.

.EXAMPLE
  .\dev_install.ps1 status
  .\dev_install.ps1 dev      # work on the addon
  .\dev_install.ps1 prod     # back to the team's build
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('dev', 'prod', 'status')]
    [string]$Mode = 'status',

    [string]$BlenderVersion = '5.2'
)

$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$source = Join-Path $repoRoot 'lightgroup_tools'
$addons = Join-Path $env:APPDATA "Blender Foundation\Blender\$BlenderVersion\scripts\addons"
$dest = Join-Path $addons 'lightgroup_tools'

function Get-InstalledVersion {
    param([string]$Path)
    $init = Join-Path $Path '__init__.py'
    if (-not (Test-Path $init)) { return '<no __init__.py>' }
    $line = Select-String -Path $init -Pattern '"version"\s*:\s*\(([^)]*)\)' | Select-Object -First 1
    if ($null -eq $line) { return '<unknown>' }
    return ($line.Matches[0].Groups[1].Value -replace '\s', '')
}

function Show-Status {
    if (-not (Test-Path $dest)) {
        Write-Host "  not installed for Blender $BlenderVersion" -ForegroundColor Yellow
        return
    }
    $item = Get-Item $dest -Force
    $kind = if ($item.LinkType -eq 'Junction') { 'DEV  (junction -> repo)' } else { 'PROD (real installed copy)' }
    $colour = if ($item.LinkType -eq 'Junction') { 'Cyan' } else { 'Green' }
    Write-Host "  mode:    $kind" -ForegroundColor $colour
    if ($item.Target) { Write-Host "  target:  $($item.Target)" }
    Write-Host "  version: $(Get-InstalledVersion $dest)"
    $tools = (Get-ChildItem $dest -Directory -Name | Where-Object { $_ -ne '__pycache__' } | Sort-Object) -join ', '
    Write-Host "  tools:   $tools"
}

function Remove-Install {
    if (-not (Test-Path $dest)) { return }
    $item = Get-Item $dest -Force
    if ($item.LinkType -eq 'Junction') {
        # Delete the link itself. Remove-Item -Recurse on a junction has a
        # history of following it and eating the TARGET -- which here is the
        # git working tree. Directory.Delete removes only the reparse point.
        [System.IO.Directory]::Delete($dest, $false)
    } else {
        Remove-Item -Recurse -Force $dest
    }
}

Write-Host ""
Write-Host "Blender $BlenderVersion addon: $dest"
Write-Host ""

switch ($Mode) {
    'status' {
        Show-Status
    }

    'dev' {
        if (-not (Test-Path $source)) { throw "Repo package not found at $source" }
        if (-not (Test-Path $addons)) { New-Item -ItemType Directory -Force $addons | Out-Null }
        Remove-Install
        New-Item -ItemType Junction -Path $dest -Target $source | Out-Null
        Write-Host "Switched to DEV." -ForegroundColor Cyan
        Write-Host "Blender now loads the repo working tree - restart Blender." -ForegroundColor Cyan
        Write-Host "Run '.\dev_install.ps1 prod' when you go back to real work." -ForegroundColor Yellow
        Write-Host ""
        Show-Status
    }

    'prod' {
        # The team installs the hand-built release zip, so that is what 'prod'
        # restores -- not the repo tree, which may be ahead of the release.
        $zip = Get-ChildItem $repoRoot -Filter 'lightgroup_tools_v*.zip' |
               Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -eq $zip) { throw "No lightgroup_tools_v*.zip found in $repoRoot" }

        $staging = Join-Path ([System.IO.Path]::GetTempPath()) ("lgt_prod_" + [guid]::NewGuid().ToString('N'))
        try {
            Expand-Archive -Path $zip.FullName -DestinationPath $staging -Force
            $payload = Join-Path $staging 'lightgroup_tools'
            if (-not (Test-Path $payload)) { throw "$($zip.Name) does not contain a lightgroup_tools/ folder at its root" }

            if (-not (Test-Path $addons)) { New-Item -ItemType Directory -Force $addons | Out-Null }
            Remove-Install
            Copy-Item $payload $dest -Recurse -Force
            Get-ChildItem $dest -Recurse -Directory -Filter '__pycache__' |
                Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        } finally {
            if (Test-Path $staging) { Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue }
        }

        Write-Host "Switched to PROD from $($zip.Name)." -ForegroundColor Green
        Write-Host "Same build as the team - restart Blender." -ForegroundColor Green
        Write-Host ""
        Show-Status
    }
}

Write-Host ""
