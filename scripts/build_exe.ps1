<#
.SYNOPSIS
    Builds standalone Windows executables:
      - dist\ClassroomTeacher.exe
      - dist\ClassroomStudent.exe
#>
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) {
    Write-Host "Устанавливаю PyInstaller в .venv..." -ForegroundColor Cyan
    & (Join-Path $ProjectRoot ".venv\Scripts\pip.exe") install pyinstaller
}

$TeacherIco = Join-Path $ProjectRoot "assets\teacher.ico"
$StudentIco = Join-Path $ProjectRoot "assets\student.ico"
if ((-not (Test-Path $TeacherIco)) -or (-not (Test-Path $StudentIco))) {
    Write-Host "`nГенерация иконок приложений (assets\teacher.ico, assets\student.ico)..." -ForegroundColor Cyan
    $PrevQpa = $env:QT_QPA_PLATFORM
    $env:QT_QPA_PLATFORM = "offscreen"
    try {
        & $Python (Join-Path $ProjectRoot "scripts\generate_icons.py")
        if ($LASTEXITCODE -ne 0) { throw "generate_icons.py завершился с ошибкой ($LASTEXITCODE)" }
    } finally {
        if ($null -eq $PrevQpa) {
            Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        } else {
            $env:QT_QPA_PLATFORM = $PrevQpa
        }
    }
}

Write-Host "`n[1/2] Сборка ClassroomTeacher.exe..." -ForegroundColor Cyan
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ClassroomTeacher" `
    --icon "assets\teacher.ico" `
    --add-data "assets;assets" `
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

Write-Host "`n[2/3] Сборка ClassroomStudent.exe..." -ForegroundColor Cyan
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ClassroomStudent" `
    --icon "assets\student.ico" `
    --add-data "assets;assets" `
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

Write-Host "`n[3/3] Сборка единого установщика ClassroomManagerSetup.exe..." -ForegroundColor Cyan
& $PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "ClassroomManagerSetup" `
    --icon "assets\teacher.ico" `
    --add-data "assets;assets" `
    --add-data "scripts\setup_firewall.ps1;payload" `
    --add-binary "dist\ClassroomTeacher.exe;payload" `
    --add-binary "dist\ClassroomStudent.exe;payload" `
    --paths "." `
    --hidden-import "cryptography" `
    --exclude-module "PySide6.QtWebEngineCore" `
    --exclude-module "PySide6.QtWebEngineWidgets" `
    --exclude-module "PySide6.QtPdf" `
    --exclude-module "PySide6.Qt3DCore" `
    --exclude-module "PySide6.QtMultimedia" `
    --exclude-module "PySide6.QtQml" `
    --exclude-module "PySide6.QtQuick" `
    "installer_app\main.py"

Write-Host "`nГотово! Собранные файлы:" -ForegroundColor Green
Get-ChildItem (Join-Path $ProjectRoot "dist\*.exe") | Format-Table Name, @{N="Size (MB)";E={[math]::Round($_.Length/1MB, 1)}}
