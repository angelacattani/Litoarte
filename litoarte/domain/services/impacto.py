"""Relatório de impacto de reajustes (atualização em cascata).

Fluxo: `fotografar` os preços dos produtos afetados ANTES da alteração, aplicar a alteração na mesma
transação (flush) e `comparar` depois. O preço praticado nunca é alterado automaticamente: o relatório
mostra como a margem real nele muda.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FichaMO, FichaMP, Produto
from .precificacao import calcular_produto


@dataclass(frozen=True)
class Foto:
    sku: str
    nome: str
    preco: float | None
    cd: float
    praticado: float | None
    margem_praticada: float | None
    margem_desejada: float


@dataclass(frozen=True)
class LinhaImpacto:
    produto_id: int
    sku: str
    nome: str
    cd_antes: float
    cd_depois: float
    preco_antes: float | None
    preco_depois: float | None
    praticado: float | None
    margem_antes: float | None
    margem_depois: float | None
    margem_desejada: float

    @property
    def variacao_pct(self) -> float | None:
        if self.preco_antes and self.preco_depois is not None:
            return 100 * (self.preco_depois / self.preco_antes - 1)
        return None

    @property
    def abaixo_da_margem(self) -> bool:
        return self.margem_depois is not None and self.margem_depois < self.margem_desejada - 1e-9


def produtos_com_insumos(sessao: Session, insumo_ids) -> list[int]:
    ids = list(insumo_ids)
    if not ids:
        return []
    return list(sessao.scalars(select(FichaMP.produto_id).where(FichaMP.materia_prima_id.in_(ids)).distinct()))


def produtos_com_etapas(sessao: Session, etapa_ids) -> list[int]:
    ids = list(etapa_ids)
    if not ids:
        return []
    return list(sessao.scalars(select(FichaMO.produto_id).where(FichaMO.mao_de_obra_id.in_(ids)).distinct()))


def fotografar(sessao: Session, produto_ids) -> dict[int, Foto]:
    fotos = {}
    for pid in produto_ids:
        p = sessao.get(Produto, pid)
        r = calcular_produto(sessao, pid)
        m = r.simular(p.preco_praticado).margem_pct if p.preco_praticado and r.cd > 0 else None
        fotos[pid] = Foto(p.sku, p.nome, r.preco, r.cd, p.preco_praticado, m, r.pct_ml)
    return fotos


def comparar(sessao: Session, antes: dict[int, Foto], *, so_alterados: bool = True) -> list[LinhaImpacto]:
    """Recalcula os produtos fotografados (após o flush da alteração) e devolve as diferenças."""
    depois = fotografar(sessao, antes)
    linhas = []
    for pid, a in antes.items():
        d = depois[pid]
        if so_alterados and abs(d.cd - a.cd) < 1e-9 and a.preco == d.preco:
            continue
        linhas.append(LinhaImpacto(pid, a.sku, a.nome, a.cd, d.cd, a.preco, d.preco, a.praticado,
                                   a.margem_praticada, d.margem_praticada, d.margem_desejada))
    return sorted(linhas, key=lambda l: -(abs(l.variacao_pct) if l.variacao_pct is not None else 0))


def gravar_com_impacto(sessao: Session, modulo, bruto: dict, **kwargs):
    """Grava pelo serviço de cadastros e, se for reajuste de insumo/etapa, devolve o impacto nos produtos."""
    from .cadastros import gravar
    id_edicao = kwargs.get("id_edicao")
    fotos = {}
    if id_edicao is not None and modulo.chave == "materias_primas":
        fotos = fotografar(sessao, produtos_com_insumos(sessao, [id_edicao]))
    elif id_edicao is not None and modulo.chave == "mao_de_obra":
        fotos = fotografar(sessao, produtos_com_etapas(sessao, [id_edicao]))
    obj = gravar(sessao, modulo, bruto, **kwargs)
    return obj, (comparar(sessao, fotos) if fotos else [])
