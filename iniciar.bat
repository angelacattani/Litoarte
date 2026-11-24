@echo off
REM ==========================================================
REM  Litoarte v2 - duplo clique para abrir o sistema.
REM  1a vez (ou apos atualizar): cria/atualiza o ambiente.
REM ==========================================================
setlocal
cd /d "%~dp0"

REM --- a pasta precisa conter o programa completo (ZIP extraido inteiro)
if not exist "litoarte\__main__.py" goto pasta_incompleta
if not exist "pyproject.toml" goto pasta_incompleta

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

REM --- (re)instala quando o pyproject.toml mudou ou o pacote nao esta instalado
".venv\Scripts\python.exe" -c "import litoarte.app.main" >nul 2>nul
if errorlevel 1 del ".venv\pyproject.instalado" >nul 2>nul
fc /b pyproject.toml ".venv\pyproject.instalado" >nul 2>nul
if errorlevel 1 (
    echo Instalando dependencias, aguarde alguns minutos...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -e . > instalacao.log 2>&1
    if errorlevel 1 (
        echo.
        echo ERRO na instalacao das dependencias. Detalhes em: %~dp0instalacao.log
        pause
        exit /b 1
    )
    copy /y pyproject.toml ".venv\pyproject.instalado" >nul
)

echo Abrindo o Litoarte em http://localhost:8503  (feche esta janela para encerrar)
set "PYTHONPATH=%~dp0"
".venv\Scripts\python.exe" -m litoarte
pause
exit /b 0

:pasta_incompleta
echo.
echo ERRO: esta pasta nao contem o programa completo:
echo   %~dp0
echo Falta a pasta "litoarte" (ou o arquivo pyproject.toml) ao lado deste iniciar.bat.
echo.
echo Extraia o ZIP baixado do GitHub INTEIRO numa pasta nova e execute o
echo iniciar.bat que esta dentro dela (junto das pastas litoarte, docs e tests).
pause
exit /b 1
