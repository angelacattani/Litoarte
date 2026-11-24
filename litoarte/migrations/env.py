"""Ambiente do Alembic: usa os modelos do domínio e a URL de litoarte.config."""

from alembic import context

from litoarte.config import url_banco
from litoarte.db import criar_engine
from litoarte.domain.models import Base

config = context.config
alvo = Base.metadata


def _url() -> str:
    return config.attributes.get("url") or config.get_main_option("sqlalchemy.url") or url_banco()


def rodar_offline() -> None:
    context.configure(url=_url(), target_metadata=alvo, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def rodar_online() -> None:
    conexao = config.attributes.get("connection")
    if conexao is not None:
        _migrar(conexao)
        return
    engine = criar_engine(_url())
    with engine.connect() as conexao:
        _migrar(conexao)


def _migrar(conexao) -> None:
    # render_as_batch: ALTER TABLE em SQLite é feito por recriação da tabela
    context.configure(connection=conexao, target_metadata=alvo, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    rodar_offline()
else:
    rodar_online()
