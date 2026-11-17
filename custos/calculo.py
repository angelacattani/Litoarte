"""Motor de formação de preço.

Método: custeio por absorção com **markup divisor**.

    CD   = custo direto unitário
         = Σ MP (quantidade × (1 + perda%) × custo unitário)
         + Σ MO (horas × custo-hora)
         + Σ custos variáveis em R$/unidade
    CFu  = custo fixo absorvido por unidade (rateio por hora de MO ou por
           unidade; zero no método % sobre faturamento)
    %CV  = Σ custos variáveis em % do preço (impostos, comissões, taxas...)
    %CF  = custos fixos ÷ faturamento previsto (só no método % faturamento)
    %ML  = margem de lucro líquida desejada

    Markup divisor  MD = 1 − (%CV + %CF + %ML) / 100
    Preço sugerido  P  = (CD + CFu) / MD

Indicadores derivados para um preço qualquer p:
    margem líquida(p)          = 1 − (%CV + %CF)/100 − (CD + CFu)/p
    margem de contribuição(p)  = p·(1 − %CV/100) − CD
    preço mínimo (lucro zero)  = (CD + CFu) / (1 − (%CV + %CF)/100)
    preço de cobertura (MC = 0)= CD / (1 − %CV/100)   — piso de curto prazo
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .modelos import ESQUEMAS, METODOS_RATEIO, PARAMETROS_PADRAO


def brl(v: float) -> str:
    """Formata no padrão monetário brasileiro: R$ 1.234,56."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class ResumoEmpresa:
    total_fixos: float
    folha_mo: float
    pct_variaveis: float
    custo_var_unitario: float
    taxa_rateio: float               # % (faturamento), R$/h ou R$/un conforme o método
    metodo_rateio: str
    faturamento_projetado: float
    margem_contribuicao_total: float
    mo_absorvida: float
    ociosidade_mo: float
    lucro_projetado: float
    margem_liquida_projetada_pct: float
    ponto_equilibrio_faturamento: float
    ocupacao_mo: pd.DataFrame = field(repr=False)
    alertas: list[str] = field(default_factory=list)


