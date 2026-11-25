"""Relatórios exportáveis (XLSX): tabela de preços, composição detalhada, histórico e impacto."""

from __future__ import annotations

import io
from dataclasses import replace

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..domain.models import HistoricoCustoMO, HistoricoCustoMP, PerfilVenda
from ..domain.pricing.engine import ItemCustoVariavel, calcular
from ..domain.services import faixas as faixas_svc
from ..domain.services.impacto import LinhaImpacto
from ..domain.services.precificacao import calcular_todos, entrada_do_produto, perfil_padrao, regras_empresa

FMT_MOEDA = '"R$" #,##0.00'
FMT_MOEDA4 = '"R$" #,##0.0000'
FMT_PCT = '0.00" %"'
FMT_NUM = '#,##0.######'


# ============================================================================ dados
def tabela_precos(sessao: Session, apenas_ativos: bool = True) -> pd.DataFrame:
    regras, padrao = regras_empresa(sessao), perfil_padrao(sessao)
    lista_faixas = faixas_svc.listar(sessao)
    perfis = list(sessao.scalars(select(PerfilVenda).options(selectinload(PerfilVenda.custos))
                                 .order_by(PerfilVenda.padrao.desc(), PerfilVenda.nome)))
    linhas = []
    for p, r in calcular_todos(sessao, apenas_ativos=apenas_ativos):
        m_real = r.simular(p.preco_praticado).margem_pct if p.preco_praticado and r.preco is not None else None
        d = {
            "SKU": p.sku, "Produto": p.nome,
            "Grupo": f"{p.subgrupo.grupo.codigo} - {p.subgrupo.grupo.nome}",
            "Subgrupo": f"{p.subgrupo.codigo} - {p.subgrupo.nome}",
            "Largura (cm)": p.largura_cm, "Altura (cm)": p.altura_cm,
            "Perfil de venda": (p.perfil_venda or padrao).nome if (p.perfil_venda or padrao) else "",
            "Materiais": r.mp, "Mão de obra": r.mo, "Custo direto": r.cd,
            "Custo fixo": r.parcela_cf, "Custos variáveis": r.parcela_cv,
            "% custo fixo": r.pct_cf, "% custos variáveis": r.pct_cv, "% margem": r.pct_ml,
            "Lucro": r.lucro, "Markup": r.markup, "Preço sugerido": r.preco,
            "Preço mínimo (lucro zero)": r.preco_minimo, "Preço praticado": p.preco_praticado,
            "Margem real no praticado (%)": m_real,
            "Ativo": "sim" if p.ativo else "não", "Alertas": "; ".join(r.alertas),
        }
        d["Custo atual (informado)"] = p.custo_atual
        d["Diferença custo calculado × atual (%)"] = 100 * (r.cd / p.custo_atual - 1) if p.custo_atual else None
        proprias = {m.faixa_id: m.margem_pct for m in p.margens_faixas if m.margem_pct is not None}
        aplicados = {m.faixa_id: m.preco_aplicado for m in p.margens_faixas if m.preco_aplicado is not None}
        for pf in faixas_svc.calcular(r, lista_faixas, proprias, aplicados):
            d[f"{pf.faixa.nome} — margem (%)"] = pf.margem_pct
            d[f"{pf.faixa.nome} — preço calculado"] = pf.preco
            d[f"{pf.faixa.nome} — preço aplicado"] = pf.preco_aplicado
            d[f"{pf.faixa.nome} — margem real no aplicado (%)"] = pf.margem_aplicada
        if len(perfis) > 1:
            base = entrada_do_produto(p, padrao)
            for pf in perfis:
                custos = tuple(ItemCustoVariavel(c.codigo, c.descricao, c.tipo, c.valor) for c in pf.custos if c.ativo)
                d[f"Preço — {pf.nome}"] = calcular(replace(base, custos_variaveis=custos), regras).preco
        linhas.append(d)
    return pd.DataFrame(linhas)


