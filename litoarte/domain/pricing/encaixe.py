"""Peças por folha/chapa (encaixe retangular, corte guilhotina) — especificação, seção 3.6.

    n(u, ℓ) = ⌊(u + e) / (ℓ + e)⌋      u = dimensão útil (folha − 2·margem), e = espaço entre peças

Testa as duas orientações; em cada uma, preenche a sobra lateral ou longitudinal com peças giradas
90° e fica com a disposição de mais peças. Folha 100 × 200 cm, peça 15 × 15 → 6 × 13 = 78 (87,75 %).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_EPS = 1e-9


@dataclass(frozen=True)
class Encaixe:
    pecas: int
    disposicao: str
    aproveitamento_pct: float


def _n(util: float, peca: float, e: float) -> int:
    if peca <= 0 or util + _EPS < peca:
        return 0
    return int(math.floor((util + e) / (peca + e) + _EPS))


def pecas_por_folha(folha_larg_cm: float, folha_comp_cm: float, peca_larg_cm: float, peca_alt_cm: float,
                    espacamento_cm: float = 0.0, margem_cm: float = 0.0) -> Encaixe:
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
        ex = _n(L - nx * (a + e), b, e) * _n(C, a, e)       # sobra na largura
        ey = _n(L, b, e) * _n(C - ny * (b + e), a, e)       # sobra no comprimento
        opcoes = [(base, f"{nx} × {ny}{rot}")]
        if ex:
            opcoes.append((base + ex, f"{nx} × {ny}{rot} + {ex} na sobra lateral"))
        if ey:
            opcoes.append((base + ey, f"{nx} × {ny}{rot} + {ey} na sobra do comprimento"))
        total, desc = max(opcoes, key=lambda o: o[0])
        if total > melhor.pecas:
            melhor = Encaixe(total, desc, 100 * total * peca_larg_cm * peca_alt_cm / (folha_larg_cm * folha_comp_cm))
    return melhor
