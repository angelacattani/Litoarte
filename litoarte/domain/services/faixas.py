"""Faixas de preço: 5 preços com margens diferentes sobre o mesmo custo.

Cada faixa tem nome e margem geral (Configuração). Um produto pode ter margem própria em qualquer
faixa; vazio = margem geral. O preço de cada faixa usa o mesmo markup divisor do preço sugerido:

    P_faixa = (CD + CFu + CV_fixo) / (1 − (%CV + %CF + %margem_faixa))
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FaixaPreco
from ..pricing.engine import ResultadoPreco
from .cadastros import ErroValidacao


@dataclass(frozen=True)
class FaixaInfo:
    id: int
    ordem: int
    nome: str
    margem_pct: float


@dataclass(frozen=True)
class PrecoFaixa:
    faixa: FaixaInfo
    margem_pct: float
    propria: bool                 # margem própria do produto (True) ou geral da faixa
    preco: float | None           # calculado; None: margem impossível com os custos variáveis e fixos atuais
    lucro: float | None
    margem_contribuicao: float | None
    margem_contribuicao_pct: float | None
    markup: float | None
    preco_aplicado: float | None = None          # preço praticado hoje nesta faixa
    margem_aplicada: float | None = None         # margem líquida real do preço aplicado (custo calculado)
    lucro_aplicado: float | None = None

    @property
    def abaixo(self) -> bool:
        """Preço aplicado rende menos que a margem da faixa."""
        return self.margem_aplicada is not None and self.margem_aplicada < self.margem_pct - 1e-9


def listar(sessao: Session) -> list[FaixaInfo]:
    return [FaixaInfo(f.id, f.ordem, f.nome, f.margem_pct)
            for f in sessao.scalars(select(FaixaPreco).order_by(FaixaPreco.ordem))]


def salvar(sessao: Session, dados: list[dict]) -> None:
    """dados: [{"id", "nome", "margem_pct"}]. Valida tudo antes de gravar."""
    erros: list[tuple[str, str]] = []
    nomes: set[str] = set()
    for d in dados:
        rot = f"faixa {d.get('ordem', d['id'])}"
        nome = " ".join(str(d.get("nome") or "").split())
        if not nome:
            erros.append((rot, "nome obrigatório"))
        elif nome.casefold() in nomes:
            erros.append((rot, f"nome repetido: {nome}"))
        nomes.add(nome.casefold())
        m = d.get("margem_pct")
        if m is None or not 0 <= m < 100:
            erros.append((rot, "margem entre 0 e 100 %"))
    if erros:
        raise ErroValidacao(erros)
    for d in dados:
        f = sessao.get(FaixaPreco, d["id"])
        f.nome, f.margem_pct = " ".join(d["nome"].split()), d["margem_pct"]
    sessao.flush()


def calcular(resultado: ResultadoPreco, faixas: list[FaixaInfo],
             margens_proprias: dict[int, float] | None = None,
             precos_aplicados: dict[int, float] | None = None) -> list[PrecoFaixa]:
    """Os preços de todas as faixas para um resultado do motor (mesmo custo, margens diferentes),
    com a margem real de cada preço aplicado."""
    proprias = margens_proprias or {}
    aplicados = precos_aplicados or {}
    linhas = []
    for f in faixas:
        m = proprias.get(f.id, f.margem_pct)
        ap = aplicados.get(f.id)
        extra = {}
        if ap and ap > 0 and resultado.custo_total > 0:
            sa = resultado.simular(ap)
            extra = dict(preco_aplicado=ap, margem_aplicada=sa.margem_pct, lucro_aplicado=sa.lucro)
        elif ap is not None:
            extra = dict(preco_aplicado=ap)
        preco = resultado.preco_para_margem(m)
        if preco is None or preco <= 0:        # margem impossível, ou produto ainda sem custo
            linhas.append(PrecoFaixa(f, m, f.id in proprias, preco, None, None, None, None, **extra))
            continue
        s = resultado.simular(preco)
        md = 1 - (resultado.pct_cv + resultado.pct_cf + m) / 100
        linhas.append(PrecoFaixa(f, m, f.id in proprias, preco, s.lucro, s.margem_contribuicao,
                                 s.margem_contribuicao_pct, 1 / md, **extra))
    return linhas


# ---------------------------------------------------------------------------- arredondamento
ARREDONDAMENTOS = {"centavos": "centavos (sem arredondar)", "90": "terminar em ,90 (para cima)",
                   "inteiro": "real inteiro (para cima)"}


def arredondar(valor: float, modo: str = "centavos") -> float:
    import math
    if modo == "inteiro":
        return float(math.ceil(valor - 1e-9))
    if modo == "90":
        base = math.floor(valor)
        return base + 0.90 if valor <= base + 0.90 + 1e-9 else base + 1.90
    return round(valor + 1e-9, 2)
