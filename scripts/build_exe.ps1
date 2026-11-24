<#
.SYNOPSIS
    Builds standalone Windows executables:
      - dist\ClassroomTeacher.exe
      - dist\ClassroomStudent.exe
#>
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) {
    Write-Host "Устанавливаю PyInstaller в .venv..." -ForegroundColor Cyan
    & (Join-Path $ProjectRoot ".venv\Scripts\pip.exe") install pyinstaller
}

Write-Host "`n[1/2] Сборка ClassroomTeacher.exe..." -ForegroundColor Cyan
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ClassroomTeacher" `
    --paths "." `
    --hidden-import "qasync" `
    --hidden-import "cryptography" `
    --hidden-import "mss" `
    --hidden-import "PIL" `
    --exclude-module "PySide6.QtWebEngineCore" `
    --exclude-module "PySide6.QtWebEngineWidgets" `
    --exclude-module "PySide6.QtPdf" `
    --exclude-module "PySide6.Qt3DCore" `
    --exclude-module "PySide6.QtMultimedia" `
    --exclude-module "PySide6.QtQml" `
    --exclude-module "PySide6.QtQuick" `
    "teacher_app\main.py"

Write-Host "`n[2/2] Сборка ClassroomStudent.exe..." -ForegroundColor Cyan
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ClassroomStudent" `
    --paths "." `
    --hidden-import "qasync" `
    --hidden-import "cryptography" `
    --hidden-import "mss" `
    --hidden-import "PIL" `
    --exclude-module "PySide6.QtWebEngineCore" `
    --exclude-module "PySide6.QtWebEngineWidgets" `
    --exclude-module "PySide6.QtPdf" `
    --exclude-module "PySide6.Qt3DCore" `
    --exclude-module "PySide6.QtMultimedia" `
    --exclude-module "PySide6.QtQml" `
    --exclude-module "PySide6.QtQuick" `
    "student_app\main.py"

Write-Host "`nГотово! Собранные файлы:" -ForegroundColor Green
Get-ChildItem (Join-Path $ProjectRoot "dist\*.exe") | Format-Table Name, @{N="Size (MB)";E={[math]::Round($_.Length/1MB, 1)}}
