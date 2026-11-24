"""Conexão com o banco e fábrica de sessões."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import url_banco


def criar_engine(url: str | None = None, **kwargs) -> Engine:
    url = url or url_banco()
    engine = create_engine(url, future=True, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_con, _):  # noqa: ANN001
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA foreign_keys = ON")   # SQLite não impõe FKs sem isto
            cur.close()
    return engine


def fabrica_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def transacao(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão com commit ao final ou rollback em caso de erro (tudo-ou-nada)."""
    sessao = fabrica()
    try:
        yield sessao
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()
