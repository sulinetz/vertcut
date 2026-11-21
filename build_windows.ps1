# Сборка VertCut для Windows 10/11 (x64) в один exe-каталог + ZIP.
# Запуск:  powershell -ExecutionPolicy Bypass -File build_windows.ps1
param(
    [string]$Version = "1.2.2",
    [switch]$SkipModel
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[VertCut] Python..." -ForegroundColor Cyan
$py = $null
foreach ($candidate in @("py -3.12", "python")) {
    try {
        & cmd /c "$candidate -c `"import sys; print(sys.version)`"" | Out-Null
        $py = $candidate
        break
    } catch { }
}
if (-not $py) { throw "Не найден Python 3.12. Установите с https://www.python.org/downloads/windows/" }

if (-not (Test-Path ".venv-win\Scripts\python.exe")) {
    Write-Host "[VertCut] создаю .venv-win..." -ForegroundColor Cyan
    & cmd /c "$py -m venv .venv-win"
}
$venvPy = Join-Path $PSScriptRoot ".venv-win\Scripts\python.exe"
$venvPip = Join-Path $PSScriptRoot ".venv-win\Scripts\pip.exe"

& $venvPy -m pip install --upgrade pip
& $venvPip install -r requirements-desktop.txt pyinstaller

if (-not $SkipModel -and -not (Test-Path "build\whisper-small\model.bin")) {
    Write-Host "[VertCut] скачиваю Whisper Small (один раз)..." -ForegroundColor Cyan
    try {
        & $venvPy -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='build/whisper-small', allow_patterns=['model.bin','config.json','tokenizer.json','vocabulary.txt'])"
    } catch {
        Write-Warning "Модель не скачалась — приложение докачает её при первом запуске."
    }
}

Write-Host "[VertCut] PyInstaller..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot ".venv-win\Scripts\pyinstaller.exe") VertCut.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }

$outDir = Join-Path $PSScriptRoot "release"
New-Item -ItemType Directory -Force $outDir | Out-Null
$zip = Join-Path $outDir "VertCut-$Version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Write-Host "[VertCut] упаковываю $zip..." -ForegroundColor Cyan
Compress-Archive -Path "dist\VertCut" -DestinationPath $zip -CompressionLevel Optimal

Write-Host ""
Write-Host "Готово: $zip" -ForegroundColor Green
Write-Host "Запуск: dist\VertCut\VertCut.exe"
