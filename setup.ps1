# Windows (PowerShell): cria o ambiente virtual isolado do sistema de custos.
# Se o PowerShell bloquear a execucao, rode:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
Set-Location $PSScriptRoot
if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip -q
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" -q
Write-Host "Ambiente pronto. Ative com:  .\.venv\Scripts\Activate.ps1"
Write-Host "Rode o app com:              streamlit run app_custos.py"
Write-Host "Ou simplesmente de duplo clique em iniciar.bat"
