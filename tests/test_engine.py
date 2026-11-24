"""Motor de precificação (puro) — fórmulas da seção 3 da especificação."""

import pytest

from litoarte.domain.pricing import (EntradaProduto, ItemCustoVariavel, LinhaMaoObra, LinhaMaterial, MetodoRateio,
                                     ModoPerda, ModoQtd, RegrasEmpresa, calcular, pecas_por_folha)
from litoarte.domain.pricing.engine import fator_perda

CV_DIRETA = (ItemCustoVariavel("SN", "Simples", "percentual", 6.0),
             ItemCustoVariavel("CART", "Cartão", "percentual", 3.5),
             ItemCustoVariavel("COM", "Comissão", "percentual", 5.0))

REGRAS = RegrasEmpresa(custo_fixo_total=12_000, metodo_rateio=MetodoRateio.PCT_FATURAMENTO,
                       faturamento_base=80_000, margem_padrao_pct=20.0)


def canvas(**kw) -> EntradaProduto:
    base = dict(
        sku="QDC-6090", largura_cm=60, altura_cm=90, custos_variaveis=CV_DIRETA,
        materiais=(
            LinhaMaterial("TELA", "Tela canvas", 38.0, 1, 10, modo_qtd=ModoQtd.AREA),
            LinhaMaterial("CHASSI", "Chassi", 9.5, 1, 5, modo_qtd=ModoQtd.PERIMETRO),
            LinhaMaterial("TINTA", "Tinta", 280.0, 12 * 0.8, 10, fator_conversao=1000, modo_qtd=ModoQtd.AREA),
            LinhaMaterial("GANCHO", "Gancho", 1.2, 2),
            LinhaMaterial("CAIXA", "Caixa", 6.5, 1),
        ),
        mao_de_obra=(LinhaMaoObra("IMP", "Impressão", 27.0, 6 / 60),
                     LinhaMaoObra("MON", "Montagem", 24.0, 20 / 60),
                     LinhaMaoObra("ACA", "Acabamento", 21.0, 8 / 60)),
    )
    base.update(kw)
    return EntradaProduto(**base)


# --------------------------------------------------------------- exemplo de aceite (3.9)
def test_exemplo_canvas_custos():
    r = calcular(canvas(), REGRAS)
    custos = {m.linha.sku: m.custo for m in r.materiais}
    assert custos["TELA"] == pytest.approx(0.54 / 0.90 * 38.0)
    assert custos["CHASSI"] == pytest.approx(3.0 / 0.95 * 9.5)
    assert custos["TINTA"] == pytest.approx(0.54 * 9.6 / 0.90 * 0.28)
    assert r.mp == pytest.approx(63.3128, abs=1e-4)
    assert r.mo == pytest.approx(13.50)
    assert r.cd == pytest.approx(76.8128, abs=1e-4)


def test_exemplo_canvas_preco():
    r = calcular(canvas(), REGRAS)
    assert r.pct_cf == pytest.approx(15.0)
    assert r.pct_cv == pytest.approx(14.5)
    assert r.markup_divisor == pytest.approx(0.505)
    assert round(r.preco, 2) == 152.10
    assert round(r.markup, 3) == 1.980
    # conferência: as parcelas somam o preço e o lucro é exatamente %ML do preço
    assert r.cd + r.parcela_cf + r.parcela_cv + r.lucro == pytest.approx(r.preco)
    assert round(r.lucro, 2) == 30.42
    assert round(r.preco_minimo, 2) == 108.95
    assert round(r.preco_cobertura, 2) == 89.84


def test_exemplo_canvas_simulador():
    s = calcular(canvas(), REGRAS).simular(139.90)
    assert round(s.margem_pct, 2) == 15.59
    assert round(s.lucro, 2) == 21.82
    assert round(s.margem_contribuicao, 2) == 42.80
    assert round(s.margem_contribuicao_pct, 1) == 30.6
    assert s.ponto_equilibrio_un == 281


def test_exemplo_canvas_rateio_por_hora():
    regras = RegrasEmpresa(custo_fixo_total=12_000, metodo_rateio=MetodoRateio.HORA_PRODUTIVA,
                           capacidade_horas=3 * 160 * 0.85, margem_padrao_pct=20.0)
    r = calcular(canvas(), regras)
    assert r.pct_cf == 0
    assert r.cf_unit == pytest.approx(12_000 / 408 * 34 / 60)
    assert round(r.preco, 2) == 142.72


# --------------------------------------------------------------- propriedades do markup
def test_margem_no_preco_sugerido_e_exata():
    r = calcular(canvas(), REGRAS)
    assert r.simular(r.preco).margem_pct == pytest.approx(20.0)
    assert r.simular(r.preco_minimo).lucro == pytest.approx(0, abs=1e-9)
    assert r.simular(r.preco_cobertura).margem_contribuicao == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("margem", [0, 5, 12.5, 30, 50])
def test_preco_e_margem_sao_inversos(margem):
    r = calcular(canvas(), REGRAS)
    assert r.simular(r.preco_para_margem(margem)).margem_pct == pytest.approx(margem)


def test_margem_do_produto_sobrepoe_padrao():
    assert calcular(canvas(margem_pct=35), REGRAS).pct_ml == 35


