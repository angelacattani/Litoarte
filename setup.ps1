# Windows (PowerShell): cria o ambiente virtual isolado do sistema de custos.
Set-Location $PSScriptRoot
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip -q
.\.venv\Scripts\pip install -e ".[dev]" -q
Write-Host "Ambiente pronto. Ative com:  .\.venv\Scripts\Activate.ps1"
Write-Host "Rode o app com:              streamlit run app_custos.py"
