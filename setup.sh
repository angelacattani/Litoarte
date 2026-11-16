#!/usr/bin/env bash
# Cria o ambiente virtual isolado do sistema de custos e instala dependências.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e ".[dev]" -q
echo "Ambiente pronto. Ative com:  source .venv/bin/activate"
echo "Rode o app com:              streamlit run app_custos.py"
