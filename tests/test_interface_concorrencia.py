"""Interface: busca de preços na web (simulada), concorrentes, credenciais e substituição de preços."""

import pytest
from nicegui import ui
from nicegui.testing import User
from sqlalchemy import select

from litoarte.app import estado
from litoarte.busca import ResultadoBusca
from litoarte.domain.models import Configuracao, PrecoConcorrente
from litoarte.domain.services import composicao as C, concorrencia
from tests.conftest import carregar_canvas


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("LITOARTE_DB_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    yield


def _valor(user, marker, valor):
    for el in user.find(marker=marker).elements:
        el.value = valor


async def _canvas(user):
    await user.open("/")
    with estado.sessao() as s:
        return carregar_canvas(s).id


RESULTADOS = [ResultadoBusca("Quadro Canvas 60x90 Mar", 159.9, "LOJA A (Mercado Livre)", "https://ml/1", "mercadolivre"),
              ResultadoBusca("Quadro Canvas 60x90 Flores", 139.0, "LOJA B (Mercado Livre)", "https://ml/2", "mercadolivre")]


async def test_busca_web_e_gravacao_dos_selecionados(banco, user: User, monkeypatch):
    chamadas = []

    def falsa(cred, fonte, consulta, limite=30, **kw):
        chamadas.append((fonte, consulta))
        return RESULTADOS, None
    monkeypatch.setattr(concorrencia, "buscar_web", falsa)
    pid = await _canvas(user)
    await user.open(f"/produtos/{pid}")
    user.find(marker="buscar-web").click()
    await user.should_see("Buscar preços de produtos similares na web")
    user.find(marker="busca-executar").click()
    await user.should_see(marker="busca-resultados")
    assert chamadas == [("mercadolivre", "Quadro Canvas 60x90")]
    tabela = user.find(marker="busca-resultados").elements.pop()
    assert [r["preco"] for r in tabela.rows] == ["R$ 159,90", "R$ 139,00"]
    tabela.selected = [tabela.rows[1]]
    user.find(marker="busca-resultados").trigger("selection", {"rows": [tabela.rows[1]], "keys": [1],
                                                                "added": True})
    await user.should_see("Gravar 1 selecionado(s)")
    user.find(marker="busca-gravar").click()
    await user.should_see("1 preço(s) de concorrentes gravado(s).")
    with estado.sessao() as s:
        pc = s.scalar(select(PrecoConcorrente))
        assert (pc.preco, pc.fonte, pc.produto_id, pc.concorrente.nome) == (139.0, "mercadolivre", pid,
                                                                            "LOJA B (Mercado Livre)")
    await user.should_see("Preços deste produto (1)")


async def test_pagina_concorrentes_e_credenciais(banco, user: User):
    await _canvas(user)
    await user.open("/concorrentes")
    await user.should_see("Preços coletados")
    user.find(marker="concorrentes-buscar").click()
    await user.should_see("Grupo dos preços *")
    await user.open("/configuracao")
    await user.should_see("Busca de preços na web")
    for el in user.find(kind=ui.input).elements:
        if el.props.get("label") == "Mercado Livre — Client ID":
            el.value = "123"
        if el.props.get("label") == "SerpApi — chave (Google Shopping)":
            el.value = "chave-serp"
    user.find(marker="salvar-credenciais").click()
    await user.should_see("Credenciais de busca salvas.")
    with estado.sessao() as s:
        c = s.get(Configuracao, 1)
        assert (c.ml_client_id, c.serpapi_chave) == ("123", "chave-serp")


async def test_substituir_precos_na_lista(banco, user: User):
    pid = await _canvas(user)
    await user.open("/produtos")
    user.find(marker="substituir-precos").click()
    await user.should_see("Substituir preços aplicados — 1 produto(s) da lista")
    _valor(user, "subst-faixa-3", True)
    user.find(marker="subst-previa").click()
    await user.should_see(marker="subst-tabela")
    [linha] = user.find(marker="subst-tabela").elements.pop().rows
    assert (linha["faixa"], linha["antes"], linha["depois"]) == ("Preço 3", "—", "R$ 152,90")
    user.find(marker="subst-confirmar").click()
    await user.should_see("1 preço(s) substituído(s).")
    with estado.sessao() as s:
        assert list(C.rascunho_de_produto(s, pid).precos_aplicados.values()) == [152.9]
