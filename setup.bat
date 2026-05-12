@echo off
REM ============================================================
REM Gerador de Shorts - Setup automatizado para Windows 10/11
REM ============================================================
REM Pre-requisito: Python 3.10+ ja instalado e no PATH.
REM
REM Uso:
REM   setup.bat
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo [setup] Projeto: %CD%
echo.

REM ------------------------------------------------------------
REM 1. Verificar Python
REM ------------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [erro] Python nao encontrado no PATH.
    echo        Instale Python 3.10+ de https://www.python.org/downloads/
    echo        Marque "Add Python to PATH" durante a instalacao.
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VERSION=%%v
echo [setup] Python detectado: %PY_VERSION%

REM ------------------------------------------------------------
REM 2. Verificar FFmpeg (avisa, nao bloqueia)
REM ------------------------------------------------------------
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [aviso] FFmpeg nao encontrado no PATH.
    echo         Instale com:  winget install Gyan.FFmpeg
    echo         Depois ABRA UM NOVO TERMINAL e rode setup.bat de novo.
    echo         Continuando setup do Python mesmo assim...
    echo.
) else (
    echo [setup] FFmpeg detectado.
)

REM ------------------------------------------------------------
REM 3. Criar ambiente virtual
REM ------------------------------------------------------------
if not exist "venv\" (
    echo [setup] Criando ambiente virtual em .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo [erro] Falha ao criar venv.
        exit /b 1
    )
) else (
    echo [setup] Ambiente virtual ja existe.
)

REM ------------------------------------------------------------
REM 4. Instalar dependencias Python
REM ------------------------------------------------------------
echo [setup] Atualizando pip e instalando dependencias...
call venv\Scripts\python.exe -m pip install --upgrade pip --quiet
call venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo [erro] Falha ao instalar requirements.
    exit /b 1
)

REM ------------------------------------------------------------
REM 5. Criar pastas de dados
REM ------------------------------------------------------------
if not exist "data\inputs"  mkdir data\inputs
if not exist "data\outputs" mkdir data\outputs
if not exist "data\temp"    mkdir data\temp

echo.
echo [setup] Concluido com sucesso!
echo.
echo Para ativar o ambiente em qualquer terminal novo:
echo   venv\Scripts\activate
echo.
echo Para testar agora (baixa um video de 19s do YouTube):
echo   venv\Scripts\activate
echo   python -m src.downloader.cli "https://www.youtube.com/watch?v=jNQXAC9IVRw"
echo.

endlocal
