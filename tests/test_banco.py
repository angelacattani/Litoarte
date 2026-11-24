"""Schema, integridade referencial, histórico e cálculo a partir do banco."""

import pytest
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.exc import IntegrityError

from litoarte.db import criar_engine
from litoarte.domain.models import (Configuracao, CustoFixo, FichaMP, HistoricoCustoMO, HistoricoCustoMP, MaoDeObra,
                                    MateriaPrima, PerfilVenda, Produto, Subgrupo, UnidadeMedida)
from litoarte.domain.services.precificacao import (calcular_produto, calcular_todos, produtos_que_usam_etapa,
                                                   produtos_que_usam_insumo, regras_empresa)
from litoarte.migracoes import atualizar_banco
from tests.conftest import un


# --------------------------------------------------------------- migrações
def test_migracao_cria_schema_e_dados_de_referencia(url, sessao):
    tabelas = set(sa_inspect(criar_engine(url)).get_table_names())
    assert {"materia_prima", "mao_de_obra", "custo_fixo", "custo_variavel", "perfil_venda", "perfil_venda_item",
            "grupo", "subgrupo", "produto", "ficha_mp", "ficha_mo", "configuracao", "historico_custo_mp",
            "historico_custo_mo", "unidade_medida", "fornecedor", "importacao_log"} <= tabelas
    assert sessao.get(Configuracao, 1).modo_perda == "sobre_compra"
    assert sessao.scalar(select(PerfilVenda).where(PerfilVenda.padrao)).nome == "Venda direta"
    assert un(sessao, "ml").grandeza == "volume"
    assert sessao.scalar(select(Produto)) is None            # começa sem dados de negócio
    atualizar_banco(url)                                      # idempotente


# --------------------------------------------------------------- exemplo de aceite pelo banco
def test_canvas_calculado_do_banco(sessao, canvas):
    r = calcular_produto(sessao, canvas.id)
    assert round(r.cd, 2) == 76.81
    assert round(r.preco, 2) == 152.10
    assert r.simular(139.90).ponto_equilibrio_un == 281


def test_modo_perda_parametrizavel_no_banco(sessao, canvas):
    sobre = calcular_produto(sessao, canvas.id).mp
    sessao.get(Configuracao, 1).modo_perda = "acrescimo"
    sessao.commit()
    acres = calcular_produto(sessao, canvas.id)
    tela = next(m for m in acres.materiais if m.linha.sku == "TELA")
    assert tela.custo == pytest.approx(0.54 * 1.10 * 38.0)
    assert acres.mp < sobre


def test_perda_da_linha_sobrepoe_cadastro(sessao, canvas):
    linha = next(f for f in canvas.materiais if f.materia_prima.sku == "TELA")
    linha.perda_pct = 20
    sessao.commit()
    tela = next(m for m in calcular_produto(sessao, canvas.id).materiais if m.linha.sku == "TELA")
    assert tela.custo == pytest.approx(0.54 / 0.80 * 38.0)


# --------------------------------------------------------------- cascata
def test_reajuste_de_insumo_recalcula_e_grava_historico(sessao, canvas):
    antes = calcular_produto(sessao, canvas.id).preco
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    tela.custo_compra = 45.0
    tela.origem_alteracao = "importacao"
    sessao.commit()
    depois = calcular_produto(sessao, canvas.id).preco
    assert depois == pytest.approx(antes + 0.54 / 0.90 * 7.0 / 0.505)
    h = sessao.scalars(select(HistoricoCustoMP)).all()
    assert [(x.custo_anterior, x.custo_novo, x.origem) for x in h] == [(38.0, 45.0, "importacao")]
    assert [p.sku for p in produtos_que_usam_insumo(sessao, tela.id)] == ["QDC-6090"]


def test_reajuste_de_mao_de_obra_grava_historico(sessao, canvas):
    mon = sessao.scalar(select(MaoDeObra).where(MaoDeObra.codigo == "MON"))
    mon.custo_hora_informado = 30.0
    mon.etapa = "Montagem e colagem"        # mudança que não altera custo não gera histórico extra
    sessao.commit()
    mon.etapa = "Montagem"
    sessao.commit()
    h = sessao.scalars(select(HistoricoCustoMO)).all()
    assert len(h) == 1 and h[0].custo_hora_anterior == pytest.approx(24.0) and h[0].custo_hora_novo == 30.0
    assert calcular_produto(sessao, canvas.id).mo == pytest.approx(13.50 + 20 / 60 * 6.0)
    assert [p.sku for p in produtos_que_usam_etapa(sessao, mon.id)] == ["QDC-6090"]


