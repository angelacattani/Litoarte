"""5 preços com margens diferentes (faixas de preço) sobre o mesmo custo."""

import io

import pandas as pd
import pytest
from sqlalchemy import select

from litoarte.domain.models import FaixaPreco, Produto, ProdutoFaixa
from litoarte.domain.services import composicao as C, faixas
from litoarte.domain.services.cadastros import MODULOS, ErroValidacao, gravar, listar
from litoarte.planilhas import relatorios as R
from litoarte.planilhas.importacao import aplicar, analisar

ESPERADO = {10: 126.96, 15: 138.40, 20: 152.10, 25: 168.82, 30: 189.66}


def test_faixas_padrao_criadas_pela_migracao(sessao):
    assert [(f.ordem, f.nome, f.margem_pct) for f in faixas.listar(sessao)] == \
        [(1, "Preço 1", 10), (2, "Preço 2", 15), (3, "Preço 3", 20), (4, "Preço 4", 25), (5, "Preço 5", 30)]


def test_cinco_precos_do_canvas(sessao, canvas):
    cat = C.carregar_catalogo(sessao)
    r = C.rascunho_de_produto(sessao, canvas.id)
    pfs = C.precos_faixas(cat, r)
    assert {pf.margem_pct: round(pf.preco, 2) for pf in pfs} == ESPERADO
    for pf in pfs:          # em cada faixa o lucro é exatamente a margem da faixa
        assert pf.lucro == pytest.approx(pf.preco * pf.margem_pct / 100)
        assert not pf.propria


def test_margem_propria_do_produto_e_gravacao(sessao, canvas):
    f4 = faixas.listar(sessao)[3]
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.margens_faixas = {f4.id: 35.0}
    C.salvar(sessao, r)
    sessao.commit()
    r = C.rascunho_de_produto(sessao, canvas.id)
    assert r.margens_faixas == {f4.id: 35.0}
    pf = C.precos_faixas(C.carregar_catalogo(sessao), r)[3]
    assert pf.propria and round(pf.preco, 2) == round(76.8128 / (1 - (0.295 + 0.35)), 2)
    r.margens_faixas = {}
    C.salvar(sessao, r)
    sessao.commit()
    assert sessao.scalar(select(ProdutoFaixa)) is None


def test_margem_impossivel_e_produto_sem_custo(sessao, canvas):
    f5 = faixas.listar(sessao)[4]
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.margens_faixas = {f5.id: 71.0}                     # 14,5 + 15 + 71 > 100
    pf = C.precos_faixas(C.carregar_catalogo(sessao), r)[4]
    assert pf.preco is None and pf.lucro is None
    vazio = C.Rascunho(sku="X", nome="x", subgrupo_id=canvas.subgrupo_id)
    assert all(p.lucro is None for p in C.precos_faixas(C.carregar_catalogo(sessao), vazio))


def test_configurar_faixas(sessao, canvas):
    fs = faixas.listar(sessao)
    dados = [{"id": f.id, "ordem": f.ordem, "nome": n, "margem_pct": m}
             for f, n, m in zip(fs, ["Atacado", "Revenda", "Loja", "Varejo", "Premium"], [12, 18, 22, 28, 40])]
    faixas.salvar(sessao, dados)
    sessao.commit()
    pfs = C.precos_faixas(C.carregar_catalogo(sessao), C.rascunho_de_produto(sessao, canvas.id))
    assert [p.faixa.nome for p in pfs][0] == "Atacado" and pfs[4].margem_pct == 40
    with pytest.raises(ErroValidacao):
        faixas.salvar(sessao, [dict(dados[0], nome="Loja"), dados[2]])          # nome repetido
    with pytest.raises(ErroValidacao):
        faixas.salvar(sessao, [dict(dados[0], margem_pct=100)])


def test_clonar_copia_margens_proprias(sessao, canvas):
    f1 = faixas.listar(sessao)[0]
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.margens_faixas = {f1.id: 8.0}
    C.salvar(sessao, r)
    novo = C.clonar(sessao, canvas.id, sku="C2", nome="Cópia")
    sessao.commit()
    assert {m.faixa_id: m.margem_pct for m in novo.margens_faixas} == {f1.id: 8.0}


def test_tabela_de_precos_exporta_as_faixas(sessao, canvas):
    df = R.tabela_precos(sessao)
    linha = df.iloc[0]
    assert round(linha["Preço 1 — preço calculado"], 2) == 126.96 and linha["Preço 5 — margem (%)"] == 30
    abas = pd.read_excel(io.BytesIO(R.xlsx({"Preços": df})), sheet_name=None)
    assert "Preço 3 — preço calculado" in abas["Preços"].columns


def test_importacao_de_margens_por_faixa(sessao, canvas):
    a = analisar(sessao, "produtos", b"sku;margem_faixa_2;margem_faixa_5\nQDC-6090;17,5;45\n", "m.csv", "atualizar")
    assert a.pode_gravar
    aplicar(sessao, a)
    sessao.commit()
    p = sessao.get(Produto, canvas.id)
    por_ordem = {m.faixa.ordem: m.margem_pct for m in p.margens_faixas}
    assert por_ordem == {2: 17.5, 5: 45}
    assert listar(sessao, MODULOS["produtos"])[0]["margem_faixa_2"] == 17.5
    gravar(sessao, MODULOS["produtos"], {"sku": "QDC-6090", "margem_faixa_2": "padrao"})
    sessao.commit()
    assert {m.faixa.ordem for m in p.margens_faixas} == {5}
    a = analisar(sessao, "produtos", b"sku;margem_faixa_1\nQDC-6090;150\n", "m.csv", "atualizar")
    assert not a.pode_gravar and "entre 0 e 100" in a.linhas[0].erros[0][1]


def test_excluir_produto_remove_margens(sessao, canvas):
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.margens_faixas = {faixas.listar(sessao)[0].id: 9.0}
    C.salvar(sessao, r)
    C.excluir(sessao, canvas.id)
    sessao.commit()
    assert sessao.scalar(select(ProdutoFaixa)) is None
    assert len(sessao.scalars(select(FaixaPreco)).all()) == 5
