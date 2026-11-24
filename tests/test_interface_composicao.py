"""Interface da fase 3: lista de produtos, composição em tempo real, simulador e clonagem."""

import pytest
from nicegui.testing import User
from sqlalchemy import select

from litoarte.app import estado
from litoarte.domain.models import MateriaPrima, Produto
from litoarte.domain.services import composicao as C
from tests.conftest import carregar_canvas


@pytest.fixture
def canvas_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("LITOARTE_DB_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    yield


async def _abrir_com_canvas(user: User, rota_fn):
    await user.open("/")                      # inicializa o banco do teste
    with estado.sessao() as s:
        pid = carregar_canvas(s).id
    await user.open(rota_fn(pid))
    return pid


def _valor(user, marker, valor):
    for el in user.find(marker=marker).elements:
        el.value = valor


async def test_lista_de_produtos(canvas_ui, user: User):
    await _abrir_com_canvas(user, lambda pid: "/produtos")
    tabela = user.find(marker="tabela-produtos").elements.pop()
    [linha] = tabela.rows
    assert (linha["sku"], linha["sugerido"], linha["situacao"]) == ("QDC-6090", "R$ 152,10", "sem")


async def test_composicao_recalcula_em_tempo_real_e_salva(canvas_ui, user: User):
    pid = await _abrir_com_canvas(user, lambda pid: f"/produtos/{pid}")
    await user.should_see("R$ 152,10")
    await user.should_see("Formação do preço")
    _valor(user, "prod-largura", 40)
    _valor(user, "prod-altura", 60)
    with estado.sessao() as s:
        cat = C.carregar_catalogo(s)
        r = C.rascunho_de_produto(s, pid)
    r.largura_cm, r.altura_cm = 40, 60
    esperado = C.calcular_rascunho(cat, r).preco
    rotulo = "R$ " + f"{esperado:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    await user.should_see(rotulo)
    await user.should_see("alterações não salvas")
    with estado.sessao() as s:
        assert s.get(Produto, pid).largura_cm == 60          # ainda não gravou
    user.find(marker="salvar-produto").click()
    await user.should_see("Produto salvo.")
    with estado.sessao() as s:
        assert s.get(Produto, pid).largura_cm == 40


async def test_simulador_preco_manual(canvas_ui, user: User):
    await _abrir_com_canvas(user, lambda pid: f"/produtos/{pid}")
    _valor(user, "sim-preco", 139.90)
    await user.should_see("Lucro líquido R$ 21,82 · 15,59 %")
    await user.should_see("Ponto de equilíbrio: 281 un/mês")


async def test_duplicar_produto(canvas_ui, user: User):
    pid = await _abrir_com_canvas(user, lambda pid: f"/produtos/{pid}")
    user.find(marker="duplicar").click()
    await user.should_see("Duplicar “QDC-6090")
    _valor(user, "clone-sku", "QDC-5070")
    _valor(user, "clone-nome", "Quadro Canvas 50×70")
    user.find(marker="clone-confirmar").click()
    await user.should_see("Produto duplicado.")
    with estado.sessao() as s:
        novo = s.scalar(select(Produto).where(Produto.sku == "QDC-5070"))
        assert novo.clonado_de_id == pid and len(novo.materiais) == 5 and len(novo.mao_de_obra) == 3


async def test_novo_produto_e_validacao(canvas_ui, user: User):
    await _abrir_com_canvas(user, lambda pid: "/produtos/novo")
    await user.should_see("Novo produto")
    user.find(marker="salvar-produto").click()
    await user.should_see("Não foi possível salvar")
    _valor(user, "prod-sku", "CX-AVULSA")
    _valor(user, "prod-nome", "Caixa avulsa")
    user.find(marker="add-material").click()
    await user.should_see(marker="mat-insumo-0")          # o redesenho da ficha é assíncrono
    with estado.sessao() as s:
        caixa = s.scalar(select(MateriaPrima).where(MateriaPrima.sku == "CAIXA")).id
    _valor(user, "mat-insumo-0", caixa)
    await user.should_see(marker="mat-qtd-0")
    _valor(user, "mat-qtd-0", 2)
    await user.should_see("R$ 13,0000")                       # custo da linha: 2 × 6,50
    user.find(marker="salvar-produto").click()
    await user.should_see("Produto salvo.")
    with estado.sessao() as s:
        p = s.scalar(select(Produto).where(Produto.sku == "CX-AVULSA"))
        assert p.materiais[0].quantidade == 2


async def test_simulador_aceita_preco_com_virgula(canvas_ui, user: User):
    await _abrir_com_canvas(user, lambda pid: f"/produtos/{pid}")
    _valor(user, "sim-preco", "139,90")
    await user.should_see("Resultado: R$ 139,90")
    await user.should_see("Lucro líquido R$ 21,82 · 15,59 %")