def test_custo_fixo_inativo_sai_do_rateio(sessao, canvas):
    sessao.scalar(select(CustoFixo).where(CustoFixo.codigo == "ALUG")).ativo = False
    sessao.commit()
    assert regras_empresa(sessao).custo_fixo_total == 5000
    assert calcular_produto(sessao, canvas.id).pct_cf == pytest.approx(5000 / 80_000 * 100)


def test_mao_de_obra_calculada_e_capacidade_padrao(sessao, canvas):
    sessao.add(MaoDeObra(codigo="COST", etapa="Costura", modo_custo="calculado", salario_mensal=2000,
                         encargos_pct=70, horas_produtivas_mes=160, qtd_colaboradores=2))
    sessao.commit()
    mo = sessao.scalar(select(MaoDeObra).where(MaoDeObra.codigo == "COST"))
    assert mo.custo_hora == pytest.approx(2000 * 1.7 / 160)
    assert mo.custo_minuto == pytest.approx(mo.custo_hora / 60)
    assert regras_empresa(sessao).capacidade_horas == pytest.approx(320)   # soma das etapas com horas


def test_calcular_todos(sessao, canvas):
    res = calcular_todos(sessao)
    assert [(p.sku, round(r.preco, 2)) for p, r in res] == [("QDC-6090", 152.10)]


# --------------------------------------------------------------- integridade
def _falha(sessao, fn):
    with pytest.raises(IntegrityError):
        fn()
        sessao.flush()
    sessao.rollback()


def test_sku_unico(sessao, canvas):
    m = un(sessao, "un")
    _falha(sessao, lambda: sessao.add(MateriaPrima(sku="TELA", nome="dup", unidade_compra=m, unidade_consumo=m,
                                                   custo_compra=1)))


def test_insumo_em_uso_nao_pode_ser_apagado(sessao, canvas):
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    _falha(sessao, lambda: sessao.delete(tela))


def test_excluir_produto_remove_a_ficha(sessao, canvas):
    sessao.delete(sessao.get(Produto, canvas.id))
    sessao.commit()
    assert sessao.scalar(select(FichaMP)) is None
    assert sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA")) is not None


def test_subgrupo_em_uso_nao_pode_ser_apagado(sessao, canvas):
    _falha(sessao, lambda: sessao.delete(sessao.scalar(select(Subgrupo))))


@pytest.mark.parametrize("campo,valor", [("perda_pct", 100), ("perda_pct", -1), ("fator_conversao", 0),
                                         ("custo_compra", -5)])
def test_checks_de_insumo(sessao, campo, valor):
    m = un(sessao, "un")
    dados = dict(sku="X", nome="x", unidade_compra=m, unidade_consumo=m, custo_compra=1)
    dados[campo] = valor
    _falha(sessao, lambda: sessao.add(MateriaPrima(**dados)))


def test_mao_de_obra_exige_dados_do_modo(sessao):
    _falha(sessao, lambda: sessao.add(MaoDeObra(codigo="A", etapa="a", modo_custo="informado")))
    _falha(sessao, lambda: sessao.add(MaoDeObra(codigo="B", etapa="b", modo_custo="calculado", salario_mensal=1000)))


def test_um_unico_perfil_padrao(sessao):
    _falha(sessao, lambda: sessao.add(PerfilVenda(nome="Marketplace", padrao=True)))
    sessao.add(PerfilVenda(nome="Marketplace", padrao=False))
    sessao.commit()


def test_configuracao_registro_unico(sessao):
    _falha(sessao, lambda: sessao.add(Configuracao(id=2)))


def test_modo_qtd_invalido(sessao, canvas):
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    _falha(sessao, lambda: sessao.add(FichaMP(produto_id=canvas.id, materia_prima=tela, modo_qtd="volume",
                                              quantidade=1)))
