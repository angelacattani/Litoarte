"""Modelo relacional (SQLAlchemy 2) — ver docs/especificacao_v2.md, seção 1.

Convenções:
- percentuais em pontos percentuais (15.0 = 15 %), sufixo `_pct`;
- valores monetários e quantidades em Numeric (asdecimal=False -> float no Python);
- códigos/SKU únicos; itens referenciados por fichas usam FK RESTRICT (inativar, não apagar);
- custos de produto NÃO são persistidos: o motor (domain/pricing) calcula a partir destes dados.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, MetaData,
                        Numeric, String, Table, Text, UniqueConstraint, event, false, func, inspect, text, true)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

# Nomes determinísticos de constraints: necessários para migrações (Alembic) em SQLite e PostgreSQL
CONVENCAO = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Num = Numeric(16, 6, asdecimal=False)

GRANDEZAS = ("unidade", "area", "comprimento", "massa", "volume")
CATEGORIAS_CV = ("imposto", "cartao", "comissao", "marketplace", "frete", "outro")
TIPOS_CV = ("percentual", "valor_fixo")
MODOS_QTD = ("fixa", "area", "perimetro", "aproveitamento")
UNIDADES_TEMPO = ("min", "h")
METODOS_RATEIO = ("pct_faturamento", "hora_produtiva", "unidade")
MODOS_PERDA = ("sobre_compra", "acrescimo")
MODOS_CUSTO_MO = ("informado", "calculado")


def _em(valores: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in valores) + ")"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO)


class ComDatas:
    # default em Python (horário local da máquina do sistema); o CURRENT_TIMESTAMP do SQLite é UTC
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now(),
                                                    onupdate=datetime.now)


# ---------------------------------------------------------------------------- apoio
class UnidadeMedida(Base):
    __tablename__ = "unidade_medida"
    id: Mapped[int] = mapped_column(primary_key=True)
    sigla: Mapped[str] = mapped_column(String(10), unique=True)
    descricao: Mapped[str] = mapped_column(String(60))
    grandeza: Mapped[str] = mapped_column(String(12), default="unidade")
    __table_args__ = (CheckConstraint(f"grandeza IN {_em(GRANDEZAS)}", name="grandeza"),)


class Fornecedor(ComDatas, Base):
    __tablename__ = "fornecedor"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    documento: Mapped[str | None] = mapped_column(String(20))
    contato: Mapped[str | None] = mapped_column(String(200))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


# ---------------------------------------------------------------------------- insumos
class MateriaPrima(ComDatas, Base):
    __tablename__ = "materia_prima"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(160))
    unidade_compra_id: Mapped[int] = mapped_column(ForeignKey("unidade_medida.id", ondelete="RESTRICT"))
    unidade_consumo_id: Mapped[int] = mapped_column(ForeignKey("unidade_medida.id", ondelete="RESTRICT"))
    fator_conversao: Mapped[float] = mapped_column(Num, default=1.0, server_default=true())
    custo_compra: Mapped[float] = mapped_column(Num)
    perda_pct: Mapped[float] = mapped_column(Num, default=0.0, server_default=text("0"))
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedor.id", ondelete="SET NULL"))
    largura_m: Mapped[float | None] = mapped_column(Num)       # folha/chapa/bobina
    comprimento_m: Mapped[float | None] = mapped_column(Num)
    margem_cm: Mapped[float] = mapped_column(Num, default=0.0, server_default=text("0"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    unidade_compra: Mapped[UnidadeMedida] = relationship(foreign_keys=[unidade_compra_id])
    unidade_consumo: Mapped[UnidadeMedida] = relationship(foreign_keys=[unidade_consumo_id])
    fornecedor: Mapped[Fornecedor | None] = relationship()
    historico: Mapped[list["HistoricoCustoMP"]] = relationship(
        back_populates="materia_prima", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("fator_conversao > 0", name="fator_conversao_positivo"),
        CheckConstraint("custo_compra >= 0", name="custo_compra_nao_negativo"),
        CheckConstraint("perda_pct >= 0 AND perda_pct < 100", name="perda_pct_faixa"),
        CheckConstraint("margem_cm >= 0", name="margem_cm_nao_negativa"),
        CheckConstraint("(largura_m IS NULL OR largura_m > 0) AND (comprimento_m IS NULL OR comprimento_m > 0)",
                        name="dimensoes_positivas"),
    )

    @property
    def custo_consumo(self) -> float:
        """R$ por unidade de consumo (frasco R$ 280 / 1000 ml = R$ 0,28/ml)."""
        return self.custo_compra / self.fator_conversao


class HistoricoCustoMP(Base):
    __tablename__ = "historico_custo_mp"
    id: Mapped[int] = mapped_column(primary_key=True)
    materia_prima_id: Mapped[int] = mapped_column(ForeignKey("materia_prima.id", ondelete="CASCADE"), index=True)
    custo_anterior: Mapped[float | None] = mapped_column(Num)
    custo_novo: Mapped[float] = mapped_column(Num)
    origem: Mapped[str] = mapped_column(String(20), default="manual")
    alterado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    materia_prima: Mapped[MateriaPrima] = relationship(back_populates="historico")


class MaoDeObra(ComDatas, Base):
    __tablename__ = "mao_de_obra"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    etapa: Mapped[str] = mapped_column(String(120))
    modo_custo: Mapped[str] = mapped_column(String(12), default="informado")
    custo_hora_informado: Mapped[float | None] = mapped_column(Num)   # encargos inclusos
    salario_mensal: Mapped[float | None] = mapped_column(Num)
    encargos_pct: Mapped[float | None] = mapped_column(Num)
    horas_produtivas_mes: Mapped[float | None] = mapped_column(Num)
    qtd_colaboradores: Mapped[float] = mapped_column(Num, default=1.0, server_default=true())
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    historico: Mapped[list["HistoricoCustoMO"]] = relationship(
        back_populates="mao_de_obra", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        CheckConstraint(f"modo_custo IN {_em(MODOS_CUSTO_MO)}", name="modo_custo"),
        CheckConstraint("modo_custo <> 'informado' OR (custo_hora_informado IS NOT NULL AND custo_hora_informado >= 0)",
                        name="informado_exige_custo_hora"),
        CheckConstraint("modo_custo <> 'calculado' OR (salario_mensal IS NOT NULL AND salario_mensal >= 0 "
                        "AND horas_produtivas_mes IS NOT NULL AND horas_produtivas_mes > 0)",
                        name="calculado_exige_salario_horas"),
        CheckConstraint("encargos_pct IS NULL OR encargos_pct >= 0", name="encargos_nao_negativos"),
        CheckConstraint("qtd_colaboradores >= 0", name="qtd_colaboradores_nao_negativa"),
    )

    @property
    def custo_hora(self) -> float:
        return custo_hora_mo(self.modo_custo, self.custo_hora_informado, self.salario_mensal,
                             self.encargos_pct, self.horas_produtivas_mes)

    @property
    def custo_minuto(self) -> float:
        return self.custo_hora / 60


def custo_hora_mo(modo, informado, salario, encargos_pct, horas) -> float:
    if modo == "informado":
        return float(informado or 0.0)
    return float(salario or 0.0) * (1 + float(encargos_pct or 0.0) / 100) / float(horas)


class HistoricoCustoMO(Base):
    __tablename__ = "historico_custo_mo"
    id: Mapped[int] = mapped_column(primary_key=True)
    mao_de_obra_id: Mapped[int] = mapped_column(ForeignKey("mao_de_obra.id", ondelete="CASCADE"), index=True)
    custo_hora_anterior: Mapped[float | None] = mapped_column(Num)
    custo_hora_novo: Mapped[float] = mapped_column(Num)
    origem: Mapped[str] = mapped_column(String(20), default="manual")
    alterado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    mao_de_obra: Mapped[MaoDeObra] = relationship(back_populates="historico")


# ---------------------------------------------------------------------------- custos da empresa
class CustoFixo(ComDatas, Base):
    __tablename__ = "custo_fixo"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    descricao: Mapped[str] = mapped_column(String(160))
    categoria: Mapped[str | None] = mapped_column(String(40))
    valor_mensal: Mapped[float] = mapped_column(Num)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    __table_args__ = (CheckConstraint("valor_mensal >= 0", name="valor_nao_negativo"),)


perfil_venda_item = Table(
    "perfil_venda_item", Base.metadata,
    Column("perfil_venda_id", ForeignKey("perfil_venda.id", ondelete="CASCADE"), primary_key=True),
    Column("custo_variavel_id", ForeignKey("custo_variavel.id", ondelete="RESTRICT"), primary_key=True),
)


class CustoVariavel(ComDatas, Base):
    __tablename__ = "custo_variavel"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    descricao: Mapped[str] = mapped_column(String(160))
    categoria: Mapped[str] = mapped_column(String(20), default="outro")
    tipo: Mapped[str] = mapped_column(String(12), default="percentual")
    valor: Mapped[float] = mapped_column(Num)        # % do preço ou R$ por unidade
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    __table_args__ = (
        CheckConstraint(f"categoria IN {_em(CATEGORIAS_CV)}", name="categoria"),
        CheckConstraint(f"tipo IN {_em(TIPOS_CV)}", name="tipo"),
        CheckConstraint("valor >= 0", name="valor_nao_negativo"),
        CheckConstraint("tipo <> 'percentual' OR valor < 100", name="percentual_menor_100"),
    )


class PerfilVenda(ComDatas, Base):
    __tablename__ = "perfil_venda"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    padrao: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    custos: Mapped[list[CustoVariavel]] = relationship(secondary=perfil_venda_item, order_by=CustoVariavel.codigo)
    __table_args__ = (
        # no máximo um perfil padrão
        Index("ux_perfil_venda_padrao", "padrao", unique=True,
              sqlite_where=text("padrao = 1"), postgresql_where=text("padrao")),
    )


# ---------------------------------------------------------------------------- classificação
class Grupo(ComDatas, Base):
    __tablename__ = "grupo"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(120))
    subgrupos: Mapped[list["Subgrupo"]] = relationship(back_populates="grupo", order_by="Subgrupo.codigo")


class Subgrupo(ComDatas, Base):
    __tablename__ = "subgrupo"
    id: Mapped[int] = mapped_column(primary_key=True)
    grupo_id: Mapped[int] = mapped_column(ForeignKey("grupo.id", ondelete="RESTRICT"))
    codigo: Mapped[str] = mapped_column(String(40))
    nome: Mapped[str] = mapped_column(String(120))
    grupo: Mapped[Grupo] = relationship(back_populates="subgrupos")
    __table_args__ = (UniqueConstraint("grupo_id", "codigo", name="uq_subgrupo_grupo_codigo"),)


# ---------------------------------------------------------------------------- produto e ficha técnica
class Produto(ComDatas, Base):
    __tablename__ = "produto"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(200))
    subgrupo_id: Mapped[int] = mapped_column(ForeignKey("subgrupo.id", ondelete="RESTRICT"), index=True)
    largura_cm: Mapped[float | None] = mapped_column(Num)
    altura_cm: Mapped[float | None] = mapped_column(Num)
    perfil_venda_id: Mapped[int | None] = mapped_column(ForeignKey("perfil_venda.id", ondelete="RESTRICT"))
    margem_desejada_pct: Mapped[float | None] = mapped_column(Num)       # None = padrão da configuração
    preco_praticado: Mapped[float | None] = mapped_column(Num)
    custo_atual: Mapped[float | None] = mapped_column(Num)        # custo usado hoje (sistema/planilha anterior)
    clonado_de_id: Mapped[int | None] = mapped_column(ForeignKey("produto.id", ondelete="SET NULL"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    subgrupo: Mapped[Subgrupo] = relationship()
    perfil_venda: Mapped[PerfilVenda | None] = relationship()
    clonado_de: Mapped["Produto | None"] = relationship(remote_side=[id])
    materiais: Mapped[list["FichaMP"]] = relationship(
        back_populates="produto", cascade="all, delete-orphan", passive_deletes=True, order_by="FichaMP.ordem")
    mao_de_obra: Mapped[list["FichaMO"]] = relationship(
        back_populates="produto", cascade="all, delete-orphan", passive_deletes=True, order_by="FichaMO.ordem")
    margens_faixas: Mapped[list["ProdutoFaixa"]] = relationship(
        back_populates="produto", cascade="all, delete-orphan", passive_deletes=True)

    __table_args__ = (
        CheckConstraint("margem_desejada_pct IS NULL OR (margem_desejada_pct >= 0 AND margem_desejada_pct < 100)",
                        name="margem_faixa"),
        CheckConstraint("(largura_cm IS NULL OR largura_cm > 0) AND (altura_cm IS NULL OR altura_cm > 0)",
                        name="dimensoes_positivas"),
        CheckConstraint("preco_praticado IS NULL OR preco_praticado >= 0", name="preco_nao_negativo"),
        CheckConstraint("custo_atual IS NULL OR custo_atual >= 0", name="custo_atual_nao_negativo"),
    )


class FichaMP(Base):
    __tablename__ = "ficha_mp"
    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id", ondelete="CASCADE"), index=True)
    materia_prima_id: Mapped[int] = mapped_column(ForeignKey("materia_prima.id", ondelete="RESTRICT"), index=True)
    modo_qtd: Mapped[str] = mapped_column(String(16), default="fixa")
    quantidade: Mapped[float] = mapped_column(Num)                # na unidade de consumo
    perda_pct: Mapped[float | None] = mapped_column(Num)          # None = perda do cadastro do insumo
    espacamento_cm: Mapped[float] = mapped_column(Num, default=0.0, server_default=text("0"))
    ordem: Mapped[int] = mapped_column(Integer, default=0)

    produto: Mapped[Produto] = relationship(back_populates="materiais")
    materia_prima: Mapped[MateriaPrima] = relationship()
    __table_args__ = (
        CheckConstraint(f"modo_qtd IN {_em(MODOS_QTD)}", name="modo_qtd"),
        CheckConstraint("quantidade >= 0", name="quantidade_nao_negativa"),
        CheckConstraint("perda_pct IS NULL OR (perda_pct >= 0 AND perda_pct < 100)", name="perda_pct_faixa"),
        CheckConstraint("espacamento_cm >= 0", name="espacamento_nao_negativo"),
    )


class FichaMO(Base):
    __tablename__ = "ficha_mo"
    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id", ondelete="CASCADE"), index=True)
    mao_de_obra_id: Mapped[int] = mapped_column(ForeignKey("mao_de_obra.id", ondelete="RESTRICT"), index=True)
    tempo: Mapped[float] = mapped_column(Num)
    unidade_tempo: Mapped[str] = mapped_column(String(3), default="min")
    ordem: Mapped[int] = mapped_column(Integer, default=0)

    produto: Mapped[Produto] = relationship(back_populates="mao_de_obra")
    mao_de_obra: Mapped[MaoDeObra] = relationship()
    __table_args__ = (
        CheckConstraint(f"unidade_tempo IN {_em(UNIDADES_TEMPO)}", name="unidade_tempo"),
        CheckConstraint("tempo >= 0", name="tempo_nao_negativo"),
    )

    @property
    def horas(self) -> float:
        return self.tempo / 60 if self.unidade_tempo == "min" else self.tempo


# ---------------------------------------------------------------------------- faixas de margem
class FaixaPreco(ComDatas, Base):
    """As 5 faixas de preço calculadas para todo produto (ex.: Atacado 15 %, Varejo 30 %)."""
    __tablename__ = "faixa_preco"
    id: Mapped[int] = mapped_column(primary_key=True)
    ordem: Mapped[int] = mapped_column(Integer, unique=True)
    nome: Mapped[str] = mapped_column(String(60))
    margem_pct: Mapped[float] = mapped_column(Num)
    __table_args__ = (CheckConstraint("margem_pct >= 0 AND margem_pct < 100", name="margem_faixa"),)


class ProdutoFaixa(Base):
    """Dados do produto numa faixa: margem própria (sobrepõe a geral) e/ou preço aplicado hoje."""
    __tablename__ = "produto_faixa"
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto.id", ondelete="CASCADE"), primary_key=True)
    faixa_id: Mapped[int] = mapped_column(ForeignKey("faixa_preco.id", ondelete="CASCADE"), primary_key=True)
    margem_pct: Mapped[float | None] = mapped_column(Num)            # None = margem geral da faixa
    preco_aplicado: Mapped[float | None] = mapped_column(Num)        # preço praticado nesta faixa
    produto: Mapped["Produto"] = relationship(back_populates="margens_faixas")
    faixa: Mapped[FaixaPreco] = relationship()
    __table_args__ = (
        CheckConstraint("margem_pct IS NULL OR (margem_pct >= 0 AND margem_pct < 100)", name="margem_faixa"),
        CheckConstraint("preco_aplicado IS NULL OR preco_aplicado >= 0", name="preco_aplicado_nao_negativo"),
    )


# ---------------------------------------------------------------------------- concorrência
concorrente_grupo = Table(
    "concorrente_grupo", Base.metadata,
    Column("concorrente_id", ForeignKey("concorrente.id", ondelete="CASCADE"), primary_key=True),
    Column("grupo_id", ForeignKey("grupo.id", ondelete="CASCADE"), primary_key=True),
)

FONTES_PRECO = ("manual", "mercadolivre", "google_shopping", "importacao")


class Concorrente(ComDatas, Base):
    """Concorrente (loja, marketplace, vendedor), associado aos grupos de produtos em que concorre."""
    __tablename__ = "concorrente"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True)
    site: Mapped[str | None] = mapped_column(String(255))
    observacao: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    grupos: Mapped[list[Grupo]] = relationship(secondary=concorrente_grupo, order_by=Grupo.codigo)


class PrecoConcorrente(Base):
    """Preço de produto similar de um concorrente, coletado manualmente ou na web."""
    __tablename__ = "preco_concorrente"
    id: Mapped[int] = mapped_column(primary_key=True)
    concorrente_id: Mapped[int] = mapped_column(ForeignKey("concorrente.id", ondelete="CASCADE"), index=True)
    grupo_id: Mapped[int] = mapped_column(ForeignKey("grupo.id", ondelete="CASCADE"), index=True)
    subgrupo_id: Mapped[int | None] = mapped_column(ForeignKey("subgrupo.id", ondelete="SET NULL"))
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produto.id", ondelete="SET NULL"), index=True)
    descricao: Mapped[str] = mapped_column(String(300))               # título do produto similar
    preco: Mapped[float] = mapped_column(Num)
    url: Mapped[str | None] = mapped_column(String(1000))
    fonte: Mapped[str] = mapped_column(String(20), default="manual")
    coletado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    concorrente: Mapped[Concorrente] = relationship()
    grupo: Mapped[Grupo] = relationship()
    subgrupo: Mapped["Subgrupo | None"] = relationship()
    produto: Mapped["Produto | None"] = relationship()
    __table_args__ = (
        CheckConstraint("preco > 0", name="preco_positivo"),
        CheckConstraint(f"fonte IN {_em(FONTES_PRECO)}", name="fonte"),
    )


# ---------------------------------------------------------------------------- configuração e auditoria
class Configuracao(ComDatas, Base):
    """Registro único (id = 1) com as regras de rateio, margem e perda."""
    __tablename__ = "configuracao"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    metodo_rateio: Mapped[str] = mapped_column(String(20), default="pct_faturamento")
    faturamento_base_mensal: Mapped[float | None] = mapped_column(Num)
    capacidade_horas_mes: Mapped[float | None] = mapped_column(Num)      # None = soma das etapas de MO
    capacidade_unidades_mes: Mapped[float | None] = mapped_column(Num)
    margem_padrao_pct: Mapped[float] = mapped_column(Num, default=20.0, server_default=text("20"))
    modo_perda: Mapped[str] = mapped_column(String(16), default="sobre_compra")
    # busca de preços na web (credenciais ficam só neste banco local)
    ml_client_id: Mapped[str | None] = mapped_column(String(100))
    ml_client_secret: Mapped[str | None] = mapped_column(String(200))
    ml_access_token: Mapped[str | None] = mapped_column(String(500))
    ml_token_expira_em: Mapped[datetime | None] = mapped_column(DateTime)
    serpapi_chave: Mapped[str | None] = mapped_column(String(200))
    __table_args__ = (
        CheckConstraint("id = 1", name="registro_unico"),
        CheckConstraint(f"metodo_rateio IN {_em(METODOS_RATEIO)}", name="metodo_rateio"),
        CheckConstraint(f"modo_perda IN {_em(MODOS_PERDA)}", name="modo_perda"),
        CheckConstraint("margem_padrao_pct >= 0 AND margem_padrao_pct < 100", name="margem_faixa"),
    )


class ImportacaoLog(Base):
    __tablename__ = "importacao_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    modulo: Mapped[str] = mapped_column(String(40))
    arquivo: Mapped[str] = mapped_column(String(255))
    modo: Mapped[str] = mapped_column(String(20))
    linhas_lidas: Mapped[int] = mapped_column(Integer, default=0)
    inseridas: Mapped[int] = mapped_column(Integer, default=0)
    atualizadas: Mapped[int] = mapped_column(Integer, default=0)
    rejeitadas: Mapped[int] = mapped_column(Integer, default=0)
    usuario: Mapped[str | None] = mapped_column(String(80))
    detalhes: Mapped[str | None] = mapped_column(Text)
    executado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())


# ---------------------------------------------------------------------------- histórico automático
_CAMPOS_CUSTO_MO = ("modo_custo", "custo_hora_informado", "salario_mensal", "encargos_pct", "horas_produtivas_mes")


@event.listens_for(Session, "before_flush")
def _registrar_historico(sessao: Session, _ctx, _inst) -> None:
    """Grava histórico de custo na MESMA transação da alteração (manual ou importação).

    A origem pode ser indicada antes do flush: `insumo.origem_alteracao = "importacao"`.
    """
    for obj in list(sessao.dirty):
        estado = inspect(obj)
        if isinstance(obj, MateriaPrima):
            h = estado.attrs.custo_compra.history
            if h.has_changes() and h.deleted and h.deleted[0] != obj.custo_compra:
                sessao.add(HistoricoCustoMP(materia_prima=obj, custo_anterior=h.deleted[0],
                                            custo_novo=obj.custo_compra,
                                            origem=getattr(obj, "origem_alteracao", "manual")))
        elif isinstance(obj, MaoDeObra):
            if not any(estado.attrs[c].history.has_changes() for c in _CAMPOS_CUSTO_MO):
                continue
            antigo = {c: (estado.attrs[c].history.deleted[0] if estado.attrs[c].history.deleted
                          else getattr(obj, c)) for c in _CAMPOS_CUSTO_MO}
            try:
                anterior = custo_hora_mo(antigo["modo_custo"], antigo["custo_hora_informado"], antigo["salario_mensal"],
                                         antigo["encargos_pct"], antigo["horas_produtivas_mes"])
            except (TypeError, ZeroDivisionError):
                anterior = None
            if anterior is None or abs(anterior - obj.custo_hora) > 1e-9:
                sessao.add(HistoricoCustoMO(mao_de_obra=obj, custo_hora_anterior=anterior,
                                            custo_hora_novo=obj.custo_hora,
                                            origem=getattr(obj, "origem_alteracao", "manual")))
