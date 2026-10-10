<#
.SYNOPSIS
  Compila iliad counter: eseguibile (PyInstaller) e setup (Inno Setup) in dist/.
.PARAMETER Version
  Versione scritta nel setup, es. 1.1.0.
.PARAMETER Sign
  Firma eseguibile, setup e disinstallatore con Azure Artifact Signing.
  Servono il Windows SDK (signtool) e un login Azure CLI valido:
    az login --scope https://codesigning.azure.net/.default
  con il ruolo "Artifact Signing Certificate Profile Signer". Account e profilo
  stanno in packaging/artifact-signing.json (non sono segreti).
#>
param(
    [Parameter(Mandatory)][string]$Version,
    [switch]$Sign
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

if ($Sign) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [version]$_.Directory.Parent.Name } | Select-Object -Last 1 -ExpandProperty FullName
    if (-not $signtool) { throw 'signtool.exe non trovato: installa il Windows SDK' }

    # plug-in di signtool che firma tramite Azure, scaricato una volta in .tools/
    $dlibVersion = '1.0.128'
    $dlibDir = Join-Path $root ".tools\artifact-signing-$dlibVersion"
    $dlib = Join-Path $dlibDir 'bin\x64\Azure.CodeSigning.Dlib.dll'
    if (-not (Test-Path $dlib)) {
        $nupkg = Join-Path $root ".tools\artifact-signing-$dlibVersion.zip"
        New-Item -ItemType Directory -Force (Split-Path $nupkg) | Out-Null
        Invoke-WebRequest "https://www.nuget.org/api/v2/package/Microsoft.ArtifactSigning.Client/$dlibVersion" -OutFile $nupkg
        Expand-Archive $nupkg -DestinationPath $dlibDir -Force
        Remove-Item $nupkg
    }
    $metadata = Join-Path $root 'packaging\artifact-signing.json'
    $signArgs = @('sign', '/fd', 'SHA256', '/tr', 'http://timestamp.acs.microsoft.com', '/td', 'SHA256',
                  '/dlib', $dlib, '/dmdf', $metadata)
}

# ---- eseguibile ----
& $python -m PyInstaller --noconfirm (Join-Path $root 'packaging\iliad-counter.spec')
if ($LASTEXITCODE) { throw 'PyInstaller ha fallito' }
$exe = Join-Path $root 'dist\iliad-counter\iliad-counter.exe'
if ($Sign) {
    & $signtool @signArgs $exe
    if ($LASTEXITCODE) { throw "Firma fallita: $exe" }
}

# ---- setup ----
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw 'Inno Setup 6 non trovato (https://jrsoftware.org/isinfo.php)' }
$isccArgs = @('/Q', "/DMyAppVersion=$Version")
if ($Sign) {
    # Inno firma setup e disinstallatore; $q e' una virgoletta, $f il file
    $command = (@($signtool) + $signArgs | ForEach-Object { if ($_ -match ' ') { "`$q$_`$q" } else { $_ } }) -join ' '
    $isccArgs += @('/DSign', "/Sartifactsigning=$command `$f")
}
& $iscc @isccArgs (Join-Path $root 'packaging\installer.iss')
if ($LASTEXITCODE) { throw 'Inno Setup ha fallito' }
$setup = Join-Path $root "dist\installer\iliad-counter-setup-$Version.exe"
Write-Host "Setup: $setup" -ForegroundColor Green

if ($Sign) {
    & $signtool verify /pa $exe $setup
    if ($LASTEXITCODE) { throw 'Verifica della firma fallita' }
    Write-Host 'Firme verificate' -ForegroundColor Green
}
