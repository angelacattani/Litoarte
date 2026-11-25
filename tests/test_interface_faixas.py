"""Interface: 5 preços por margem na composição e configuração das faixas."""

import pytest
from nicegui.testing import User
from sqlalchemy import select

from litoarte.app import estado
from litoarte.domain.models import FaixaPreco, Produto
from tests.conftest import carregar_canvas


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("LITOARTE_DB_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    yield


def _valor(user, marker, valor):
    for el in user.find(marker=marker).elements:
        el.value = valor


def _texto(user, marker):
    return user.find(marker=marker).elements.pop().text


async def _canvas(user):
    await user.open("/")
    with estado.sessao() as s:
        return carregar_canvas(s).id


async def test_cinco_precos_na_composicao(banco, user: User):
    pid = await _canvas(user)
    await user.open(f"/produtos/{pid}")
    await user.should_see("5 preços por margem")
    assert [_texto(user, f"faixa-preco-{i}") for i in range(1, 6)] == \
        ["R$ 126,96", "R$ 138,40", "R$ 152,10", "R$ 168,82", "R$ 189,66"]
    _valor(user, "faixa-margem-4", "35")
    await user.should_see("alterações não salvas")
    assert _texto(user, "faixa-preco-4") == "R$ 216,37"          # 76,8128 / (1 − 0,645)
    user.find(marker="salvar-produto").click()
    await user.should_see("Produto salvo.")
    with estado.sessao() as s:
        p = s.get(Produto, pid)
        assert [(m.faixa.ordem, m.margem_pct) for m in p.margens_faixas] == [(4, 35.0)]


async def test_configurar_faixas(banco, user: User):
    await _canvas(user)
    await user.open("/configuracao")
    _valor(user, "cfg-faixa-nome-1", "Atacado")
    _valor(user, "cfg-faixa-margem-1", "12,5")
    user.find(marker="salvar-faixas").click()
    await user.should_see("Faixas de preço salvas.")
    with estado.sessao() as s:
        f = s.scalar(select(FaixaPreco).where(FaixaPreco.ordem == 1))
        assert (f.nome, f.margem_pct) == ("Atacado", 12.5)
