"""Composição de preço: rascunho, cálculo em tempo real, gravação, clonagem, canais e lista."""

import pytest
from sqlalchemy import func, select

from litoarte.domain.models import CustoVariavel, FichaMP, MateriaPrima, PerfilVenda, Produto
from litoarte.domain.services import composicao as C, perfis
from litoarte.domain.services.cadastros import ErroValidacao
from litoarte.domain.services.precificacao import calcular_produto


def _ids(sessao):
    return {m.sku: m.id for m in sessao.scalars(select(MateriaPrima))}


def test_rascunho_reproduz_o_preco_do_banco(sessao, canvas):
    cat = C.carregar_catalogo(sessao)
    r = C.rascunho_de_produto(sessao, canvas.id)
    res = C.calcular_rascunho(cat, r)
    assert round(res.preco, 2) == 152.10
    assert res.preco == pytest.approx(calcular_produto(sessao, canvas.id).preco)


def test_alteracao_recalcula_sem_gravar(sessao, canvas):
    cat = C.carregar_catalogo(sessao)
    r = C.rascunho_de_produto(sessao, canvas.id)
    antes = C.calcular_rascunho(cat, r).preco
    r.largura_cm, r.altura_cm = 40, 60                      # menor: área e perímetro caem
    depois = C.calcular_rascunho(cat, r).preco
    assert depois < antes
    assert sessao.get(Produto, canvas.id).largura_cm == 60  # nada gravado
    r.materiais.append(C.LinhaMat())                        # linha nova, ainda vazia
    res = C.calcular_rascunho(cat, r)
    assert res.preco == pytest.approx(depois)
    assert any("incompleta" in a for a in res.alertas)


def test_simular_outra_margem_sem_mudar_rascunho(sessao, canvas):
    cat = C.carregar_catalogo(sessao)
    r = C.rascunho_de_produto(sessao, canvas.id)
    res = C.calcular_rascunho(cat, r, margem_pct=30)
    assert res.pct_ml == 30 and res.simular(res.preco).margem_pct == pytest.approx(30)
    assert r.margem_desejada_pct is None


def test_salvar_novo_produto_com_ficha(sessao, canvas):
    ids = _ids(sessao)
    r = C.Rascunho(sku="QDC-4060", nome="Quadro Canvas 40×60", subgrupo_id=canvas.subgrupo_id,
                   largura_cm=40, altura_cm=60, preco_praticado=79.9,
                   materiais=[C.LinhaMat(ids["TELA"], "area", 1), C.LinhaMat(ids["CAIXA"], "fixa", 1, perda_pct=0)],
                   mao_de_obra=[C.LinhaMO(canvas.mao_de_obra[1].mao_de_obra_id, 15, "min")])
    p = C.salvar(sessao, r)
    sessao.commit()
    assert r.id == p.id and len(p.materiais) == 2 and p.mao_de_obra[0].tempo == 15
    assert calcular_produto(sessao, p.id).mp == pytest.approx(0.24 / 0.9 * 38 + 6.5)


def test_salvar_substitui_linhas_da_ficha(sessao, canvas):
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.materiais = r.materiais[:2]
    r.mao_de_obra[0].tempo = 10
    C.salvar(sessao, r)
    sessao.commit()
    assert sessao.scalar(select(func.count()).select_from(FichaMP)) == 2
    assert calcular_produto(sessao, canvas.id).mo == pytest.approx((10 * 0.45) + 8.0 + 2.8)


def test_validacao_aponta_cabecalho_e_linhas(sessao, canvas):
    r = C.Rascunho(sku="QDC-6090", nome="", largura_cm=-1, margem_desejada_pct=100,
                   materiais=[C.LinhaMat(None, "area", None)], mao_de_obra=[C.LinhaMO(None, -2)])
    with pytest.raises(ErroValidacao) as e:
        C.salvar(sessao, r)
    campos = {c for c, _ in e.value.erros}
    assert {"sku", "nome", "subgrupo_id", "largura_cm", "margem_desejada_pct", "material 1",
            "mão de obra 1"} <= campos