def test_preco_indefinido_quando_percentuais_somam_100():
    r = calcular(canvas(margem_pct=71), REGRAS)               # 14,5 + 15 + 71 = 100,5 %
    assert r.preco is None and r.markup is None
    assert r.margem_maxima_pct == pytest.approx(70.5)
    assert any("indefinido" in a for a in r.alertas)
    assert r.preco_para_margem(71) is None


def test_custo_variavel_em_reais_vai_ao_numerador():
    frete = ItemCustoVariavel("FRT", "Frete", "valor_fixo", 12.0)
    r = calcular(canvas(custos_variaveis=CV_DIRETA + (frete,)), REGRAS)
    assert r.cv_fixo == 12.0
    assert r.preco == pytest.approx((r.cd + 12.0) / 0.505)
    assert r.simular(r.preco).margem_pct == pytest.approx(20.0)


def test_rateio_por_unidade():
    regras = RegrasEmpresa(custo_fixo_total=12_000, metodo_rateio=MetodoRateio.UNIDADE, capacidade_unidades=600)
    r = calcular(canvas(), regras)
    assert r.cf_unit == pytest.approx(20.0)
    assert r.preco == pytest.approx((r.cd + 20) / (1 - (14.5 + 20) / 100))


@pytest.mark.parametrize("regras", [
    RegrasEmpresa(12_000, MetodoRateio.PCT_FATURAMENTO),
    RegrasEmpresa(12_000, MetodoRateio.HORA_PRODUTIVA),
    RegrasEmpresa(12_000, MetodoRateio.UNIDADE),
])
def test_base_de_rateio_ausente_alerta(regras):
    r = calcular(canvas(), regras)
    assert r.pct_cf == 0 and r.cf_unit == 0
    assert any("custo fixo fora do preço" in a for a in r.alertas)


# --------------------------------------------------------------- perda parametrizável
def test_fator_perda_modos():
    assert fator_perda(10, ModoPerda.SOBRE_COMPRA) == pytest.approx(1 / 0.9)
    assert fator_perda(10, ModoPerda.ACRESCIMO) == pytest.approx(1.1)
    with pytest.raises(ValueError):
        fator_perda(100, ModoPerda.SOBRE_COMPRA)


def test_modo_perda_acrescimo_no_produto():
    regras = RegrasEmpresa(12_000, MetodoRateio.PCT_FATURAMENTO, faturamento_base=80_000,
                           modo_perda=ModoPerda.ACRESCIMO)
    r = calcular(canvas(), regras)
    tela = next(m for m in r.materiais if m.linha.sku == "TELA")
    assert tela.custo == pytest.approx(0.54 * 1.10 * 38.0)
    assert r.mp < calcular(canvas(), REGRAS).mp


# --------------------------------------------------------------- quantidade por dimensões
def test_produto_sem_dimensoes():
    r = calcular(canvas(largura_cm=None, altura_cm=None), REGRAS)
    assert sum(1 for a in r.alertas if "sem dimensões" in a) == 3   # tela, chassi, tinta
    assert r.mp == pytest.approx(2 * 1.2 + 6.5)                      # só itens fixos


def test_aproveitamento_folha_1x2_recorte_15x15():
    papel = LinhaMaterial("PAP", "Papel 1×2 m", 18.0, 1, 5, modo_qtd=ModoQtd.APROVEITAMENTO,
                          unidade_consumo="folha", folha_largura_m=1.0, folha_comprimento_m=2.0)
    r = calcular(EntradaProduto("REC", (papel,), largura_cm=15, altura_cm=15), REGRAS)
    m = r.materiais[0]
    assert m.pecas_folha == 78 and m.aproveitamento_pct == pytest.approx(87.75)
    assert m.custo == pytest.approx(18.0 / 78 / 0.95)


def test_aproveitamento_sem_dimensao_de_folha_e_peca_grande():
    sem_folha = LinhaMaterial("PAP", "Papel", 18.0, 1, modo_qtd=ModoQtd.APROVEITAMENTO)
    grande = LinhaMaterial("PAP2", "Papel", 18.0, 1, modo_qtd=ModoQtd.APROVEITAMENTO,
                           folha_largura_m=1.0, folha_comprimento_m=2.0)
    r = calcular(EntradaProduto("X", (sem_folha, grande), largura_cm=120, altura_cm=250), REGRAS)
    assert any("sem dimensões de folha" in a for a in r.alertas)
    assert any("não cabe" in a for a in r.alertas)
    assert r.mp == 0


def test_ficha_vazia_e_preco_praticado():
    r = calcular(EntradaProduto("V"), REGRAS)
    assert "ficha técnica vazia" in r.alertas
    r = calcular(canvas(preco_praticado=100.0), REGRAS)
    assert any("gera prejuízo" in a for a in r.alertas)
    assert any("rende" in a for a in r.alertas)


# --------------------------------------------------------------- encaixe
@pytest.mark.parametrize("args,pecas", [
    ((100, 200, 15, 15), 78), ((100, 200, 15, 15, 1.0), 72), ((100, 200, 15, 15, 0, 3.0), 72),
    ((100, 200, 15, 20), 65), ((100, 200, 20, 30), 33), ((100, 200, 120, 10), 10), ((100, 200, 120, 250), 0),
])
def test_pecas_por_folha(args, pecas):
    assert pecas_por_folha(*args).pecas == pecas
