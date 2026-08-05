[CmdletBinding()]
param(
    [ValidateSet("cp312", "cp313")]
    [string]$Implementation = "cp312",
    [string]$PythonVersion = "3.12",
    [string]$Platform = "manylinux_2_17_x86_64",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Constraints = Join-Path $Root "constraints\$Implementation-linux-x86_64.txt"
$Output = Join-Path $Root "wheelhouse\linux-x86_64-$Implementation"
$Manifest = Join-Path $Root "wheelhouse\manifests\$Implementation.json"

if (-not (Test-Path $Constraints -PathType Leaf)) {
    throw "Missing locked constraint file: $Constraints"
}
New-Item -ItemType Directory -Path $Output -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $Manifest) -Force | Out-Null
Get-ChildItem -Path $Output -Filter "*.whl" -File | Remove-Item -Force

# --platform/--python-version/--implementation/--abi force target-platform downloads.
# --only-binary prevents accidental local Windows builds or sdists.
& $Python -m pip download `
    --dest $Output `
    --requirement $Constraints `
    --only-binary=:all: `
    --platform $Platform `
    --python-version $PythonVersion `
    --implementation cp `
    --abi $Implementation `
    --abi abi3 `
    --abi none `
    --disable-pip-version-check
if ($LASTEXITCODE -ne 0) {
    throw "Target-platform wheel download failed"
}

$SumFile = Join-Path $Output "SHA256SUMS"
$Lines = Get-ChildItem -Path $Output -Filter "*.whl" -File |
    Sort-Object Name |
    ForEach-Object {
        $Hash = (Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant()
        "$Hash  $($_.Name)"
    }
[System.IO.File]::WriteAllLines($SumFile, $Lines, [System.Text.UTF8Encoding]::new($false))

& $Python (Join-Path $Root "scripts\verify-wheelhouse.py") $Output `
    --implementation $Implementation `
    --python-version $PythonVersion `
    --sha256sums $SumFile `
    --manifest $Manifest
if ($LASTEXITCODE -ne 0) {
    throw "Wheelhouse tag/hash validation failed"
}

$ManifestHash = (Get-FileHash -Algorithm SHA256 -Path $Manifest).Hash.ToLowerInvariant()
Write-Output "wheelhouse=$Output"
Write-Output "manifest=$Manifest"
Write-Output "manifest_sha256=$ManifestHash"
