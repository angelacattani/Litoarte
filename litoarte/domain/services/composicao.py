"""Composição de preço: rascunho editável, cálculo em tempo real, gravação, clonagem e comparativos.

A tela edita um `Rascunho` (em memória). O `Catalogo` é um retrato dos cadastros carregado uma vez
por tela, de modo que cada alteração recalcula o preço sem acessar o banco. Ao salvar, cabeçalho e
ficha técnica são gravados numa única transação (substituindo as linhas da ficha).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (MODOS_QTD, UNIDADES_TEMPO, FichaMO, FichaMP, Grupo, MaoDeObra, MateriaPrima, PerfilVenda,
                      Produto, Subgrupo)
from ..pricing.engine import (EntradaProduto, ItemCustoVariavel, LinhaMaoObra, LinhaMaterial, ModoQtd,
                              RegrasEmpresa, ResultadoPreco, calcular)
from .cadastros import ErroValidacao
from .precificacao import calcular_todos, regras_empresa


# ============================================================================ catálogo (retrato dos cadastros)
@dataclass(frozen=True)
class InsumoInfo:
    id: int
    sku: str
    nome: str
    custo_compra: float
    fator_conversao: float
    perda_pct: float
    unidade_consumo: str
    largura_m: float | None
    comprimento_m: float | None
    margem_cm: float
    ativo: bool

    @property
    def custo_consumo(self) -> float:
        return self.custo_compra / self.fator_conversao

    @property
    def folha(self) -> bool:
        return self.largura_m is not None and self.comprimento_m is not None


@dataclass(frozen=True)
class EtapaInfo:
    id: int
    codigo: str
    etapa: str
    custo_hora: float
    ativo: bool


@dataclass(frozen=True)
class PerfilInfo:
    id: int
    nome: str
    padrao: bool
    custos: tuple[ItemCustoVariavel, ...]


@dataclass
class Catalogo:
    insumos: dict[int, InsumoInfo]
    etapas: dict[int, EtapaInfo]
    perfis: dict[int, PerfilInfo]
    subgrupos: dict[int, tuple[str, str, str, str]]      # id -> (cód. grupo, nome grupo, cód. sub, nome sub)
    regras: RegrasEmpresa

    @property
    def perfil_padrao(self) -> PerfilInfo | None:
        return next((p for p in self.perfis.values() if p.padrao), None)


def carregar_catalogo(sessao: Session) -> Catalogo:
    insumos = {m.id: InsumoInfo(m.id, m.sku, m.nome, m.custo_compra, m.fator_conversao, m.perda_pct,
                                m.unidade_consumo.sigla, m.largura_m, m.comprimento_m, m.margem_cm or 0.0, m.ativo)
               for m in sessao.scalars(select(MateriaPrima).options(selectinload(MateriaPrima.unidade_consumo))
                                       .order_by(MateriaPrima.sku))}
    etapas = {e.id: EtapaInfo(e.id, e.codigo, e.etapa, e.custo_hora, e.ativo)
              for e in sessao.scalars(select(MaoDeObra).order_by(MaoDeObra.codigo))}
    perfis = {p.id: PerfilInfo(p.id, p.nome, p.padrao,
                               tuple(ItemCustoVariavel(c.codigo, c.descricao, c.tipo, c.valor)
                                     for c in p.custos if c.ativo))
              for p in sessao.scalars(select(PerfilVenda).options(selectinload(PerfilVenda.custos))
                                      .order_by(PerfilVenda.padrao.desc(), PerfilVenda.nome))}
    subgrupos = {s.id: (s.grupo.codigo, s.grupo.nome, s.codigo, s.nome)
                 for s in sessao.scalars(select(Subgrupo).join(Grupo).options(selectinload(Subgrupo.grupo))
                                         .order_by(Grupo.codigo, Subgrupo.codigo))}
    return Catalogo(insumos, etapas, perfis, subgrupos, regras_empresa(sessao))


# ============================================================================ rascunho
@dataclass
class LinhaMat:
    insumo_id: int | None = None
    modo_qtd: str = "fixa"
    quantidade: float | None = None
    perda_pct: float | None = None          # None = perda do insumo
    espacamento_cm: float | None = 0.0


@dataclass
class LinhaMO:
    etapa_id: int | None = None
    tempo: float | None = None
    unidade_tempo: str = "min"


@dataclass
class Rascunho:
    id: int | None = None
    sku: str = ""
    nome: str = ""
    subgrupo_id: int | None = None
    largura_cm: float | None = None
    altura_cm: float | None = None
    perfil_venda_id: int | None = None      # None = perfil padrão
    margem_desejada_pct: float | None = None
    preco_praticado: float | None = None
    ativo: bool = True
    materiais: list[LinhaMat] = field(default_factory=list)
    mao_de_obra: list[LinhaMO] = field(default_factory=list)


def rascunho_de_produto(sessao: Session, produto_id: int) -> Rascunho:
    p = sessao.scalar(select(Produto).where(Produto.id == produto_id)
                      .options(selectinload(Produto.materiais), selectinload(Produto.mao_de_obra))
                      .execution_options(populate_existing=True))
    if p is None:
        raise LookupError(f"produto {produto_id} não encontrado")
    return Rascunho(
        id=p.id, sku=p.sku, nome=p.nome, subgrupo_id=p.subgrupo_id, largura_cm=p.largura_cm, altura_cm=p.altura_cm,
        perfil_venda_id=p.perfil_venda_id, margem_desejada_pct=p.margem_desejada_pct,
        preco_praticado=p.preco_praticado, ativo=p.ativo,
        materiais=[LinhaMat(f.materia_prima_id, f.modo_qtd, _arred(f.quantidade), f.perda_pct, f.espacamento_cm)
                   for f in p.materiais],
        mao_de_obra=[LinhaMO(f.mao_de_obra_id, _arred(f.tempo), f.unidade_tempo) for f in p.mao_de_obra])


def _arred(v: float | None) -> float | None:
    """Remove ruído binário (12 × 0,8 = 9,600000000000001) para exibição e edição."""
    return None if v is None else round(v, 9)


# ============================================================================ cálculo em tempo real
def _horas(l: LinhaMO) -> float:
    t = l.tempo or 0.0
    return t / 60 if l.unidade_tempo == "min" else t


def entrada(cat: Catalogo, r: Rascunho, perfil_id: int | None = None) -> EntradaProduto:
    mats = []
    for l in r.materiais:
        ins = cat.insumos.get(l.insumo_id)
        if ins is None or l.quantidade is None:
            continue                        # linha incompleta: ignorada até ser preenchida
        mats.append(LinhaMaterial(
            sku=ins.sku, nome=ins.nome, custo_compra=ins.custo_compra, quantidade=l.quantidade,
            perda_pct=ins.perda_pct if l.perda_pct is None else l.perda_pct, fator_conversao=ins.fator_conversao,
            modo_qtd=ModoQtd(l.modo_qtd), unidade_consumo=ins.unidade_consumo, espacamento_cm=l.espacamento_cm or 0.0,
            folha_largura_m=ins.largura_m, folha_comprimento_m=ins.comprimento_m, folha_margem_cm=ins.margem_cm))
    mos = [LinhaMaoObra(cat.etapas[l.etapa_id].codigo, cat.etapas[l.etapa_id].etapa,
                        cat.etapas[l.etapa_id].custo_hora, _horas(l))
           for l in r.mao_de_obra if l.etapa_id in cat.etapas and l.tempo is not None]
    pid = perfil_id if perfil_id is not None else r.perfil_venda_id
    perfil = cat.perfis.get(pid) if pid is not None else cat.perfil_padrao
    return EntradaProduto(sku=r.sku or "(novo)", materiais=tuple(mats), mao_de_obra=tuple(mos),
                          custos_variaveis=perfil.custos if perfil else (), largura_cm=r.largura_cm,
                          altura_cm=r.altura_cm, margem_pct=r.margem_desejada_pct, preco_praticado=r.preco_praticado)


def calcular_rascunho(cat: Catalogo, r: Rascunho, *, perfil_id: int | None = None,
                      margem_pct: float | None = None) -> ResultadoPreco:
    """Preço do rascunho. `margem_pct` permite simular outra margem sem alterar o rascunho."""
    e = entrada(cat, r, perfil_id)
    if margem_pct is not None:
        e = replace(e, margem_pct=margem_pct)
    res = calcular(e, cat.regras)
    avisos = list(res.alertas)
    incompletas = sum(1 for l in r.materiais if l.insumo_id is None or l.quantidade is None) + \
        sum(1 for l in r.mao_de_obra if l.etapa_id is None or l.tempo is None)
    if incompletas:
        avisos.append(f"{incompletas} linha(s) da ficha incompleta(s), fora do cálculo")
    inativos = [cat.insumos[l.insumo_id].sku for l in r.materiais
                if l.insumo_id in cat.insumos and not cat.insumos[l.insumo_id].ativo]
    inativos += [cat.etapas[l.etapa_id].codigo for l in r.mao_de_obra
                 if l.etapa_id in cat.etapas and not cat.etapas[l.etapa_id].ativo]
    if inativos:
        avisos.append("itens inativos na ficha: " + ", ".join(inativos))
    return replace(res, alertas=tuple(avisos))


@dataclass(frozen=True)
class Canal:
    perfil_id: int
    nome: str
    padrao: bool
    atual: bool
    resultado: ResultadoPreco
    margem_no_praticado: float | None


def comparar_canais(cat: Catalogo, r: Rascunho) -> list[Canal]:
    atual = r.perfil_venda_id if r.perfil_venda_id is not None else (cat.perfil_padrao.id if cat.perfil_padrao else None)
    canais = []
    for p in cat.perfis.values():
        res = calcular_rascunho(cat, r, perfil_id=p.id)
        m = res.simular(r.preco_praticado).margem_pct if r.preco_praticado and res.cd > 0 else None
        canais.append(Canal(p.id, p.nome, p.padrao, p.id == atual, res, m))
    return canais


# ============================================================================ validação e gravação
def validar(sessao: Session, r: Rascunho) -> list[tuple[str, str]]:
    erros: list[tuple[str, str]] = []
    sku = (r.sku or "").strip()
    if not sku:
        erros.append(("sku", "obrigatório"))
    else:
        outro = sessao.scalar(select(Produto).where(Produto.sku == sku))
        if outro is not None and outro.id != r.id:
            erros.append(("sku", f"já existe o produto {sku}"))
    if not (r.nome or "").strip():
        erros.append(("nome", "obrigatório"))
    if r.subgrupo_id is None or sessao.get(Subgrupo, r.subgrupo_id) is None:
        erros.append(("subgrupo_id", "selecione grupo e subgrupo"))
    for campo in ("largura_cm", "altura_cm"):
        v = getattr(r, campo)
        if v is not None and v <= 0:
            erros.append((campo, "deve ser maior que zero"))
    if r.margem_desejada_pct is not None and not 0 <= r.margem_desejada_pct < 100:
        erros.append(("margem_desejada_pct", "entre 0 e 100 %"))
    if r.preco_praticado is not None and r.preco_praticado < 0:
        erros.append(("preco_praticado", "não pode ser negativo"))
    if r.perfil_venda_id is not None and sessao.get(PerfilVenda, r.perfil_venda_id) is None:
        erros.append(("perfil_venda_id", "perfil inexistente"))
    for i, l in enumerate(r.materiais, start=1):
        if l.insumo_id is None or sessao.get(MateriaPrima, l.insumo_id) is None:
            erros.append((f"material {i}", "selecione o insumo"))
        if l.quantidade is None or l.quantidade < 0:
            erros.append((f"material {i}", "quantidade obrigatória (≥ 0)"))
        if l.modo_qtd not in MODOS_QTD:
            erros.append((f"material {i}", "modo inválido"))
        if l.perda_pct is not None and not 0 <= l.perda_pct < 100:
            erros.append((f"material {i}", "perda entre 0 e 100 %"))
        if (l.espacamento_cm or 0) < 0:
            erros.append((f"material {i}", "espaçamento negativo"))
    for i, l in enumerate(r.mao_de_obra, start=1):
        if l.etapa_id is None or sessao.get(MaoDeObra, l.etapa_id) is None:
            erros.append((f"mão de obra {i}", "selecione a etapa"))
        if l.tempo is None or l.tempo < 0:
            erros.append((f"mão de obra {i}", "tempo obrigatório (≥ 0)"))
        if l.unidade_tempo not in UNIDADES_TEMPO:
            erros.append((f"mão de obra {i}", "unidade de tempo inválida"))
    return erros


def salvar(sessao: Session, r: Rascunho) -> Produto:
    """Grava cabeçalho + ficha técnica (substitui as linhas). Levanta ErroValidacao. Não faz commit."""
    erros = validar(sessao, r)
    if erros:
        raise ErroValidacao(erros)
    p = sessao.get(Produto, r.id) if r.id else Produto()
    p.sku, p.nome = r.sku.strip(), " ".join(r.nome.split())
    p.subgrupo_id, p.largura_cm, p.altura_cm = r.subgrupo_id, r.largura_cm, r.altura_cm
    p.perfil_venda_id, p.margem_desejada_pct = r.perfil_venda_id, r.margem_desejada_pct
    p.preco_praticado, p.ativo = r.preco_praticado, r.ativo
    p.materiais = [FichaMP(materia_prima_id=l.insumo_id, modo_qtd=l.modo_qtd, quantidade=l.quantidade,
                           perda_pct=l.perda_pct, espacamento_cm=l.espacamento_cm or 0.0, ordem=i)
                   for i, l in enumerate(r.materiais, start=1)]
    p.mao_de_obra = [FichaMO(mao_de_obra_id=l.etapa_id, tempo=l.tempo, unidade_tempo=l.unidade_tempo, ordem=i)
                     for i, l in enumerate(r.mao_de_obra, start=1)]
    if r.id is None:
        sessao.add(p)
    sessao.flush()
    r.id = p.id
    return p


def excluir(sessao: Session, produto_id: int) -> None:
    p = sessao.get(Produto, produto_id)
    if p is not None:
        sessao.delete(p)          # a ficha técnica sai junto (CASCADE)
        sessao.flush()


# ============================================================================ clonagem
def sugerir_sku(sessao: Session, base: str) -> str:
    raiz = re.sub(r"-C\d+$", "", base.strip())
    existentes = set(sessao.scalars(select(Produto.sku).where(Produto.sku.like(f"{raiz}-C%"))))
    n = 1
    while f"{raiz}-C{n}" in existentes:
        n += 1
    return f"{raiz}-C{n}"


def clonar(sessao: Session, origem_id: int, *, sku: str, nome: str, subgrupo_id: int | None = None,
           largura_cm: float | None = None, altura_cm: float | None = None, copiar_materiais: bool = True,
           copiar_mao_de_obra: bool = True, copiar_perfil_margem: bool = True, copiar_preco: bool = False) -> Produto:
    """Cria um produto a partir de outro (grupo/subgrupo, ficha técnica e configurações de venda)."""
    base = rascunho_de_produto(sessao, origem_id)
    novo = Rascunho(
        sku=sku, nome=nome, subgrupo_id=subgrupo_id or base.subgrupo_id,
        largura_cm=base.largura_cm if largura_cm is None else largura_cm,
        altura_cm=base.altura_cm if altura_cm is None else altura_cm,
        perfil_venda_id=base.perfil_venda_id if copiar_perfil_margem else None,
        margem_desejada_pct=base.margem_desejada_pct if copiar_perfil_margem else None,
        preco_praticado=base.preco_praticado if copiar_preco else None,
        materiais=[replace(l) for l in base.materiais] if copiar_materiais else [],
        mao_de_obra=[replace(l) for l in base.mao_de_obra] if copiar_mao_de_obra else [])
    p = salvar(sessao, novo)
    p.clonado_de_id = origem_id
    sessao.flush()
    return p


# ============================================================================ lista de produtos
@dataclass(frozen=True)
class ResumoProduto:
    id: int
    sku: str
    nome: str
    grupo: str
    subgrupo: str
    ativo: bool
    cd: float
    preco_sugerido: float | None
    preco_praticado: float | None
    margem_desejada: float
    margem_praticada: float | None
    alertas: tuple[str, ...]

    @property
    def abaixo_da_margem(self) -> bool:
        return self.margem_praticada is not None and self.margem_praticada < self.margem_desejada - 1e-9


def resumo_produtos(sessao: Session, apenas_ativos: bool = False) -> list[ResumoProduto]:
    linhas = []
    for p, r in calcular_todos(sessao, apenas_ativos=apenas_ativos):
        m = r.simular(p.preco_praticado).margem_pct if p.preco_praticado else None
        linhas.append(ResumoProduto(p.id, p.sku, p.nome, f"{p.subgrupo.grupo.codigo} - {p.subgrupo.grupo.nome}",
                                    f"{p.subgrupo.codigo} - {p.subgrupo.nome}", p.ativo, r.cd, r.preco,
                                    p.preco_praticado, r.pct_ml, m, r.alertas))
    return linhas