def composicao_detalhada(sessao: Session, apenas_ativos: bool = True) -> pd.DataFrame:
    linhas = []
    for p, r in calcular_todos(sessao, apenas_ativos=apenas_ativos):
        for m in r.materiais:
            l = m.linha
            linhas.append({
                "SKU produto": p.sku, "Produto": p.nome, "Tipo": "Material", "Item": l.sku, "Descrição": l.nome,
                "Modo": l.modo_qtd.value if hasattr(l.modo_qtd, "value") else l.modo_qtd,
                "Quantidade informada": l.quantidade, "Quantidade efetiva": m.qtd_efetiva, "Perda (%)": l.perda_pct,
                "Quantidade c/ perda": m.qtd_comprada, "Unidade": l.unidade_consumo,
                "Custo unitário": m.custo_consumo, "Custo": m.custo,
                "Peças/folha": m.pecas_folha, "Aproveitamento (%)": m.aproveitamento_pct, "Alerta": m.alerta or ""})
        for m in r.mao_de_obra:
            l = m.linha
            linhas.append({
                "SKU produto": p.sku, "Produto": p.nome, "Tipo": "Mão de obra", "Item": l.codigo,
                "Descrição": l.etapa, "Modo": "tempo", "Quantidade informada": l.horas,
                "Quantidade efetiva": l.horas, "Perda (%)": None, "Quantidade c/ perda": l.horas, "Unidade": "h",
                "Custo unitário": l.custo_hora, "Custo": m.custo, "Peças/folha": None,
                "Aproveitamento (%)": None, "Alerta": ""})
    return pd.DataFrame(linhas)


def historico_custos(sessao: Session) -> pd.DataFrame:
    linhas = []
    for h in sessao.scalars(select(HistoricoCustoMP).options(selectinload(HistoricoCustoMP.materia_prima))):
        linhas.append({"Data": h.alterado_em, "Tipo": "Matéria-prima", "Código": h.materia_prima.sku,
                       "Descrição": h.materia_prima.nome, "Unidade": "por unidade de compra",
                       "Anterior": h.custo_anterior, "Novo": h.custo_novo, "Origem": h.origem})
    for h in sessao.scalars(select(HistoricoCustoMO).options(selectinload(HistoricoCustoMO.mao_de_obra))):
        linhas.append({"Data": h.alterado_em, "Tipo": "Mão de obra", "Código": h.mao_de_obra.codigo,
                       "Descrição": h.mao_de_obra.etapa, "Unidade": "por hora",
                       "Anterior": h.custo_hora_anterior, "Novo": h.custo_hora_novo, "Origem": h.origem})
    df = pd.DataFrame(linhas, columns=["Data", "Tipo", "Código", "Descrição", "Unidade", "Anterior", "Novo",
                                       "Origem"])
    if df.empty:
        df["Variação (%)"] = []
        return df
    df["Variação (%)"] = [100 * (n / a - 1) if a else None for a, n in zip(df["Anterior"], df["Novo"])]
    return df.sort_values("Data", ascending=False, kind="stable").reset_index(drop=True)


def impacto_df(linhas: list[LinhaImpacto]) -> pd.DataFrame:
    return pd.DataFrame([{
        "SKU": l.sku, "Produto": l.nome, "Custo direto antes": l.cd_antes, "Custo direto depois": l.cd_depois,
        "Preço sugerido antes": l.preco_antes, "Preço sugerido depois": l.preco_depois,
        "Variação (%)": l.variacao_pct, "Preço praticado": l.praticado,
        "Margem real antes (%)": l.margem_antes, "Margem real depois (%)": l.margem_depois,
        "Margem desejada (%)": l.margem_desejada,
        "Situação": "margem abaixo da desejada" if l.abaixo_da_margem else ""} for l in linhas])


# ============================================================================ XLSX
def xlsx(abas: dict[str, pd.DataFrame]) -> bytes:
    """Planilha formatada: cabeçalho destacado, filtros, moeda/percentual pelo nome da coluna."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nome, df in abas.items():
            df.to_excel(xw, sheet_name=nome[:31], index=False)
            ws = xw.sheets[nome[:31]]
            ws.freeze_panes = "B2" if len(df.columns) > 6 else "A2"
            if len(df):
                ws.auto_filter.ref = ws.dimensions
            for j, col in enumerate(df.columns, start=1):
                cab = ws.cell(row=1, column=j)
                cab.font = Font(bold=True)
                cab.fill = PatternFill("solid", fgColor="DDE4EE")
                cab.alignment = Alignment(wrap_text=True, vertical="top")
                fmt = _formato(col)
                largura = max([len(str(col)) * 0.9] + [len(str(v)) for v in df[col].head(200) if v is not None])
                ws.column_dimensions[cab.column_letter].width = min(max(10, largura + 2), 48)
                if fmt:
                    for (cel,) in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                        cel.number_format = fmt
    return buf.getvalue()


def _formato(col: str) -> str | None:
    c = col.lower()
    if "%" in c:
        return FMT_PCT
    if c in ("data",):
        return "dd/mm/yyyy hh:mm"
    if c.startswith("custo unitário") or c in ("anterior", "novo"):
        return FMT_MOEDA4
    if any(k in c for k in ("preço", "custo", "lucro", "materiais", "mão de obra")) and "(cm)" not in c:
        return FMT_MOEDA
    if c in ("markup",) or "quantidade" in c:
        return FMT_NUM
    return None
