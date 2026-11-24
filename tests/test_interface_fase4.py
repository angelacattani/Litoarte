"""Interface da fase 4: impacto de reajuste, histórico e início."""

import pytest
from nicegui.testing import User
from sqlalchemy import select

from litoarte.app import estado
from litoarte.domain.models import Produto
from tests.conftest import carregar_canvas


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("LITOARTE_DB_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    yield


def _valor(user, marker, valor):
    for el in user.find(marker=marker).elements:
        el.value = valor


async def _preparar(user):
    await user.open("/")
    with estado.sessao() as s:
        p = carregar_canvas(s)
        s.get(Produto, p.id).preco_praticado = 160.0


async def test_reajuste_na_tela_mostra_impacto(banco, user: User):
    await _preparar(user)
    await user.open("/materias-primas")
    tabela = user.find(marker="tabela-materias_primas").elements.pop()
    tela = next(r for r in tabela.rows if r["sku"] == "TELA")
    user.find(marker="tabela-materias_primas").trigger("editar", tela)   # botão "editar" da linha
    await user.should_see("Editar — Matérias-primas (insumos)")
    _valor(user, "campo-custo_compra", "45,00")
    user.find(marker="salvar-form").click()
    await user.should_see("Impacto do reajuste nos produtos")
    impacto = user.find(marker="tabela-impacto").elements.pop()
    [linha] = impacto.rows
    assert linha["sku"] == "QDC-6090" and linha["antes"] == "R$ 152,10"
    assert linha["situacao"] == "abaixo da desejada"
    await user.should_see("1 produto(s) passam a render menos que a margem desejada")


async def test_historico_e_inicio(banco, user: User):
    await _preparar(user)
    from litoarte.domain.services import impacto
    from litoarte.domain.services.cadastros import MODULOS
    from litoarte.domain.models import MateriaPrima
    with estado.sessao() as s:
        tela = s.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
        impacto.gravar_com_impacto(s, MODULOS["materias_primas"], {"sku": "TELA", "custo_compra": 45},
                                   id_edicao=tela.id)
    await user.open("/historico")
    [linha] = user.find(marker="tabela-historico").elements.pop().rows
    assert (linha["codigo"], linha["anterior"], linha["novo"], linha["origem"]) == \
        ("TELA", "R$ 38,0000", "R$ 45,0000", "manual")
    await user.open("/")
    await user.should_see("Produtos ativos")
    await user.should_see("1 com margem abaixo da desejada")
