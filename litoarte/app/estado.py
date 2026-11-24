"""Conexão da interface com o banco (uma fábrica de sessões por processo)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from ..config import url_banco
from ..db import criar_engine, fabrica_sessoes, transacao
from ..migracoes import atualizar_banco

_fabrica = None
URL: str | None = None


def configurar(url: str | None = None) -> None:
    """Aplica migrações e prepara as sessões. Chamado na inicialização do app."""
    global _fabrica, URL
    URL = url or url_banco()
    atualizar_banco(URL)
    _fabrica = fabrica_sessoes(criar_engine(URL))


@contextmanager
def sessao() -> Iterator[Session]:
    """Uma transação por ação do usuário (commit ao final, rollback em erro)."""
    if _fabrica is None:
        configurar()
    with transacao(_fabrica) as s:
        yield s
