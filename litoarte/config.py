"""Configuração de ambiente.

LITOARTE_DB_URL define o banco (padrão: SQLite na pasta do projeto).
Exemplos:
    sqlite:///D:/Litoarte/litoarte.db
    postgresql+psycopg://usuario:senha@servidor:5432/litoarte
"""

import os
from pathlib import Path

PASTA_PROJETO = Path(__file__).resolve().parent.parent
URL_PADRAO = f"sqlite:///{(PASTA_PROJETO / 'litoarte.db').as_posix()}"


def url_banco() -> str:
    return os.environ.get("LITOARTE_DB_URL", URL_PADRAO)
