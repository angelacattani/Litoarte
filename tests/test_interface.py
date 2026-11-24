"""Interface (simulação de usuário do NiceGUI, sem navegador)."""

import pytest
from nicegui import ui
from nicegui.testing import User
from sqlalchemy import select

from litoarte.app import estado
from litoarte.domain.models import Configuracao, MateriaPrima, PerfilVenda


@pytest.fixture
def usuario(tmp_path, monkeypatch):
    monkeypatch.setenv("LITOARTE_DB_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    yield


def _valor(user: User, marker: str, valor):
    for el in user.find(marker=marker).elements:
        if isinstance(el, ui.select) and valor not in el.options:
            el.options.append(valor)          # equivale a digitar um valor novo (new-value-mode)
            el.update()
        el.value = valor


async def test_todas_as_paginas_abrem(usuario, user: User):
    from litoarte.app.paginas import ROTAS
    for rota in ROTAS:
        await user.open(rota)
    await user.open("/")
    await user.should_see("Primeiros passos")
    await user.should_see("Cadastrar matérias-primas")


async def test_cadastrar_materia_prima_pelo_formulario(usuario, user: User):
    await user.open("/materias-primas")
    user.find(marker="novo-materias_primas").click()
    await user.should_see("Novo — Matérias-primas (insumos)")
    _valor(user, "campo-sku", "TINTA")
    _valor(user, "campo-nome", "Tinta CMYK 1 L")
    _valor(user, "campo-unidade_compra", "frasco")
    _valor(user, "campo-unidade_consumo", "ml")
    _valor(user, "campo-fator_conversao", 1000)
    _valor(user, "campo-custo_compra", 280)
    _valor(user, "campo-fornecedor", "Insumos Gráficos")
    user.find(marker="salvar-form").click()
    await user.should_see("Registro salvo.")
    with estado.sessao() as s:
        mp = s.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TINTA"))
        assert mp.custo_consumo == pytest.approx(0.28) and mp.fornecedor.nome == "Insumos Gráficos"
    tabela = user.find(marker="tabela-materias_primas").elements.pop()
    assert [r["sku"] for r in tabela.rows] == ["TINTA"]
    assert tabela.rows[0]["custo_compra"] == "280,00"


async def test_formulario_aponta_erros(usuario, user: User):
    await user.open("/materias-primas")
    user.find(marker="novo-materias_primas").click()
    _valor(user, "campo-sku", "X")
    _valor(user, "campo-perda_pct", 150)
    user.find(marker="salvar-form").click()
    await user.should_see("Corrija os campos destacados.")
    campo = user.find(marker="campo-perda_pct").elements.pop()
    assert "menor que 100" in campo.props.get("error-message", "")
    with estado.sessao() as s:
        assert s.scalar(select(MateriaPrima)) is None


async def test_mao_de_obra_por_minuto(usuario, user: User):
    await user.open("/mao-de-obra")
    user.find(marker="novo-mao_de_obra").click()
    _valor(user, "campo-codigo", "CORTE")
    _valor(user, "campo-etapa", "Corte")
    _valor(user, "campo-custo_minuto", 0.45)
    assert user.find(marker="campo-custo_hora").elements.pop().value == "27"
    user.find(marker="salvar-form").click()
    await user.should_see("Registro salvo.")


async def test_configuracao(usuario, user: User):
    await user.open("/configuracao")
    _valor(user, "faturamento", 80000)
    _valor(user, "margem", 25)
    user.find(marker="salvar-config").click()
    await user.should_see("Configuração salva")
    with estado.sessao() as s:
        c = s.get(Configuracao, 1)
        assert (c.faturamento_base_mensal, c.margem_padrao_pct) == (80000, 25)


async def test_custos_fixos_mostra_total(usuario, user: User):
    from litoarte.domain.services.cadastros import MODULOS, gravar
    with estado.sessao() as s:
        gravar(s, MODULOS["custos_fixos"], {"codigo": "ALUG", "descricao": "Aluguel", "valor_mensal": 3500})
        gravar(s, MODULOS["custos_fixos"], {"codigo": "NET", "descricao": "Internet", "valor_mensal": 150.5})
    await user.open("/custos-fixos")
    await user.should_see("R$ 3.650,50")
    await user.should_see("defina o faturamento base")


async def test_perfil_de_venda_na_tela(usuario, user: User):
    from litoarte.domain.services.cadastros import MODULOS, gravar
    with estado.sessao() as s:
        gravar(s, MODULOS["custos_variaveis"], {"codigo": "SN", "descricao": "Simples", "tipo": "percentual",
                                                "valor": 6, "perfis": "Venda direta"})
    await user.open("/custos-variaveis")
    await user.should_see("Venda direta")
    await user.should_see("6,00 % do preço")
    caixa = user.find(kind=ui.checkbox, content="Simples").elements.pop()
    caixa.value = False
    with estado.sessao() as s:
        assert s.scalar(select(PerfilVenda).where(PerfilVenda.padrao)).custos == []


async def test_dialogo_de_importacao_abre(usuario, user: User):
    await user.open("/custos-fixos")
    user.find("Importar").click()
    await user.should_see("Importar — Custos fixos")
    await user.should_see("Nada é gravado antes da confirmação.", retries=5)


async def test_campo_numerico_aceita_virgula(usuario, user: User):
    """Regressão: no navegador pt-BR, '139,90' em <input type=number> virava 13990."""
    await user.open("/custos-fixos")
    user.find(marker="novo-custos_fixos").click()
    _valor(user, "campo-codigo", "NET")
    _valor(user, "campo-descricao", "Internet")
    _valor(user, "campo-valor_mensal", "1.234,56")
    user.find(marker="salvar-form").click()
    await user.should_see("Registro salvo.")
    from litoarte.domain.models import CustoFixo
    with estado.sessao() as s:
        assert s.scalar(select(CustoFixo)).valor_mensal == pytest.approx(1234.56)
