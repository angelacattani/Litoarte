"""Fase 4: relatório de impacto de reajustes, exportações e histórico."""

import io

import pandas as pd
import pytest
from sqlalchemy import select

from litoarte.domain.models import CustoVariavel, MaoDeObra, MateriaPrima, PerfilVenda, Produto
from litoarte.domain.services import composicao as C, impacto, perfis
from litoarte.domain.services.cadastros import MODULOS
from litoarte.planilhas import relatorios as R
from litoarte.planilhas.importacao import aplicar, analisar


def _segundo_produto(sessao, canvas):
    return C.clonar(sessao, canvas.id, sku="QDC-4060", nome="Quadro Canvas 40×60", largura_cm=40, altura_cm=60)


def test_reajuste_manual_de_insumo_mostra_impacto(sessao, canvas):
    _segundo_produto(sessao, canvas)
    sessao.get(Produto, canvas.id).preco_praticado = 160.0
    sessao.commit()
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    _, linhas = impacto.gravar_com_impacto(sessao, MODULOS["materias_primas"], {"sku": "TELA", "custo_compra": 45},
                                           id_edicao=tela.id, vazios_apagam=True)
    sessao.commit()
    por_sku = {l.sku: l for l in linhas}
    assert set(por_sku) == {"QDC-6090", "QDC-4060"}
    g = por_sku["QDC-6090"]
    assert round(g.preco_antes, 2) == 152.10
    assert g.preco_depois == pytest.approx(g.preco_antes + 0.54 / 0.90 * 7 / 0.505)
    assert g.cd_depois - g.cd_antes == pytest.approx(0.54 / 0.90 * 7)
    # no praticado de R$ 160 a margem cai de 22,49 % para 19,87 %: abaixo dos 20 % desejados
    assert round(g.margem_antes, 2) == 22.49 and round(g.margem_depois, 2) == 19.87 and g.abaixo_da_margem
    assert linhas[0].sku == "QDC-4060" or abs(linhas[0].variacao_pct) >= abs(linhas[1].variacao_pct)
    assert por_sku["QDC-4060"].praticado is None and por_sku["QDC-4060"].margem_depois is None


def test_alteracao_sem_efeito_no_custo_nao_lista(sessao, canvas):
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    _, linhas = impacto.gravar_com_impacto(sessao, MODULOS["materias_primas"], {"sku": "TELA", "nome": "Tela crua"},
                                           id_edicao=tela.id)
    assert linhas == []


def test_reajuste_de_mao_de_obra(sessao, canvas):
    mon = sessao.scalar(select(MaoDeObra).where(MaoDeObra.codigo == "MON"))
    _, [l] = impacto.gravar_com_impacto(sessao, MODULOS["mao_de_obra"], {"codigo": "MON", "custo_minuto": "0,50"},
                                        id_edicao=mon.id)
    assert l.cd_depois - l.cd_antes == pytest.approx(20 * 0.10)


def test_importacao_de_precos_traz_impacto(sessao, canvas):
    sessao.get(Produto, canvas.id).preco_praticado = 139.9
    sessao.commit()
    a = analisar(sessao, "materias_primas", b"sku;custo_compra\nTELA;45\nCHASSI;12\n", "reajuste.csv", "atualizar")
    r = aplicar(sessao, a)
    sessao.commit()
    [l] = r.impacto
    assert l.sku == "QDC-6090" and l.preco_depois > l.preco_antes and l.abaixo_da_margem
    df = R.impacto_df(r.impacto)
    assert df.loc[0, "Situação"] == "margem abaixo da desejada"


def test_tabela_de_precos_com_canais(sessao, canvas):
    direta = sessao.scalar(select(PerfilVenda).where(PerfilVenda.padrao))
    mkt = perfis.criar(sessao, "Marketplace", copiar_de=direta.id)
    c = CustoVariavel(codigo="MKT", descricao="Comissão", categoria="marketplace", valor=16)
    sessao.add(c)
    sessao.flush()
    perfis.definir_custo(sessao, mkt.id, c.id, True)
    sessao.get(Produto, canvas.id).preco_praticado = 139.9
    sessao.commit()
    df = R.tabela_precos(sessao)
    linha = df.iloc[0]
    assert round(linha["Preço sugerido"], 2) == 152.10 and round(linha["Custo direto"], 2) == 76.81
    assert round(linha["Margem real no praticado (%)"], 2) == 15.59
    assert linha["Custo direto"] + linha["Custo fixo"] + linha["Custos variáveis"] + linha["Lucro"] == \
        pytest.approx(linha["Preço sugerido"])
    assert round(linha["Preço — Venda direta"], 2) == 152.10
    # marketplace: %CV 14,5 + 16 = 30,5 %; %CF 15 %; margem 20 %
    assert linha["Preço — Marketplace"] == pytest.approx(76.8128 / (1 - (0.305 + 0.15 + 0.20)), rel=1e-5)


def test_composicao_detalhada_soma_o_custo_direto(sessao, canvas):
    df = R.composicao_detalhada(sessao)
    assert len(df) == 8                                   # 5 materiais + 3 etapas
    assert df["Custo"].sum() == pytest.approx(76.8128, abs=1e-4)
    tinta = df[df["Item"] == "TINTA"].iloc[0]
    assert tinta["Unidade"] == "ml" and tinta["Custo unitário"] == pytest.approx(0.28)


def test_historico_e_xlsx(sessao, canvas):
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    impacto.gravar_com_impacto(sessao, MODULOS["materias_primas"], {"sku": "TELA", "custo_compra": 40},
                               id_edicao=tela.id)
    mon = sessao.scalar(select(MaoDeObra).where(MaoDeObra.codigo == "MON"))
    impacto.gravar_com_impacto(sessao, MODULOS["mao_de_obra"], {"codigo": "MON", "custo_hora": 30},
                               id_edicao=mon.id)
    sessao.commit()
    h = R.historico_custos(sessao)
    assert set(h["Código"]) == {"TELA", "MON"}
    assert h.set_index("Código").loc["TELA", "Variação (%)"] == pytest.approx(100 * (40 / 38 - 1))
    conteudo = R.xlsx({"Preços": R.tabela_precos(sessao), "Composição": R.composicao_detalhada(sessao),
                       "Histórico": h})
    abas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None)
    assert set(abas) == {"Preços", "Composição", "Histórico"}
    assert R.xlsx({"Vazio": R.tabela_precos(sessao).iloc[0:0]})          # exporta mesmo sem linhas


def test_historico_grava_horario_local(sessao, canvas):
    from datetime import datetime
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    antes = datetime.now()
    impacto.gravar_com_impacto(sessao, MODULOS["materias_primas"], {"sku": "TELA", "custo_compra": 40},
                               id_edicao=tela.id)
    sessao.commit()
    data = R.historico_custos(sessao).loc[0, "Data"]
    assert abs((data - antes).total_seconds()) < 60        # horário local, não UTC
