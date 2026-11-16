@echo off
REM ==========================================================
REM  Sistema de Custos - Litoarte
REM  Duplo clique: cria o ambiente (1a vez) e abre o sistema.
REM ==========================================================
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto rodar

echo Primeira execucao: criando ambiente virtual...
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv .venv
) else (
    python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERRO: Python nao encontrado. Instale o Python 3.11 ou superior em
    echo https://www.python.org/downloads/ marcando "Add python.exe to PATH".
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -e ".[dev]" -q
if errorlevel 1 (
    echo ERRO na instalacao das dependencias.
    pause
    exit /b 1
)

:rodar
echo Abrindo o sistema em http://localhost:8502  (feche esta janela para encerrar)
".venv\Scripts\python.exe" -m streamlit run app_custos.py
pause
