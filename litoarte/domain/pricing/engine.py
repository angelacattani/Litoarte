"""Motor de precificação — implementação da seção 3 de docs/especificacao_v2.md.

Puro: não acessa banco nem interface. Recebe dados já carregados (dataclasses) e devolve
resultados imutáveis. Isso permite recalcular em tempo real na tela de composição (sem salvar)
e testar cada fórmula isoladamente.

Convenção: campos `_pct` em pontos percentuais (15.0 = 15 %); internamente usa frações.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .encaixe import pecas_por_folha


class ModoPerda(StrEnum):
    SOBRE_COMPRA = "sobre_compra"   # perda = fração do material comprado: q / (1 − p)
    ACRESCIMO = "acrescimo"         # perda = acréscimo sobre o consumo:   q · (1 + p)


class MetodoRateio(StrEnum):
    PCT_FATURAMENTO = "pct_faturamento"   # %CF = CFT / faturamento base (denominador)
    HORA_PRODUTIVA = "hora_produtiva"     # CFu = CFT / H_cap · horas do produto (numerador)
    UNIDADE = "unidade"                   # CFu = CFT / U_cap (numerador)


class ModoQtd(StrEnum):
    FIXA = "fixa"
    AREA = "area"
    PERIMETRO = "perimetro"
    APROVEITAMENTO = "aproveitamento"


# ============================================================================ entradas
@dataclass(frozen=True)
class LinhaMaterial:
    sku: str
    nome: str
    custo_compra: float
    quantidade: float
    perda_pct: float = 0.0                 # perda efetiva da linha (já resolvida: linha ou cadastro)
    fator_conversao: float = 1.0
    modo_qtd: ModoQtd = ModoQtd.FIXA
    unidade_consumo: str = "un"
    espacamento_cm: float = 0.0
    folha_largura_m: float | None = None   # aproveitamento
    folha_comprimento_m: float | None = None
    folha_margem_cm: float = 0.0


@dataclass(frozen=True)
class LinhaMaoObra:
    codigo: str
    etapa: str
    custo_hora: float
    horas: float


@dataclass(frozen=True)
class ItemCustoVariavel:
    codigo: str
    descricao: str
    tipo: str          # "percentual" | "valor_fixo"
    valor: float       # % do preço ou R$/un


@dataclass(frozen=True)
class RegrasEmpresa:
    """Parâmetros globais: configuração + custos fixos agregados."""
    custo_fixo_total: float
    metodo_rateio: MetodoRateio = MetodoRateio.PCT_FATURAMENTO
    faturamento_base: float | None = None
    capacidade_horas: float | None = None
    capacidade_unidades: float | None = None
    margem_padrao_pct: float = 20.0
    modo_perda: ModoPerda = ModoPerda.SOBRE_COMPRA


@dataclass(frozen=True)
class EntradaProduto:
    sku: str
    materiais: tuple[LinhaMaterial, ...] = ()
    mao_de_obra: tuple[LinhaMaoObra, ...] = ()
    custos_variaveis: tuple[ItemCustoVariavel, ...] = ()
    largura_cm: float | None = None
    altura_cm: float | None = None
    margem_pct: float | None = None        # None = margem padrão
    preco_praticado: float | None = None


# ============================================================================ resultados
@dataclass(frozen=True)
class ResultadoMaterial:
    linha: LinhaMaterial
    qtd_efetiva: float          # após o modo (área, perímetro, 1/peças)
    qtd_comprada: float         # após a perda
    custo_consumo: float        # R$ por unidade de consumo
    custo: float
    pecas_folha: int | None = None
    disposicao: str | None = None
    aproveitamento_pct: float | None = None
    alerta: str | None = None


@dataclass(frozen=True)
class ResultadoMaoObra:
    linha: LinhaMaoObra
    custo: float


@dataclass(frozen=True)
class Simulacao:
    preco: float
    lucro: float
    margem_pct: float
    margem_contribuicao: float
    margem_contribuicao_pct: float
    ponto_equilibrio_un: int | None     # unidades/mês só deste produto para cobrir o CFT


@dataclass(frozen=True)
class ResultadoPreco:
    sku: str
    materiais: tuple[ResultadoMaterial, ...]
    mao_de_obra: tuple[ResultadoMaoObra, ...]
    mp: float
    mo: float
    cd: float
    horas_mo: float
    cf_unit: float
    cv_fixo: float
    pct_cv: float
    pct_cf: float
    pct_ml: float
    markup_divisor: float
    markup: float | None
    preco: float | None                 # None = indefinido (%CV + %CF + %ML ≥ 100 %)
    preco_minimo: float | None          # lucro zero
    preco_cobertura: float | None       # margem de contribuição zero
    margem_maxima_pct: float            # 100 − %CV − %CF
    custo_fixo_total: float
    alertas: tuple[str, ...] = field(default_factory=tuple)

    # parcelas do preço sugerido (para o painel "formação do preço")
    @property
    def parcela_cf(self) -> float | None:
        return None if self.preco is None else self.cf_unit + self.preco * self.pct_cf / 100

    @property
    def parcela_cv(self) -> float | None:
        return None if self.preco is None else self.cv_fixo + self.preco * self.pct_cv / 100

    @property
    def lucro(self) -> float | None:
        return None if self.preco is None else self.preco * self.pct_ml / 100

    @property
    def custo_total(self) -> float:
        """Numerador do markup: CD + CFu + CV fixo."""
        return self.cd + self.cf_unit + self.cv_fixo

    # -------------------------------------------------------------- simulador
    def simular(self, preco: float) -> Simulacao:
        """Indicadores para um preço qualquer (seção 3.8)."""
        if preco <= 0:
            raise ValueError("preço deve ser positivo")
        cv, cf = self.pct_cv / 100, self.pct_cf / 100
        lucro = preco * (1 - cv - cf) - self.custo_total
        mc = preco * (1 - cv) - self.cv_fixo - self.cd
        pe = math.ceil(self.custo_fixo_total / mc - 1e-9) if mc > 0 else None
        return Simulacao(preco=preco, lucro=lucro, margem_pct=100 * lucro / preco,
                         margem_contribuicao=mc, margem_contribuicao_pct=100 * mc / preco,
                         ponto_equilibrio_un=pe)

    def preco_para_margem(self, margem_pct: float) -> float | None:
        """Inverso do simulador: preço que entrega exatamente a margem líquida informada."""
        md = 1 - (self.pct_cv + self.pct_cf + margem_pct) / 100
        return self.custo_total / md if md > 0 else None


# ============================================================================ cálculo
def _br(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",")


def fator_perda(perda_pct: float, modo: ModoPerda) -> float:
    p = perda_pct / 100
    if modo == ModoPerda.SOBRE_COMPRA:
        if p >= 1:
            raise ValueError("perda deve ser menor que 100 %")
        return 1 / (1 - p)
    return 1 + p


def calcular_material(linha: LinhaMaterial, largura_cm: float | None, altura_cm: float | None,
                      modo_perda: ModoPerda) -> ResultadoMaterial:
    custo_consumo = linha.custo_compra / linha.fator_conversao
    tem_dim = largura_cm is not None and altura_cm is not None
    extra: dict = {}
    if linha.modo_qtd == ModoQtd.FIXA:
        q = linha.quantidade
    elif not tem_dim:
        return ResultadoMaterial(linha, 0.0, 0.0, custo_consumo, 0.0,
                                 alerta=f"{linha.sku}: produto sem dimensões para o modo '{linha.modo_qtd}'")
    elif linha.modo_qtd == ModoQtd.AREA:
        q = linha.quantidade * largura_cm * altura_cm / 10_000
    elif linha.modo_qtd == ModoQtd.PERIMETRO:
        q = linha.quantidade * 2 * (largura_cm + altura_cm) / 100
    else:  # aproveitamento
        if linha.folha_largura_m is None or linha.folha_comprimento_m is None:
            return ResultadoMaterial(linha, 0.0, 0.0, custo_consumo, 0.0,
                                     alerta=f"{linha.sku}: insumo sem dimensões de folha/chapa")
        enc = pecas_por_folha(100 * linha.folha_largura_m, 100 * linha.folha_comprimento_m,
                              largura_cm, altura_cm, linha.espacamento_cm, linha.folha_margem_cm)
        extra = dict(pecas_folha=enc.pecas, disposicao=enc.disposicao, aproveitamento_pct=enc.aproveitamento_pct)
        if enc.pecas == 0:
            return ResultadoMaterial(linha, 0.0, 0.0, custo_consumo, 0.0,
                                     alerta=f"{linha.sku}: produto não cabe na folha", **extra)
        q = linha.quantidade / enc.pecas
    comprada = q * fator_perda(linha.perda_pct, modo_perda)
    return ResultadoMaterial(linha, q, comprada, custo_consumo, comprada * custo_consumo, **extra)


def calcular(entrada: EntradaProduto, regras: RegrasEmpresa) -> ResultadoPreco:
    alertas: list[str] = []

    # 3.1 materiais
    mats = tuple(calcular_material(l, entrada.largura_cm, entrada.altura_cm, regras.modo_perda)
                 for l in entrada.materiais)
    alertas += [m.alerta for m in mats if m.alerta]
    mp = sum(m.custo for m in mats)

    # 3.2 mão de obra
    mos = tuple(ResultadoMaoObra(l, l.horas * l.custo_hora) for l in entrada.mao_de_obra)
    mo = sum(m.custo for m in mos)
    horas = sum(l.horas for l in entrada.mao_de_obra)

    # 3.3
    cd = mp + mo

    # 3.4 custos fixos
    cft = regras.custo_fixo_total
    pct_cf, cf_unit = 0.0, 0.0
    if cft > 0:
        if regras.metodo_rateio == MetodoRateio.PCT_FATURAMENTO:
            if regras.faturamento_base and regras.faturamento_base > 0:
                pct_cf = 100 * cft / regras.faturamento_base
            else:
                alertas.append("faturamento base não informado: custo fixo fora do preço")
        elif regras.metodo_rateio == MetodoRateio.HORA_PRODUTIVA:
            if regras.capacidade_horas and regras.capacidade_horas > 0:
                cf_unit = cft / regras.capacidade_horas * horas
            else:
                alertas.append("capacidade de horas não informada: custo fixo fora do preço")
        else:
            if regras.capacidade_unidades and regras.capacidade_unidades > 0:
                cf_unit = cft / regras.capacidade_unidades
            else:
                alertas.append("capacidade de unidades não informada: custo fixo fora do preço")

    # 3.5 custos variáveis
    pct_cv = sum(i.valor for i in entrada.custos_variaveis if i.tipo == "percentual")
    cv_fixo = sum(i.valor for i in entrada.custos_variaveis if i.tipo == "valor_fixo")

    # 3.7 preço
    pct_ml = regras.margem_padrao_pct if entrada.margem_pct is None else entrada.margem_pct
    md = 1 - (pct_cv + pct_cf + pct_ml) / 100
    numerador = cd + cf_unit + cv_fixo
    preco = numerador / md if md > 0 else None
    if preco is None:
        alertas.append(f"%CV + %CF + margem = {_br(pct_cv + pct_cf + pct_ml)} % ≥ 100 %: preço indefinido "
                       f"(margem máxima possível {_br(100 - pct_cv - pct_cf)} %)")
    div_min = 1 - (pct_cv + pct_cf) / 100
    div_cob = 1 - pct_cv / 100
    if not entrada.materiais and not entrada.mao_de_obra:
        alertas.append("ficha técnica vazia")

    resultado = ResultadoPreco(
        sku=entrada.sku, materiais=mats, mao_de_obra=mos, mp=mp, mo=mo, cd=cd, horas_mo=horas,
        cf_unit=cf_unit, cv_fixo=cv_fixo, pct_cv=pct_cv, pct_cf=pct_cf, pct_ml=pct_ml,
        markup_divisor=md, markup=(1 / md if md > 0 else None), preco=preco,
        preco_minimo=numerador / div_min if div_min > 0 else None,
        preco_cobertura=(cd + cv_fixo) / div_cob if div_cob > 0 else None,
        margem_maxima_pct=100 - pct_cv - pct_cf, custo_fixo_total=cft,
    )
    if entrada.preco_praticado and preco is not None:
        s = resultado.simular(entrada.preco_praticado)
        if s.margem_pct < pct_ml - 1e-9:
            alertas.append(f"preço praticado rende {_br(s.margem_pct, 1)} % (desejado {_br(pct_ml, 1)} %)")
        if s.lucro < 0:
            alertas.append("preço praticado gera prejuízo")
    return replace(resultado, alertas=tuple(alertas))
