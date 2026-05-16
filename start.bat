@echo off
REM ============================================================
REM Gerador de Shorts - Inicia backend (FastAPI) + frontend (Vite)
REM em duas janelas cmd separadas, e abre o browser na URL do app.
REM
REM Uso:
REM   start.bat
REM
REM Pre-requisitos (rodar UMA vez antes):
REM   - venv Python configurado:  setup.bat
REM   - node_modules instalado:   cd frontend ^&^& npm install
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo  Gerador de Shorts - Iniciando servidores
echo ============================================================
echo.

REM ------------------------------------------------------------
REM 1. Verificacoes pre-flight
REM ------------------------------------------------------------
if not exist "venv\Scripts\activate.bat" (
    echo [erro] venv nao encontrado.
    echo        Rode primeiro:  setup.bat
    echo.
    pause
    exit /b 1
)

if not exist "frontend\node_modules\" (
    echo [erro] node_modules do frontend nao encontrado.
    echo        Rode primeiro:
    echo            cd frontend
    echo            npm install
    echo.
    pause
    exit /b 1
)

REM ------------------------------------------------------------
REM 2. Inicia o BACKEND em janela separada
REM    cmd /k mantem a janela aberta apos rodar (pra ver logs).
REM    O titulo "Shorts API" facilita identificar.
REM ------------------------------------------------------------
echo [1/2] Iniciando API FastAPI em http://127.0.0.1:8000 ...
start "Shorts API (backend)" cmd /k "cd /d %CD% && venv\Scripts\activate.bat && python -m src.api.cli"

REM Pequena espera pra o backend subir antes do frontend tentar conectar
timeout /t 3 /nobreak >nul

REM ------------------------------------------------------------
REM 3. Inicia o FRONTEND em outra janela separada
REM ------------------------------------------------------------
echo [2/2] Iniciando frontend Vite em http://localhost:5173 ...
start "Shorts UI (frontend)" cmd /k "cd /d %CD%\frontend && npm run dev"

REM ------------------------------------------------------------
REM 4. Aguarda mais um pouco e abre o browser
REM ------------------------------------------------------------
echo.
echo Aguardando o frontend ficar pronto (5s) ...
timeout /t 5 /nobreak >nul

echo Abrindo browser ...
start "" http://localhost:5173

echo.
echo ============================================================
echo  Tudo iniciado!
echo ============================================================
echo  Backend  : http://127.0.0.1:8000  (Swagger em /docs)
echo  Frontend : http://localhost:5173
echo.
echo  Pra ENCERRAR: feche as duas janelas que abriram.
echo  (Ctrl+C dentro delas tambem funciona.)
echo ============================================================
echo.

endlocal
