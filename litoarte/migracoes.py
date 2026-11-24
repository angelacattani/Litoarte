"""Aplicar migrações por código (usado na inicialização do app e nos testes)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import url_banco

_RAIZ = Path(__file__).resolve().parent


def config_alembic(url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_RAIZ / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url or url_banco())
    return cfg


def atualizar_banco(url: str | None = None, revisao: str = "head") -> None:
    """Cria ou atualiza o schema até a revisão indicada (idempotente)."""
    command.upgrade(config_alembic(url), revisao)
