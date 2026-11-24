@echo off
REM ==========================================================
REM  Litoarte v2 - duplo clique para abrir o sistema.
REM  1a vez (ou apos atualizar): cria/atualiza o ambiente.
REM ==========================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    where py >nul 2>nul
    if %errorlevel%==0 (py -3 -m venv .venv) else (python -m venv .venv)
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERRO: Python nao encontrado. Instale o Python 3.11 ou superior em
    echo https://www.python.org/downloads/ marcando "Add python.exe to PATH".
    pause
    exit /b 1
)

REM reinstala quando o pyproject.toml mudou (nova versao baixada)
fc /b pyproject.toml ".venv\pyproject.instalado" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias, aguarde alguns minutos...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -e . -q
    if errorlevel 1 (
        echo ERRO na instalacao das dependencias.
        pause
        exit /b 1
    )
    copy /y pyproject.toml ".venv\pyproject.instalado" >nul
)

echo Abrindo o Litoarte em http://localhost:8503  (feche esta janela para encerrar)
".venv\Scripts\python.exe" -m litoarte
pause
