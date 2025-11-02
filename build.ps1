<# ============================================================================
  Angular → Django Wizard — Build Script (FINAL PORTABLE)
  Usage (PowerShell depuis le dossier du projet):
    Set-ExecutionPolicy -Scope Process RemoteSigned
    ./build.ps1                         # build par défaut
    ./build.ps1 -Icon "assets\wizard.ico" -VersionFile "version_info.txt" -Clean
    ./build.ps1 -Name "AngularDjangoWizard" -NoUPX

  Résultat :
    dist/AngularDjangoWizard.exe   (standalone portable, pas besoin d’installer Python)

  Ce script :
    - crée .venv si besoin
    - installe PyInstaller
    - build un .exe onefile sans console
    - active le mode DPI per-monitor-v2 via PyInstaller (au lieu d'un manifest custom)
    - n’utilise PAS de manifeste externe (ça évite l’erreur "côte à côte incorrecte")
============================================================================ #>

[CmdletBinding()]
param(
  [string]$EntryPoint = "angular_django_wizard.py",
  [string]$Name = "AngularDjangoWizard",
  [string]$Icon = "assets\wizard.ico",
  [string]$VersionFile = "version_info.txt",
  [switch]$Clean,
  [switch]$NoUPX
)

function Write-Info($msg){ Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Warn($msg){ Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err ($msg){ Write-Host "[ERR ] $msg" -ForegroundColor Red }

# --- Trouver Python ---
$python = ""
try {
  $null = & py --version 2>$null
  if ($LASTEXITCODE -eq 0) { $python = "py" }
} catch {}
if (-not $python) {
  try {
    $null = & python --version 2>$null
    if ($LASTEXITCODE -eq 0) { $python = "python" }
  } catch {}
}
if (-not $python) {
  Write-Err "Python introuvable (ni 'py' ni 'python')."
  exit 1
}

# --- Créer venv si pas déjà là ---
if (-not (Test-Path ".venv")) {
  Write-Info "Création du venv (.venv)..."
  & $python -m venv .venv
  if ($LASTEXITCODE -ne 0) {
    Write-Err "Échec création de l'environnement virtuel."
    exit 1
  }
}

# --- Activer venv ---
Write-Info "Activation du venv..."
. .\.venv\Scripts\Activate.ps1

# --- Installer / mettre à jour dépendances ---
Write-Info "Mise à jour pip..."
python -m pip install --upgrade pip > $null
if ($LASTEXITCODE -ne 0) { Write-Err "pip upgrade a échoué."; exit 1 }

Write-Info "Installation / mise à jour PyInstaller..."
python -m pip install --upgrade pyinstaller > $null
if ($LASTEXITCODE -ne 0) { Write-Err "pyinstaller install a échoué."; exit 1 }

# On n'a pas besoin d'installer d'autres libs parce que ton script n'utilise
# que la stdlib (tkinter, shutil, etc.) qui est déjà incluse dans Python.

# --- UPX optionnel pour compresser ---
$UseUPX = $true
if ($NoUPX) {
  $UseUPX = $false
} elseif (-not (Get-Command upx -ErrorAction SilentlyContinue)) {
  $UseUPX = $false
}

# --- Vérifier fichiers sources ---
if (-not (Test-Path $EntryPoint)) {
  Write-Err "EntryPoint '$EntryPoint' introuvable. Vérifie que angular_django_wizard.py est dans ce dossier."
  exit 1
}

$iconArg = @()
if (Test-Path $Icon) {
  $iconArg = @("--icon", $Icon)
} else {
  Write-Warn "Icône '$Icon' absente → pas d'icône custom."
}

$verArg = @()
if (Test-Path $VersionFile) {
  $verArg = @("--version-file", $VersionFile)
} else {
  Write-Warn "Version file '$VersionFile' absent → pas d'info de version intégrée."
}

# NOTE IMPORTANTE :
# PAS de manifest externe. On LAISSE PyInstaller générer son propre manifest Windows.
# C'est ce qui résout l'erreur 'configuration côte à côte incorrecte'.

# --- Nettoyage des anciens builds si demandé ---
if ($Clean) {
  Write-Info "Nettoyage des anciens builds (build/, dist/, __pycache__/)..."
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, "__pycache__"
}

# --- Construire la liste d'arguments PyInstaller ---
# Flags importants :
#   --onefile     => un seul .exe portable
#   --windowed    => pas de console noire
#   --dpi-aware permonitorv2  => sharp sur écrans haute résolution
#   --clean       => rebuild propre
$common = @(
  "--onefile",
  "--windowed",
  "--name", $Name
) + $iconArg + $verArg

if ($UseUPX) {
  try {
    $upxPath = (Get-Command upx -ErrorAction Stop).Path
    $upxDir = Split-Path $upxPath -Parent
    $common += @("--upx-dir", $upxDir)
  } catch {
    # pas grave
  }
}

$args = $common + @("--clean", $EntryPoint)

# --- Afficher la commande finale pour debug ---
Write-Info "Construction avec PyInstaller (via python -m PyInstaller)..."
Write-Host ("▶ {0} -m PyInstaller {1}" -f $python, ($args -join ' ')) -ForegroundColor Green

# --- Lancer la construction ---
& $python -m PyInstaller @args
if ($LASTEXITCODE -ne 0) {
  Write-Err "Build PyInstaller échoué."
  exit 1
}

# --- Vérifier résultat final ---
$exePath = Join-Path "dist" ("{0}.exe" -f $Name)
if (Test-Path $exePath) {
  Write-Host ""
  Write-Host "✅ Build réussi : $exePath" -ForegroundColor Green
  Write-Host "Tu peux lancer ce fichier directement (double-clic). Pas d'installation nécessaire."
} else {
  Write-Warn "Build terminé, mais exe introuvable dans dist/. Vérifie la sortie PyInstaller ci-dessus."
}
