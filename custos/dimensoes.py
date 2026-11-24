"""Cálculos dimensionais da ficha técnica.

Aproveitamento de folha/chapa (encaixe retangular, corte guilhotina):

    área útil  = (L − 2·margem) × (C − 2·margem)
    n peças em uma direção = ⌊(útil + e) / (peça + e)⌋   (e = espaço entre peças)

Testa as duas orientações da peça e, em cada uma, aproveita a sobra lateral
(ou longitudinal) com peças giradas 90°. Fica com a disposição de mais peças.

Exemplo: folha 100 × 200 cm, peça 15 × 15 cm, e = 0 → 6 × 13 = 78 peças,
aproveitamento = 78 × 225 / 20 000 = 87,75 %.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

_EPS = 1e-9


@dataclass(frozen=True)
class Encaixe:
    pecas: int
    disposicao: str          # descrição legível, ex.: "6 × 13" ou "6 × 10 + 1 × 6 (girada)"
    aproveitamento_pct: float


def _n(util: float, peca: float, e: float) -> int:
    if peca <= 0 or util + _EPS < peca:
        return 0
    return int(math.floor((util + e) / (peca + e) + _EPS))


def pecas_por_folha(folha_larg_cm: float, folha_comp_cm: float, peca_larg_cm: float, peca_alt_cm: float,
                    espacamento_cm: float = 0.0, margem_cm: float = 0.0) -> Encaixe:
    """Maior número de peças retangulares que cabem na folha."""
    L = folha_larg_cm - 2 * margem_cm
    C = folha_comp_cm - 2 * margem_cm
    e = max(espacamento_cm, 0.0)
    melhor = Encaixe(0, "não cabe", 0.0)
    if L <= 0 or C <= 0 or peca_larg_cm <= 0 or peca_alt_cm <= 0:
        return melhor
    for a, b, rot in ((peca_larg_cm, peca_alt_cm, ""), (peca_alt_cm, peca_larg_cm, " (girada)")):
        nx, ny = _n(L, a, e), _n(C, b, e)
        base = nx * ny
        if base == 0:
            continue
        # sobra na largura, preenchida com a peça na outra orientação
        sobra_x = L - nx * (a + e)
        ex = _n(sobra_x, b, e) * _n(C, a, e)
        # sobra no comprimento
        sobra_y = C - ny * (b + e)
        ey = _n(L, b, e) * _n(sobra_y, a, e)
        opcoes = [(base, f"{nx} × {ny}{rot}")]
        if ex:
            opcoes.append((base + ex, f"{nx} × {ny}{rot} + {ex} na sobra lateral"))
        if ey:
            opcoes.append((base + ey, f"{nx} × {ny}{rot} + {ey} na sobra do comprimento"))
        total, desc = max(opcoes, key=lambda o: o[0])
        if total > melhor.pecas:
            ap = 100 * total * peca_larg_cm * peca_alt_cm / (folha_larg_cm * folha_comp_cm)
            melhor = Encaixe(total, desc, ap)
    return melhor


def ficha_efetiva(produtos: pd.DataFrame, ficha_produto: pd.DataFrame, ficha_subgrupo: pd.DataFrame,
                  item: str, qtd: str) -> pd.DataFrame:
    """Ficha técnica de cada produto = padrão do subgrupo + ajustes do produto.

    item: coluna do item ('mp_codigo' ou 'mo_codigo'); qtd: 'quantidade' ou 'horas'.
    Linha do produto substitui a do subgrupo para o mesmo item; quantidade 0 exclui.
    """
    herdada = (produtos[["codigo", "grupo_codigo", "subgrupo_codigo"]]
               .merge(ficha_subgrupo, on=["grupo_codigo", "subgrupo_codigo"])
               .rename(columns={"codigo": "produto_codigo"})
               .drop(columns=["grupo_codigo", "subgrupo_codigo"])
               .assign(origem="subgrupo"))
    propria = ficha_produto.assign(origem="produto")
    tudo = pd.concat([propria, herdada], ignore_index=True)
    tudo = tudo.drop_duplicates(subset=["produto_codigo", item], keep="first")
    return tudo[tudo[qtd] > 0].reset_index(drop=True)
