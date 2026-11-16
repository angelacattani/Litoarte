"""Importação e exportação (XLSX e CSV).

XLSX completo: uma aba por tabela (nomes = chaves de ESQUEMAS). Abas com
outros nomes são ignoradas na importação, então o próprio arquivo exportado
(que inclui as abas de relatório 'precos' e 'resumo') pode ser reimportado.

CSV: uma tabela por arquivo. Na leitura detecta separador (',' ou ';') e
números no formato brasileiro; na escrita usa ';' e vírgula decimal, com BOM
UTF-8 para abrir corretamente no Excel em pt-BR.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .calculo import MotorCustos
from .modelos import ESQUEMAS, METODOS_RATEIO, ORDEM_TABELAS, normalizar_nome

Arquivo = str | Path | BinaryIO

# Colunas do relatório de preços (nome interno -> rótulo exportado)
COLUNAS_RELATORIO = {
    "codigo": "Código", "descricao": "Descrição", "unidade": "Un.",
    "custo_mp": "Matéria-prima (R$)", "custo_mo": "Mão de obra (R$)",
    "custo_var_unit": "Variáveis unit. (R$)", "custo_direto": "Custo direto (R$)",
    "custo_fixo_unit": "Fixo rateado (R$)", "custo_total": "Custo total (R$)",
    "pct_variaveis": "% Variáveis", "pct_fixos": "% Fixos", "margem_pct": "% Margem",
    "markup_multiplicador": "Markup (×)", "preco_sugerido": "Preço sugerido (R$)",
    "preco_minimo": "Preço mínimo — lucro zero (R$)", "preco_cobertura": "Preço de cobertura — MC zero (R$)",
    "margem_contribuicao_unit": "MC unit. (R$)", "margem_contribuicao_pct": "MC %",
    "preco_atual": "Preço atual (R$)", "margem_preco_atual_pct": "Margem no preço atual %",
    "conc_n": "Nº concorrentes", "conc_min": "Concorrência mín. (R$)",
    "conc_media": "Concorrência média (R$)", "conc_max": "Concorrência máx. (R$)",
    "dif_vs_conc_media_pct": "Dif. vs média conc. %", "posicao_mercado": "Posição",
    "margem_no_preco_conc_pct": "Margem praticando média conc. %",
    "volume_mensal": "Volume mensal", "alertas": "Alertas",
}


# ----------------------------------------------------------------- importação
def ler_xlsx(arquivo: Arquivo) -> dict[str, pd.DataFrame]:
    """Lê as abas reconhecidas de um XLSX. Retorna {tabela: DataFrame bruto}."""
    abas = pd.read_excel(arquivo, sheet_name=None, dtype=object)
    saida = {}
    for nome, df in abas.items():
        tabela = _tabela_por_nome(nome)
        if tabela:
            saida[tabela] = df
    if not saida:
        raise ValueError("Nenhuma aba reconhecida. Use os nomes: " + ", ".join(ORDEM_TABELAS))
    return saida


def ler_csv(arquivo: Arquivo, tabela: str) -> pd.DataFrame:
    if tabela not in ESQUEMAS:
        raise ValueError(f"tabela desconhecida: {tabela}")
    bruto = arquivo.read() if hasattr(arquivo, "read") else Path(arquivo).read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = bruto.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.StringIO(texto), sep=None, engine="python", dtype=str, keep_default_na=False)


def _tabela_por_nome(nome: str) -> str | None:
    n = normalizar_nome(nome)
    if n in ESQUEMAS:
        return n
    for t, e in ESQUEMAS.items():
        if n == normalizar_nome(e.titulo):
            return t
    return None


# ----------------------------------------------------------------- exportação
def relatorio_precos(motor: MotorCustos) -> pd.DataFrame:
    tab = motor.tabela_precos()
    return tab[list(COLUNAS_RELATORIO)].rename(columns=COLUNAS_RELATORIO)


def exportar_xlsx(dados: dict[str, pd.DataFrame], parametros: dict, destino: Arquivo | None = None,
                  incluir_relatorio: bool = True) -> bytes | None:
    """Exporta todas as tabelas (+ relatório de preços e resumo). Sem destino, retorna bytes."""
    buffer = io.BytesIO() if destino is None else destino
    with pd.ExcelWriter(buffer, engine="openpyxl") as xw:
        if incluir_relatorio:
            motor = MotorCustos(dados, parametros)
            relatorio_precos(motor).to_excel(xw, sheet_name="precos", index=False)
            _resumo_df(motor).to_excel(xw, sheet_name="resumo", index=False)
        for t in ORDEM_TABELAS:
            dados.get(t, ESQUEMAS[t].vazio()).to_excel(xw, sheet_name=t, index=False)
        pd.DataFrame(list(parametros.items()), columns=["chave", "valor"]).to_excel(
            xw, sheet_name="parametros", index=False)
        _formatar(xw)
    if destino is None:
        return buffer.getvalue()
    return None


def ler_parametros_xlsx(arquivo: Arquivo) -> dict:
    """Lê a aba 'parametros' se existir (gerada por exportar_xlsx)."""
    try:
        df = pd.read_excel(arquivo, sheet_name="parametros")
    except ValueError:
        return {}
    p = {}
    for _, r in df.iterrows():
        k, v = str(r["chave"]), r["valor"]
        if k == "metodo_rateio":
            if v in METODOS_RATEIO:
                p[k] = v
        elif pd.notna(v):
            p[k] = float(v)
    return p


def exportar_csv(df: pd.DataFrame, destino: Arquivo | None = None) -> bytes | None:
    texto = df.to_csv(sep=";", decimal=",", index=False, float_format="%.4f")
    dados = texto.encode("utf-8-sig")
    if destino is None:
        return dados
    if hasattr(destino, "write"):
        destino.write(dados)
    else:
        Path(destino).write_bytes(dados)
    return None


def planilha_modelo() -> bytes:
    """XLSX vazio com todas as abas, cabeçalhos e uma aba de instruções."""
    buffer = io.BytesIO()
    linhas = []
    for t in ORDEM_TABELAS:
        e = ESQUEMAS[t]
        for c in e.colunas:
            linhas.append({"aba": t, "coluna": c.nome, "tipo": c.tipo,
                           "obrigatória": "sim" if c.obrigatoria else "",
                           "padrão": "" if c.padrao is None else c.padrao, "descrição": c.descricao})
    with pd.ExcelWriter(buffer, engine="openpyxl") as xw:
        pd.DataFrame(linhas).to_excel(xw, sheet_name="instrucoes", index=False)
        for t in ORDEM_TABELAS:
            ESQUEMAS[t].vazio().to_excel(xw, sheet_name=t, index=False)
        _formatar(xw)
    return buffer.getvalue()


def _resumo_df(motor: MotorCustos) -> pd.DataFrame:
    r = motor.resumo()
    itens = [
        ("Método de rateio dos fixos", METODOS_RATEIO[r.metodo_rateio]),
        ("Custos fixos mensais (R$)", r.total_fixos),
        ("Folha de MO direta c/ encargos (R$)", r.folha_mo),
        ("Custos variáveis (% do preço)", r.pct_variaveis),
        ("Custos variáveis unitários (R$/un)", r.custo_var_unitario),
        ("Faturamento projetado (R$)", r.faturamento_projetado),
        ("Margem de contribuição total (R$)", r.margem_contribuicao_total),
        ("Ociosidade de MO não absorvida (R$)", r.ociosidade_mo),
        ("Lucro líquido projetado (R$)", r.lucro_projetado),
        ("Margem líquida projetada (%)", r.margem_liquida_projetada_pct),
        ("Ponto de equilíbrio (faturamento R$)", r.ponto_equilibrio_faturamento),
    ] + [("Alerta", a) for a in r.alertas]
    return pd.DataFrame(itens, columns=["Indicador", "Valor"])


def _formatar(xw: pd.ExcelWriter) -> None:
    """Cabeçalho em negrito, congelado, e largura de colunas ajustada."""
    from openpyxl.styles import Font, PatternFill
    for ws in xw.book.worksheets:
        ws.freeze_panes = "A2"
        for cel in ws[1]:
            cel.font = Font(bold=True)
            cel.fill = PatternFill("solid", fgColor="DDE4EE")
        for col in ws.columns:
            larg = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(max(larg + 2, 10), 60)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"
