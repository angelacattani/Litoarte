"""Ponte banco → motor de precificação.

Lê os cadastros ATUAIS e monta as entradas do motor. Como nenhum custo de produto é gravado,
qualquer alteração de insumo, etapa, custo fixo, custo variável ou configuração aparece no próximo
cálculo de todos os produtos que a usam (atualização em cascata por construção).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (Configuracao, CustoFixo, FichaMO, FichaMP, MaoDeObra, MateriaPrima, PerfilVenda, Produto)
from ..pricing.engine import (EntradaProduto, ItemCustoVariavel, LinhaMaoObra, LinhaMaterial, MetodoRateio, ModoPerda,
                              ModoQtd, RegrasEmpresa, ResultadoPreco, calcular)


def configuracao(sessao: Session) -> Configuracao:
    """Registro único de configuração (criado com os padrões se não existir)."""
    cfg = sessao.get(Configuracao, 1)
    if cfg is None:
        cfg = Configuracao(id=1)
        sessao.add(cfg)
        sessao.flush()
    return cfg


def regras_empresa(sessao: Session) -> RegrasEmpresa:
    cfg = configuracao(sessao)
    cft = sessao.scalar(select(func.coalesce(func.sum(CustoFixo.valor_mensal), 0.0)).where(CustoFixo.ativo)) or 0.0
    cap_horas = cfg.capacidade_horas_mes
    if cap_horas is None:  # soma das etapas: colaboradores × horas produtivas
        cap_horas = sessao.scalar(
            select(func.sum(MaoDeObra.qtd_colaboradores * MaoDeObra.horas_produtivas_mes))
            .where(MaoDeObra.ativo, MaoDeObra.horas_produtivas_mes.is_not(None))) or None
    return RegrasEmpresa(
        custo_fixo_total=float(cft), metodo_rateio=MetodoRateio(cfg.metodo_rateio),
        faturamento_base=cfg.faturamento_base_mensal, capacidade_horas=cap_horas,
        capacidade_unidades=cfg.capacidade_unidades_mes, margem_padrao_pct=cfg.margem_padrao_pct,
        modo_perda=ModoPerda(cfg.modo_perda))


def perfil_padrao(sessao: Session) -> PerfilVenda | None:
    return sessao.scalar(select(PerfilVenda).where(PerfilVenda.padrao).options(selectinload(PerfilVenda.custos)))


def entrada_do_produto(produto: Produto, perfil_default: PerfilVenda | None = None) -> EntradaProduto:
    """Converte o produto (com ficha carregada) na entrada do motor."""
    perfil = produto.perfil_venda or perfil_default
    mats = []
    for f in produto.materiais:
        mp = f.materia_prima
        mats.append(LinhaMaterial(
            sku=mp.sku, nome=mp.nome, custo_compra=mp.custo_compra, quantidade=f.quantidade,
            perda_pct=mp.perda_pct if f.perda_pct is None else f.perda_pct,
            fator_conversao=mp.fator_conversao, modo_qtd=ModoQtd(f.modo_qtd),
            unidade_consumo=mp.unidade_consumo.sigla if mp.unidade_consumo else "un",
            espacamento_cm=f.espacamento_cm or 0.0, folha_largura_m=mp.largura_m,
            folha_comprimento_m=mp.comprimento_m, folha_margem_cm=mp.margem_cm or 0.0))
    mos = [LinhaMaoObra(codigo=f.mao_de_obra.codigo, etapa=f.mao_de_obra.etapa,
                        custo_hora=f.mao_de_obra.custo_hora, horas=f.horas) for f in produto.mao_de_obra]
    cvs = [ItemCustoVariavel(c.codigo, c.descricao, c.tipo, c.valor)
           for c in (perfil.custos if perfil else []) if c.ativo]
    return EntradaProduto(sku=produto.sku, materiais=tuple(mats), mao_de_obra=tuple(mos),
                          custos_variaveis=tuple(cvs), largura_cm=produto.largura_cm, altura_cm=produto.altura_cm,
                          margem_pct=produto.margem_desejada_pct, preco_praticado=produto.preco_praticado)


_CARGA_FICHA = (
    selectinload(Produto.materiais).selectinload(FichaMP.materia_prima).selectinload(MateriaPrima.unidade_consumo),
    selectinload(Produto.mao_de_obra).selectinload(FichaMO.mao_de_obra),
    selectinload(Produto.perfil_venda).selectinload(PerfilVenda.custos),
)


def calcular_produto(sessao: Session, produto_id: int) -> ResultadoPreco:
    # populate_existing: o preço reflete sempre o estado atual do banco, mesmo com objetos já carregados
    produto = sessao.scalar(select(Produto).where(Produto.id == produto_id).options(*_CARGA_FICHA)
                            .execution_options(populate_existing=True))
    if produto is None:
        raise LookupError(f"produto {produto_id} não encontrado")
    return calcular(entrada_do_produto(produto, perfil_padrao(sessao)), regras_empresa(sessao))


def calcular_todos(sessao: Session, apenas_ativos: bool = True) -> list[tuple[Produto, ResultadoPreco]]:
    consulta = select(Produto).options(*_CARGA_FICHA).order_by(Produto.sku).execution_options(populate_existing=True)
    if apenas_ativos:
        consulta = consulta.where(Produto.ativo)
    regras, padrao = regras_empresa(sessao), perfil_padrao(sessao)
    return [(p, calcular(entrada_do_produto(p, padrao), regras)) for p in sessao.scalars(consulta)]


def produtos_que_usam_insumo(sessao: Session, materia_prima_id: int) -> list[Produto]:
    return list(sessao.scalars(select(Produto).join(FichaMP).where(FichaMP.materia_prima_id == materia_prima_id)
                               .distinct().order_by(Produto.sku)))


def produtos_que_usam_etapa(sessao: Session, mao_de_obra_id: int) -> list[Produto]:
    return list(sessao.scalars(select(Produto).join(FichaMO).where(FichaMO.mao_de_obra_id == mao_de_obra_id)
                               .distinct().order_by(Produto.sku)))