def test_clonar_herda_ficha_e_configuracoes(sessao, canvas):
    mkt = perfis.criar(sessao, "Marketplace")
    p = sessao.get(Produto, canvas.id)
    p.perfil_venda_id, p.margem_desejada_pct, p.preco_praticado = mkt.id, 25, 139.9
    sessao.commit()
    sku = C.sugerir_sku(sessao, "QDC-6090")
    assert sku == "QDC-6090-C1"
    novo = C.clonar(sessao, canvas.id, sku=sku, nome="Quadro Canvas 50×70", largura_cm=50, altura_cm=70)
    sessao.commit()
    assert (novo.subgrupo_id, novo.perfil_venda_id, novo.margem_desejada_pct, novo.preco_praticado,
            novo.clonado_de_id) == (canvas.subgrupo_id, mkt.id, 25, None, canvas.id)
    assert [f.materia_prima.sku for f in novo.materiais] == [f.materia_prima.sku for f in canvas.materiais]
    assert len(novo.mao_de_obra) == 3
    assert C.sugerir_sku(sessao, "QDC-6090-C1") == "QDC-6090-C2"
    # a origem não muda e as fichas são independentes
    novo.materiais[0].quantidade = 2
    sessao.commit()
    assert sessao.get(Produto, canvas.id).materiais[0].quantidade == 1
    assert calcular_produto(sessao, novo.id).cd < calcular_produto(sessao, canvas.id).cd * 1.5


def test_clonar_sem_ficha(sessao, canvas):
    novo = C.clonar(sessao, canvas.id, sku="X", nome="Vazio", copiar_materiais=False, copiar_mao_de_obra=False,
                    copiar_perfil_margem=False)
    assert novo.materiais == [] and novo.mao_de_obra == [] and novo.perfil_venda_id is None


def test_comparar_canais(sessao, canvas):
    direta = sessao.scalar(select(PerfilVenda).where(PerfilVenda.padrao))
    mkt = perfis.criar(sessao, "Marketplace", copiar_de=direta.id)
    extra = CustoVariavel(codigo="MKT", descricao="Comissão", categoria="marketplace", valor=16)
    frete = CustoVariavel(codigo="FRT", descricao="Frete", categoria="frete", tipo="valor_fixo", valor=12)
    sessao.add_all([extra, frete])
    sessao.flush()
    perfis.definir_custo(sessao, mkt.id, extra.id, True)
    perfis.definir_custo(sessao, mkt.id, frete.id, True)
    sessao.get(Produto, canvas.id).preco_praticado = 139.9
    sessao.commit()
    cat = C.carregar_catalogo(sessao)
    canais = {c.nome: c for c in C.comparar_canais(cat, C.rascunho_de_produto(sessao, canvas.id))}
    assert canais["Venda direta"].atual and round(canais["Venda direta"].resultado.preco, 2) == 152.10
    m = canais["Marketplace"].resultado
    assert m.pct_cv == pytest.approx(30.5) and m.cv_fixo == 12
    assert m.preco == pytest.approx((76.8128 + 12) / (1 - 0.655), rel=1e-5)
    assert canais["Marketplace"].margem_no_praticado < canais["Venda direta"].margem_no_praticado


def test_resumo_da_lista(sessao, canvas):
    sessao.get(Produto, canvas.id).preco_praticado = 139.9
    sessao.commit()
    [r] = C.resumo_produtos(sessao)
    assert r.grupo == "QDR - Quadros" and round(r.preco_sugerido, 2) == 152.10
    assert round(r.margem_praticada, 2) == 15.59 and r.abaixo_da_margem


def test_excluir_produto(sessao, canvas):
    C.excluir(sessao, canvas.id)
    sessao.commit()
    assert sessao.scalar(select(func.count()).select_from(Produto)) == 0
    assert sessao.scalar(select(func.count()).select_from(MateriaPrima)) == 5