class MotorCustos:
    def __init__(self, dados: dict[str, pd.DataFrame], parametros: dict | None = None):
        self.d = {t: dados.get(t, e.vazio()) for t, e in ESQUEMAS.items()}
        self.p = {**PARAMETROS_PADRAO, **(parametros or {})}
        if self.p["metodo_rateio"] not in METODOS_RATEIO:
            raise ValueError(f"método de rateio desconhecido: {self.p['metodo_rateio']}")
        self.alertas_gerais: list[str] = []
        self._preparar()

    # ------------------------------------------------------------------ bases
    def _preparar(self) -> None:
        mo = self.d["mao_de_obra"].copy()
        horas = mo["horas_produtivas_mes"].replace(0, np.nan)
        mo["custo_hora"] = mo["salario_mensal"] * (1 + mo["encargos_pct"] / 100) / horas
        mo["capacidade_horas"] = mo["quantidade"].astype(float) * mo["horas_produtivas_mes"]
        mo["custo_mensal_total"] = mo["quantidade"].astype(float) * mo["salario_mensal"] * (1 + mo["encargos_pct"] / 100)
        self.mo = mo

        cv = self.d["custos_variaveis"]
        self.pct_var = float(cv.loc[cv["tipo"] == "percentual", "valor"].sum())
        self.var_unit = float(cv.loc[cv["tipo"] == "unitario", "valor"].sum())
        self.total_fixos = float(self.d["custos_fixos"]["valor_mensal"].sum())

        # Linhas da ficha técnica valorizadas
        comp = self.d["composicao"].merge(
            self.d["materias_primas"][["codigo", "descricao", "unidade", "custo_unitario"]],
            left_on="mp_codigo", right_on="codigo", how="left", suffixes=("", "_mp"))
        comp["qtd_com_perda"] = comp["quantidade"] * (1 + comp["perda_pct"] / 100)
        comp["custo"] = comp["qtd_com_perda"] * comp["custo_unitario"]
        self.linhas_mp = comp.drop(columns="codigo")

        pmo = self.d["produto_mao_de_obra"].merge(
            mo[["codigo", "funcao", "custo_hora"]], left_on="mo_codigo", right_on="codigo", how="left")
        pmo["custo"] = pmo["horas"] * pmo["custo_hora"]
        self.linhas_mo = pmo.drop(columns="codigo")

        prod = self.d["produtos"][["codigo", "descricao", "grupo", "subgrupo", "unidade", "margem_desejada_pct",
                                   "volume_mensal", "preco_atual"]].copy()
        prod["custo_mp"] = prod["codigo"].map(self.linhas_mp.groupby("produto_codigo")["custo"].sum()).fillna(0.0)
        prod["custo_mo"] = prod["codigo"].map(self.linhas_mo.groupby("produto_codigo")["custo"].sum()).fillna(0.0)
        prod["horas_mo"] = prod["codigo"].map(self.linhas_mo.groupby("produto_codigo")["horas"].sum()).fillna(0.0)
        prod["custo_var_unit"] = self.var_unit
        prod["custo_direto"] = prod["custo_mp"] + prod["custo_mo"] + prod["custo_var_unit"]
        self._base = prod
        self._calcular_rateio()

    def _calcular_rateio(self) -> None:
        metodo = self.p["metodo_rateio"]
        prod = self._base
        self.pct_fix, self.taxa_rateio = 0.0, 0.0
        prod["custo_fixo_unit"] = 0.0
        if self.total_fixos == 0:
            return
        if metodo == "percentual_faturamento":
            fat = float(self.p.get("faturamento_mensal_previsto") or 0)
            if fat > 0:
                self.pct_fix = self.taxa_rateio = 100 * self.total_fixos / fat
            else:
                self.alertas_gerais.append(
                    "Faturamento mensal previsto não informado: custos fixos NÃO estão sendo incluídos no preço.")
        elif metodo == "por_hora_mo":
            horas_previstas = float((prod["volume_mensal"] * prod["horas_mo"]).sum())
            base = horas_previstas
            if base <= 0:
                base = float(self.mo["capacidade_horas"].sum())
                self.alertas_gerais.append(
                    "Sem volume previsto com horas de MO: rateio feito sobre a capacidade total de horas.")
            if base > 0:
                self.taxa_rateio = self.total_fixos / base
                prod["custo_fixo_unit"] = prod["horas_mo"] * self.taxa_rateio
            else:
                self.alertas_gerais.append("Sem horas de mão de obra cadastradas: impossível ratear por hora.")
        elif metodo == "por_unidade":
            vol = float(prod["volume_mensal"].sum())
            if vol > 0:
                self.taxa_rateio = self.total_fixos / vol
                prod["custo_fixo_unit"] = self.taxa_rateio
            else:
                self.alertas_gerais.append("Volume mensal previsto zerado: impossível ratear por unidade.")

    # ------------------------------------------------------------- precificação
    def margem_em(self, preco, custo_total, pct_fix=None):
        """Margem líquida (%) obtida a um preço dado. Aceita escalares ou Series."""
        pct_fix = self.pct_fix if pct_fix is None else pct_fix
        preco = pd.Series(preco, dtype="float64") if not np.isscalar(preco) else float(preco)
        with np.errstate(divide="ignore", invalid="ignore"):
            m = 100 * (1 - (self.pct_var + pct_fix) / 100 - custo_total / preco)
        return m

    def tabela_precos(self) -> pd.DataFrame:
        """Uma linha por produto com custos, preço sugerido, margens e concorrência."""
        df = self._base.copy()
        df["margem_pct"] = df["margem_desejada_pct"].fillna(float(self.p["margem_padrao_pct"]))
        df["pct_variaveis"] = self.pct_var
        df["pct_fixos"] = self.pct_fix
        df["custo_total"] = df["custo_direto"] + df["custo_fixo_unit"]
        df["markup_divisor"] = 1 - (self.pct_var + self.pct_fix + df["margem_pct"]) / 100
        df["markup_multiplicador"] = np.where(df["markup_divisor"] > 0, 1 / df["markup_divisor"], np.nan)
        df["preco_sugerido"] = np.where(df["markup_divisor"] > 0, df["custo_total"] / df["markup_divisor"], np.nan)

        div_min = 1 - (self.pct_var + self.pct_fix) / 100
        df["preco_minimo"] = df["custo_total"] / div_min if div_min > 0 else np.nan
        div_cob = 1 - self.pct_var / 100
        df["preco_cobertura"] = df["custo_direto"] / div_cob if div_cob > 0 else np.nan

        p = df["preco_sugerido"]
        df["margem_contribuicao_unit"] = p * (1 - self.pct_var / 100) - df["custo_direto"]
        df["margem_contribuicao_pct"] = 100 * df["margem_contribuicao_unit"] / p
        df["lucro_unit"] = p * df["margem_pct"] / 100
        df["margem_preco_atual_pct"] = self.margem_em(df["preco_atual"].values, df["custo_total"].values)
        df["dif_preco_atual_pct"] = 100 * (df["preco_atual"] / p - 1)

        # Concorrência
        conc = self.d["concorrentes"].groupby("produto_codigo")["preco"].agg(
            conc_n="count", conc_min="min", conc_media="mean", conc_max="max")
        df = df.merge(conc, left_on="codigo", right_index=True, how="left")
        df["conc_n"] = df["conc_n"].fillna(0).astype(int)
        df["dif_vs_conc_media_pct"] = 100 * (p / df["conc_media"] - 1)
        tol = float(self.p["tolerancia_concorrencia_pct"])
        df["posicao_mercado"] = np.select(
            [df["conc_n"] == 0, df["dif_vs_conc_media_pct"] < -tol, df["dif_vs_conc_media_pct"] > tol],
            ["sem dados", "abaixo", "acima"], default="alinhado")
        df["margem_no_preco_conc_pct"] = self.margem_em(df["conc_media"].values, df["custo_total"].values)
        df["alertas"] = df.apply(self._alertas_produto, axis=1)
        return df.reset_index(drop=True)

    def _alertas_produto(self, r: pd.Series) -> str:
        a = []
        if r["custo_mp"] == 0:
            a.append("sem ficha de matéria-prima")
        if r["custo_mo"] == 0:
            a.append("sem mão de obra")
        if not r["markup_divisor"] > 0:
            a.append("soma de %CV + %CF + margem ≥ 100%: preço indefinido")
        if pd.notna(r["conc_min"]) and pd.notna(r["preco_minimo"]) and r["preco_minimo"] > r["conc_min"]:
            a.append("custo acima do menor preço da concorrência")
        if pd.notna(r["preco_atual"]) and pd.notna(r["preco_minimo"]) and r["preco_atual"] < r["preco_minimo"]:
            a.append("preço atual gera prejuízo")
        return "; ".join(a)

    def detalhar(self, codigo: str) -> dict:
        """Ficha de custos de um produto (para exibição/relatório)."""
        tab = self.tabela_precos()
        linha = tab.loc[tab["codigo"] == codigo]
        if linha.empty:
            raise KeyError(f"produto {codigo} não cadastrado")
        return {
            "resultado": linha.iloc[0],
            "materias_primas": self.linhas_mp.loc[self.linhas_mp["produto_codigo"] == codigo,
                                                  ["mp_codigo", "descricao", "unidade", "quantidade", "perda_pct",
                                                   "qtd_com_perda", "custo_unitario", "custo"]],
            "mao_de_obra": self.linhas_mo.loc[self.linhas_mo["produto_codigo"] == codigo,
                                              ["mo_codigo", "funcao", "horas", "custo_hora", "custo"]],
            "concorrentes": self.d["concorrentes"].loc[self.d["concorrentes"]["produto_codigo"] == codigo],
        }

    def simular(self, codigo: str, preco: float) -> dict:
        """Indicadores de um produto a um preço arbitrário (what-if)."""
        r = self.tabela_precos().set_index("codigo").loc[codigo]
        mc = preco * (1 - self.pct_var / 100) - r["custo_direto"]
        return {
            "preco": preco,
            "margem_liquida_pct": float(self.margem_em(preco, r["custo_total"])),
            "lucro_unit": preco - r["custo_total"] - preco * (self.pct_var + self.pct_fix) / 100,
            "margem_contribuicao_unit": mc,
            "margem_contribuicao_pct": 100 * mc / preco if preco else np.nan,
        }

    def resumo_por_grupo(self, nivel: str = "subgrupo", coluna_preco: str = "preco_sugerido") -> pd.DataFrame:
        """Resultado mensal projetado agregado por grupo (nivel='grupo') ou grupo+subgrupo.

        Lucro = Σ volume × (preço − custo total − %CV·preço − %CF·preço); a
        ociosidade de MO não é atribuída a grupos (aparece só no resumo geral).
        """
        t = self.tabela_precos()
        preco = t[coluna_preco].fillna(t["preco_sugerido"]).fillna(0)
        vol = t["volume_mensal"]
        t = t.assign(
            faturamento=vol * preco,
            margem_contribuicao=vol * (preco * (1 - self.pct_var / 100) - t["custo_direto"]),
            lucro=vol * (preco - t["custo_total"] - preco * (self.pct_var + self.pct_fix) / 100),
        )
        chaves = ["grupo"] if nivel == "grupo" else ["grupo", "subgrupo"]
        g = t.groupby(chaves, dropna=False).agg(
            produtos=("codigo", "count"), volume=("volume_mensal", "sum"),
            faturamento=("faturamento", "sum"), margem_contribuicao=("margem_contribuicao", "sum"),
            lucro=("lucro", "sum")).reset_index()
        with np.errstate(divide="ignore", invalid="ignore"):
            g["mc_pct"] = 100 * g["margem_contribuicao"] / g["faturamento"]
            g["margem_liquida_pct"] = 100 * g["lucro"] / g["faturamento"]
        total = g["faturamento"].sum()
        g["participacao_pct"] = 100 * g["faturamento"] / total if total else np.nan
        return g.sort_values("faturamento", ascending=False).reset_index(drop=True)

    # ------------------------------------------------------------------ empresa
    def resumo(self, coluna_preco: str = "preco_sugerido") -> ResumoEmpresa:
        """Resultado mensal projetado com os volumes previstos e o preço escolhido."""
        tab = self.tabela_precos()
        preco = tab[coluna_preco].fillna(tab["preco_sugerido"]).fillna(0)
        vol = tab["volume_mensal"]
        fat = float((vol * preco).sum())
        mc = float((vol * (preco * (1 - self.pct_var / 100) - tab["custo_direto"])).sum())
        mo_abs = float((vol * tab["custo_mo"]).sum())
        folha = float(self.mo["custo_mensal_total"].sum())
        ocios = max(folha - mo_abs, 0.0)
        lucro = mc - self.total_fixos - ocios
        mc_pct = mc / fat if fat else 0
        pe = (self.total_fixos + ocios) / mc_pct if mc_pct > 0 else np.nan

        uso = (self.linhas_mo.assign(vol=self.linhas_mo["produto_codigo"].map(
            tab.set_index("codigo")["volume_mensal"]).fillna(0))
            .assign(horas_previstas=lambda x: x["horas"] * x["vol"])
            .groupby("mo_codigo")["horas_previstas"].sum())
        ocup = self.mo[["codigo", "funcao", "quantidade", "capacidade_horas", "custo_hora", "custo_mensal_total"]].copy()
        ocup["horas_previstas"] = ocup["codigo"].map(uso).fillna(0.0)
        ocup["ocupacao_pct"] = 100 * ocup["horas_previstas"] / ocup["capacidade_horas"].replace(0, np.nan)

        alertas = list(self.alertas_gerais)
        for _, r in ocup[ocup["ocupacao_pct"] > 100].iterrows():
            alertas.append(f"Mão de obra '{r['funcao']}' com ocupação de {r['ocupacao_pct']:.0f}% — capacidade insuficiente.")
        if ocios > 0 and folha > 0:
            alertas.append(f"Ociosidade de MO de {brl(ocios)}/mês não absorvida pelos produtos (volume abaixo da capacidade).")
        if self.p["metodo_rateio"] == "percentual_faturamento" and fat and self.pct_fix:
            fat_prev = float(self.p["faturamento_mensal_previsto"])
            if abs(fat / fat_prev - 1) > 0.15:
                alertas.append(f"Faturamento projetado ({brl(fat)}) difere >15% do previsto usado no rateio "
                               f"({brl(fat_prev)}): revise o parâmetro.")

        return ResumoEmpresa(
            total_fixos=self.total_fixos, folha_mo=folha, pct_variaveis=self.pct_var,
            custo_var_unitario=self.var_unit, taxa_rateio=self.taxa_rateio,
            metodo_rateio=self.p["metodo_rateio"], faturamento_projetado=fat,
            margem_contribuicao_total=mc, mo_absorvida=mo_abs, ociosidade_mo=ocios,
            lucro_projetado=lucro, margem_liquida_projetada_pct=100 * lucro / fat if fat else np.nan,
            ponto_equilibrio_faturamento=pe, ocupacao_mo=ocup, alertas=alertas,
        )
