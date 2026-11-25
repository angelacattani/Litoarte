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
    await user.should_see("5 preços")
    user.find(marker="faixas-mostrar-calculados").elements.pop().value = True   # calculados ficam ocultos por padrão
    await user.should_see(marker="faixa-preco-1")
    assert [_texto(user, f"faixa-preco-{i}") for i in range(1, 6)] == \
        ["R$ 126,96", "R$ 138,40", "R$ 152,10", "R$ 168,82", "R$ 189,66"]
    _valor(user, "faixa-margem-4", "35")
    await user.should_see("alterações não salvas")
    assert _texto(user, "faixa-preco-4") == "R$ 216,37"          # 76,8128 / (1 − 0,645)
    # preço aplicado digitado e substituição pelo calculado
    _valor(user, "faixa-aplicado-1", "119,90")
    assert _texto(user, "faixa-real-1") == "6,4 %"                # 1 − 0,295 − 76,81/119,90: abaixo dos 10 %
    user.find(marker="faixa-usar-2").click()
    assert user.find(marker="faixa-aplicado-2").elements.pop().value == "138,40"
    user.find(marker="salvar-produto").click()
    await user.should_see("Produto salvo.")
    with estado.sessao() as s:
        p = s.get(Produto, pid)
        dados = {m.faixa.ordem: (m.margem_pct, m.preco_aplicado) for m in p.margens_faixas}
        assert dados == {1: (None, 119.9), 2: (None, 138.4), 4: (35.0, None)}


async def test_custo_atual_e_concorrencia(banco, user: User):
    pid = await _canvas(user)
    await user.open(f"/produtos/{pid}")
    await user.should_see("Custo atual × calculado")
    _valor(user, "prod-custo-atual", "70")
    await user.should_see("+R$ 6,81 (+9,7 %)")
    await user.should_see("Nenhum preço de concorrente para este grupo")
    from litoarte.domain.services import concorrencia
    with estado.sessao() as s:
        gid, sid = concorrencia.grupo_do_produto(s, pid)
        concorrencia.registrar(s, grupo_id=gid, subgrupo_id=sid, concorrente="Loja A", descricao="Canvas 60x90",
                               preco=149.9)
    await user.open(f"/produtos/{pid}")
    await user.should_see("Preços do subgrupo (1): mínimo R$ 149,90")
    user.find(marker="buscar-web").click()
    await user.should_see("Buscar preços de produtos similares na web")
    assert user.find(marker="busca-consulta").elements.pop().value == "Quadro Canvas 60x90"


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
