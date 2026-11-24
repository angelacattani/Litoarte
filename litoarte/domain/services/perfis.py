"""Perfis de venda (canais) e seus custos variáveis."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import CustoVariavel, PerfilVenda, Produto
from .cadastros import ErroValidacao


def listar(sessao: Session) -> list[PerfilVenda]:
    return list(sessao.scalars(select(PerfilVenda).options(selectinload(PerfilVenda.custos))
                               .order_by(PerfilVenda.padrao.desc(), PerfilVenda.nome)))


def resumo(perfil: PerfilVenda) -> tuple[float, float]:
    """(%CV, CV fixo em R$/un) considerando só custos ativos."""
    ativos = [c for c in perfil.custos if c.ativo]
    return (sum(c.valor for c in ativos if c.tipo == "percentual"),
            sum(c.valor for c in ativos if c.tipo == "valor_fixo"))


def _nome_livre(sessao: Session, nome: str, ignorar_id: int | None = None) -> str:
    nome = " ".join((nome or "").split())
    if not nome:
        raise ErroValidacao([("nome", "obrigatório")])
    outro = sessao.scalar(select(PerfilVenda).where(func.lower(PerfilVenda.nome) == nome.lower()))
    if outro is not None and outro.id != ignorar_id:
        raise ErroValidacao([("nome", f"já existe o perfil '{outro.nome}'")])
    return nome


def criar(sessao: Session, nome: str, copiar_de: int | None = None) -> PerfilVenda:
    p = PerfilVenda(nome=_nome_livre(sessao, nome), padrao=False)
    if copiar_de is not None:
        p.custos = list(sessao.get(PerfilVenda, copiar_de).custos)
    sessao.add(p)
    sessao.flush()
    return p


def renomear(sessao: Session, perfil_id: int, nome: str) -> None:
    sessao.get(PerfilVenda, perfil_id).nome = _nome_livre(sessao, nome, perfil_id)
    sessao.flush()


def definir_padrao(sessao: Session, perfil_id: int) -> None:
    for p in sessao.scalars(select(PerfilVenda).where(PerfilVenda.padrao)):
        p.padrao = False
    sessao.flush()                       # libera o índice único antes de marcar o novo
    sessao.get(PerfilVenda, perfil_id).padrao = True
    sessao.flush()


def definir_custo(sessao: Session, perfil_id: int, custo_id: int, incluir: bool) -> None:
    p, c = sessao.get(PerfilVenda, perfil_id), sessao.get(CustoVariavel, custo_id)
    if incluir and c not in p.custos:
        p.custos.append(c)
    elif not incluir and c in p.custos:
        p.custos.remove(c)
    sessao.flush()


def excluir(sessao: Session, perfil_id: int) -> None:
    p = sessao.get(PerfilVenda, perfil_id)
    if p.padrao:
        raise ErroValidacao([("", "o perfil padrão não pode ser excluído; defina outro como padrão antes")])
    em_uso = sessao.scalar(select(func.count()).select_from(Produto).where(Produto.perfil_venda_id == perfil_id))
    if em_uso:
        raise ErroValidacao([("", f"perfil usado por {em_uso} produto(s)")])
    sessao.delete(p)
    sessao.flush()
