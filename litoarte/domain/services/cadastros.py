"""Cadastros: definição declarativa dos módulos e serviço único de validação/gravação.

Cada `Modulo` descreve seus campos UMA vez. A mesma definição alimenta:
  - formulários da interface (tipo de controle, rótulo, obrigatoriedade, opções);
  - validação e gravação (formulário e importação usam `validar_registro` + `gravar`);
  - modelos de planilha e exportação (colunas = nomes dos campos).

Regras gerais:
  - chave de negócio (SKU/código) identifica o registro: gravar = inserir ou atualizar;
  - em atualização, campo vazio NÃO apaga o valor existente;
  - referências são informadas pelo código/sigla/nome e resolvidas para o id;
  - excluir item referenciado é bloqueado (FK RESTRICT): a interface oferece inativar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (FONTES_PRECO, Concorrente, PrecoConcorrente)
from ..models import (CATEGORIAS_CV, GRANDEZAS, MODOS_CUSTO_MO, MODOS_QTD, TIPOS_CV, UNIDADES_TEMPO, CustoFixo,
                      CustoVariavel, FichaMO, FichaMP, Fornecedor, Grupo, MaoDeObra, MateriaPrima, PerfilVenda,
                      Produto, Subgrupo, UnidadeMedida)
from . import valores as V


# ============================================================================ definição
@dataclass(frozen=True)
class Campo:
    nome: str                               # nome da coluna (planilha) e chave do formulário
    rotulo: str
    tipo: str = "texto"                     # texto | numero | bool | opcao | ref
    obrigatorio: bool = False               # exigido na inclusão
    atributo: str | None = None             # atributo do modelo (padrão = nome); None em campo virtual
    opcoes: tuple[str, ...] = ()
    aliases: dict[str, str] = field(default_factory=dict)
    ref: tuple[type, str] | None = None     # (Modelo, coluna de busca) -> grava o id
    cria_ref: bool = False                  # cria o referenciado se não existir (ex.: fornecedor)
    minimo: float | None = None             # >=
    maior_que: float | None = None          # >
    menor_que: float | None = None          # <
    ajuda: str = ""
    exemplo: Any = None
    na_lista: bool = True
    virtual: bool = False                   # não é atributo do modelo (tratado em gancho)
    padrao: Any = None                      # valor usado quando o campo é apagado no formulário

    @property
    def attr(self) -> str:
        return self.atributo or self.nome


@dataclass
class Modulo:
    chave: str
    titulo: str
    modelo: type
    campos: tuple[Campo, ...]
    chave_negocio: tuple[str, ...]          # campos que identificam o registro
    buscar: Callable[[Session, dict], Any] | None = None     # localizar existente pela chave
    ajustar: Callable[[Session, dict, Any, list], None] | None = None    # regras cruzadas (antes de gravar)
    depois: Callable[[Session, Any, dict], None] | None = None           # efeitos após gravar
    exibir: Callable[[Any], dict] | None = None                          # linha para listagem/exportação
    ordem: Any = None

    def campo(self, nome: str) -> Campo:
        return next(c for c in self.campos if c.nome == nome)

    @property
    def tem_ativo(self) -> bool:
        return hasattr(self.modelo, "ativo")


class ErroValidacao(ValueError):
    def __init__(self, erros: list[tuple[str, str]]):
        self.erros = erros
        super().__init__("; ".join(f"{c}: {m}" if c else m for c, m in erros))


# ============================================================================ validação
def converter(campo: Campo, bruto: Any) -> Any:
    if campo.tipo == "numero":
        v = V.numero(bruto)
        if v is not None:
            if campo.minimo is not None and v < campo.minimo:
                raise V.ValorInvalido(f"não pode ser menor que {campo.minimo:g}")
            if campo.maior_que is not None and v <= campo.maior_que:
                raise V.ValorInvalido(f"deve ser maior que {campo.maior_que:g}")
            if campo.menor_que is not None and v >= campo.menor_que:
                raise V.ValorInvalido(f"deve ser menor que {campo.menor_que:g}")
        return v
    if campo.tipo == "bool":
        return V.booleano(bruto)
    if campo.tipo == "opcao":
        return V.opcao(bruto, campo.opcoes, campo.aliases)
    return V.texto(bruto)


def resolver_ref(sessao: Session, campo: Campo, valor: str, criar: bool) -> int | None:
    modelo, coluna = campo.ref
    alvo = getattr(modelo, coluna)
    obj = sessao.scalar(select(modelo).where(alvo == valor))
    if obj is None:   # tolera maiúsculas/minúsculas e acentos
        for o in sessao.scalars(select(modelo)):
            if V.chave(getattr(o, coluna)) == V.chave(valor):
                obj = o
                break
    if obj is None and criar and campo.cria_ref:
        obj = modelo(**{coluna: valor})
        sessao.add(obj)
        sessao.flush()
    return obj.id if obj is not None else None


def validar_registro(sessao: Session, modulo: Modulo, bruto: dict, *, criar_refs: bool = False,
                     vazios_apagam: bool = False) -> tuple[dict, Any, list[tuple[str, str]]]:
    """Converte e valida uma linha. Retorna (valores, existente, erros).

    Importação (padrão): campos vazios ficam de fora e não apagam o existente.
    Formulário (vazios_apagam=True): campo opcional presente e vazio é gravado como vazio (None).
    """
    erros: list[tuple[str, str]] = []
    vals: dict[str, Any] = {}
    for c in modulo.campos:
        if c.nome in bruto and V.vazio(bruto[c.nome]) and vazios_apagam and not c.virtual \
                and not c.obrigatorio and c.nome not in modulo.chave_negocio and c.tipo != "bool":
            vals[c.nome] = c.padrao
            continue
        if c.nome not in bruto or V.vazio(bruto[c.nome]):
            continue
        try:
            v = converter(c, bruto[c.nome])
        except V.ValorInvalido as e:
            erros.append((c.nome, str(e)))
            continue
        if v is None:
            continue
        if c.tipo == "ref" and not c.virtual:
            rid = resolver_ref(sessao, c, v, criar_refs)
            if rid is None:
                if c.cria_ref:
                    vals[c.nome] = v         # será criado na gravação
                    continue
                erros.append((c.nome, f"'{v}' não cadastrado"))
                continue
            vals[c.nome] = rid
        else:
            vals[c.nome] = v

    faltando_chave = [k for k in modulo.chave_negocio if k not in vals]
    existente = None
    if not faltando_chave and not any(e[0] in modulo.chave_negocio for e in erros):
        existente = (modulo.buscar or _buscar_padrao(modulo))(sessao, vals)
    for k in faltando_chave:
        if not any(e[0] == k for e in erros):
            erros.append((k, "obrigatório"))
    if existente is None:
        for c in modulo.campos:
            if c.obrigatorio and c.nome not in vals and not any(e[0] == c.nome for e in erros) \
                    and c.nome not in modulo.chave_negocio:
                erros.append((c.nome, "obrigatório na inclusão"))
    if modulo.ajustar and not erros:
        modulo.ajustar(sessao, vals, existente, erros)
    return vals, existente, erros


def _buscar_padrao(modulo: Modulo) -> Callable[[Session, dict], Any]:
    def buscar(sessao: Session, vals: dict):
        filtro = [getattr(modulo.modelo, modulo.campo(k).attr) == vals[k] for k in modulo.chave_negocio]
        return sessao.scalar(select(modulo.modelo).where(*filtro))
    return buscar


# ============================================================================ gravação
def gravar(sessao: Session, modulo: Modulo, bruto: dict, *, origem: str = "manual", id_edicao: int | None = None,
           vazios_apagam: bool = False):
    """Insere ou atualiza (pela chave de negócio). Levanta ErroValidacao. Não faz commit."""
    vals, existente, erros = validar_registro(sessao, modulo, bruto, criar_refs=True, vazios_apagam=vazios_apagam)
    if id_edicao is not None:
        atual = sessao.get(modulo.modelo, id_edicao)
        if existente is not None and existente.id != id_edicao:
            erros.append((modulo.chave_negocio[0], "já existe outro registro com esta chave"))
        existente = atual
    if erros:
        raise ErroValidacao(erros)
    return aplicar(sessao, modulo, vals, existente, origem=origem)


def aplicar(sessao: Session, modulo: Modulo, vals: dict, existente, *, origem: str = "manual"):
    obj = existente or modulo.modelo()
    for c in modulo.campos:
        if c.virtual or c.nome not in vals:
            continue
        valor = vals[c.nome]
        if c.tipo == "ref" and isinstance(valor, str) and valor:  # referência a criar (cria_ref)
            valor = resolver_ref(sessao, c, valor, True)
        setattr(obj, c.attr, valor)
    for attr, valor in vals.get("_attrs", {}).items():          # atributos derivados por `ajustar`
        setattr(obj, attr, valor)
    obj.origem_alteracao = origem
    if existente is None:
        sessao.add(obj)
    sessao.flush()
    if modulo.depois:
        modulo.depois(sessao, obj, vals)
        sessao.flush()
    return obj


def excluir(sessao: Session, modulo: Modulo, id_: int) -> None:
    """Exclui; se o registro estiver em uso, levanta ErroValidacao sugerindo inativar.

    Deve ser a única operação da transação: em caso de bloqueio a sessão é revertida.
    """
    obj = sessao.get(modulo.modelo, id_)
    if obj is None:
        return
    try:
        sessao.delete(obj)
        sessao.flush()
    except IntegrityError:
        sessao.rollback()
        dica = " Inative-o para tirá-lo de uso." if modulo.tem_ativo else ""
        raise ErroValidacao([("", f"registro em uso por outros cadastros e não pode ser excluído.{dica}")]) from None


def definir_ativo(sessao: Session, modulo: Modulo, id_: int, ativo: bool) -> None:
    obj = sessao.get(modulo.modelo, id_)
    if obj is not None and modulo.tem_ativo:
        obj.ativo = ativo
        sessao.flush()


def listar(sessao: Session, modulo: Modulo, *, incluir_inativos: bool = True) -> list[dict]:
    q = select(modulo.modelo)
    if modulo.tem_ativo and not incluir_inativos:
        q = q.where(modulo.modelo.ativo)
    if modulo.ordem is not None:
        q = q.order_by(*modulo.ordem)
    return [linha_exibicao(modulo, o) for o in sessao.scalars(q)]


def linha_exibicao(modulo: Modulo, obj) -> dict:
    """Valores no formato da planilha (referências pelo código/sigla/nome)."""
    if modulo.exibir:
        d = modulo.exibir(obj)
    else:
        d = {}
        for c in modulo.campos:
            if c.virtual:
                continue
            v = getattr(obj, c.attr)
            if c.tipo == "ref" and v is not None:
                alvo = _objeto_ref(obj, c)
                v = getattr(alvo, c.ref[1]) if alvo is not None else None
            d[c.nome] = v
    d["id"] = obj.id
    return d


def _objeto_ref(obj, campo: Campo):
    nome_rel = campo.attr[:-3] if campo.attr.endswith("_id") else campo.attr
    return getattr(obj, nome_rel, None)


# ============================================================================ ganchos específicos
SIM_NAO = "sim/não"
N_FAIXAS = 5


def _mp_ajustar(sessao, vals, existente, erros):
    if existente is None and "unidade_consumo" not in vals and "unidade_compra" in vals:
        vals["unidade_consumo"] = vals["unidade_compra"]
    larg = vals.get("largura_m", getattr(existente, "largura_m", None))
    comp = vals.get("comprimento_m", getattr(existente, "comprimento_m", None))
    if (larg is None) != (comp is None):
        erros.append(("comprimento_m" if comp is None else "largura_m",
                      "informe largura e comprimento da folha juntos"))


def _mo_ajustar(sessao, vals, existente, erros):
    if "custo_minuto" in vals:
        if "custo_hora" in vals:
            erros.append(("custo_minuto", "informe custo por hora OU por minuto"))
            return
        vals["custo_hora"] = vals.pop("custo_minuto") * 60
    if "modo_custo" not in vals and existente is None:
        vals["modo_custo"] = "calculado" if "salario_mensal" in vals else "informado"
    modo = vals.get("modo_custo", getattr(existente, "modo_custo", None))
    final = lambda k: vals.get(k, getattr(existente, k, None))  # noqa: E731
    if modo == "informado" and final("custo_hora_informado") is None and "custo_hora" not in vals:
        erros.append(("custo_hora", "obrigatório quando o custo é informado"))
    if modo == "calculado":
        for k in ("salario_mensal", "horas_produtivas_mes"):
            if final(k) is None:
                erros.append((k, "obrigatório quando o custo é calculado"))
    if "custo_hora" in vals:
        vals.setdefault("_attrs", {})["custo_hora_informado"] = vals.pop("custo_hora")


def _mo_exibir(o: MaoDeObra) -> dict:
    return {"codigo": o.codigo, "etapa": o.etapa, "modo_custo": o.modo_custo,
            "custo_hora": round(o.custo_hora, 4),
            "salario_mensal": o.salario_mensal, "encargos_pct": o.encargos_pct,
            "horas_produtivas_mes": o.horas_produtivas_mes, "qtd_colaboradores": o.qtd_colaboradores,
            "ativo": o.ativo}


def _cv_depois(sessao, obj: CustoVariavel, vals):
    if "perfis" not in vals:
        return
    nomes = [n.strip() for n in str(vals["perfis"]).replace(",", ";").split(";") if n.strip()]
    for nome in nomes:
        perfil = sessao.scalar(select(PerfilVenda).where(PerfilVenda.nome == nome))
        if perfil is None:
            perfil = PerfilVenda(nome=nome, padrao=False)
            sessao.add(perfil)
        if obj not in perfil.custos:
            perfil.custos.append(obj)
    for perfil in sessao.scalars(select(PerfilVenda)):
        if perfil.nome not in nomes and obj in perfil.custos:
            perfil.custos.remove(obj)


def _cv_exibir(o: CustoVariavel) -> dict:
    return {"codigo": o.codigo, "descricao": o.descricao, "categoria": o.categoria, "tipo": o.tipo,
            "valor": o.valor, "ativo": o.ativo, "perfis": "; ".join(sorted(p.nome for p in _perfis_de(o)))}


def _perfis_de(o: CustoVariavel):
    from sqlalchemy.orm import object_session
    s = object_session(o)
    return [p for p in s.scalars(select(PerfilVenda)) if o in p.custos] if s else []


def _sub_buscar(sessao, vals):
    return sessao.scalar(select(Subgrupo).where(Subgrupo.grupo_id == vals["grupo"], Subgrupo.codigo == vals["codigo"]))


def _sub_exibir(o: Subgrupo) -> dict:
    return {"grupo": o.grupo.codigo, "grupo_nome": o.grupo.nome, "codigo": o.codigo, "nome": o.nome}


def _prod_faixas(vals, erros):
    """margem_faixa_N: margem própria ('padrao' volta à geral); preco_faixa_N: preço aplicado ('remover' apaga)."""
    faixas: dict[int, dict] = {}
    for i in range(1, N_FAIXAS + 1):
        for tipo, col, limite in (("margem", f"margem_faixa_{i}", 100), ("preco", f"preco_faixa_{i}", None)):
            if col not in vals:
                continue
            bruto = vals.pop(col)
            if V.chave(bruto) in ("padrao", "geral", "remover", "apagar"):
                faixas.setdefault(i, {})[tipo] = None
                continue
            try:
                v = V.numero(bruto)
            except V.ValorInvalido as e:
                erros.append((col, str(e)))
                continue
            if v is None:
                continue
            if v < 0 or (limite is not None and v >= limite):
                erros.append((col, "entre 0 e 100 %" if limite else "não pode ser negativo"))
                continue
            faixas.setdefault(i, {})[tipo] = v
    if faixas:
        vals["_faixas"] = faixas


def _prod_depois(sessao, obj: Produto, vals):
    from ..models import FaixaPreco, ProdutoFaixa
    for ordem, mud in vals.get("_faixas", {}).items():
        faixa = sessao.scalar(select(FaixaPreco).where(FaixaPreco.ordem == ordem))
        if faixa is None:
            continue
        atual = next((x for x in obj.margens_faixas if x.faixa_id == faixa.id), None)
        if atual is None:
            atual = ProdutoFaixa(faixa_id=faixa.id)
            obj.margens_faixas.append(atual)
        if "margem" in mud:
            atual.margem_pct = mud["margem"]
        if "preco" in mud:
            atual.preco_aplicado = mud["preco"]
        if atual.margem_pct is None and atual.preco_aplicado is None:
            obj.margens_faixas.remove(atual)


def _prod_ajustar(sessao, vals, existente, erros):
    """Subgrupo informado por grupo + código do subgrupo; margens próprias das faixas."""
    _prod_faixas(vals, erros)
    if "subgrupo" in vals or "grupo" in vals:
        g = vals.pop("grupo", None)
        sg = vals.pop("subgrupo", None)
        if g is None or sg is None:
            erros.append(("subgrupo", "informe grupo e subgrupo juntos"))
            return
        sub = sessao.scalar(select(Subgrupo).join(Grupo).where(Grupo.codigo == g, Subgrupo.codigo == sg))
        if sub is None:
            erros.append(("subgrupo", f"subgrupo {g}/{sg} não cadastrado"))
            return
        vals.setdefault("_attrs", {})["subgrupo_id"] = sub.id
    elif existente is None:
        erros.append(("subgrupo", "obrigatório na inclusão (grupo + subgrupo)"))


def _prod_exibir(o: Produto) -> dict:
    return {"sku": o.sku, "nome": o.nome, "grupo": o.subgrupo.grupo.codigo, "subgrupo": o.subgrupo.codigo,
            "largura_cm": o.largura_cm, "altura_cm": o.altura_cm,
            "perfil_venda": o.perfil_venda.nome if o.perfil_venda else None,
            "margem_desejada_pct": o.margem_desejada_pct, "preco_praticado": o.preco_praticado, "ativo": o.ativo,
            "custo_atual": o.custo_atual,
            **{f"margem_faixa_{m.faixa.ordem}": m.margem_pct for m in o.margens_faixas if m.margem_pct is not None},
            **{f"preco_faixa_{m.faixa.ordem}": m.preco_aplicado for m in o.margens_faixas
               if m.preco_aplicado is not None}}


def _ficha_mp_buscar(sessao, vals):
    return sessao.scalar(select(FichaMP).where(FichaMP.produto_id == vals["produto"],
                                               FichaMP.materia_prima_id == vals["insumo"]))


def _ficha_mo_buscar(sessao, vals):
    return sessao.scalar(select(FichaMO).where(FichaMO.produto_id == vals["produto"],
                                               FichaMO.mao_de_obra_id == vals["etapa"]))


def _conc_ajustar(sessao, vals, existente, erros):
    if "grupos" in vals:
        codigos = [c.strip() for c in str(vals.pop("grupos")).replace(",", ";").split(";") if c.strip()]
        grupos = []
        for cod in codigos:
            g = sessao.scalar(select(Grupo).where(Grupo.codigo == cod))
            if g is None:
                erros.append(("grupos", f"grupo '{cod}' não cadastrado"))
            else:
                grupos.append(g)
        vals["_grupos"] = grupos


def _conc_depois(sessao, obj, vals):
    if "_grupos" in vals:
        obj.grupos = vals["_grupos"]


def _conc_exibir(o) -> dict:
    return {"nome": o.nome, "site": o.site, "observacao": o.observacao,
            "grupos": "; ".join(g.codigo for g in o.grupos), "ativo": o.ativo}


def _pc_buscar(sessao, vals):
    from ..models import PrecoConcorrente
    if not isinstance(vals["concorrente"], int):      # concorrente novo (será criado): não há preço anterior
        return None
    return sessao.scalar(select(PrecoConcorrente).where(
        PrecoConcorrente.concorrente_id == vals["concorrente"], PrecoConcorrente.grupo_id == vals["grupo"],
        PrecoConcorrente.descricao == vals["descricao"]))


def _pc_ajustar(sessao, vals, existente, erros):
    if "subgrupo" in vals:
        cod = vals.pop("subgrupo")
        gid = vals.get("grupo", getattr(existente, "grupo_id", None))
        sub = sessao.scalar(select(Subgrupo).where(Subgrupo.grupo_id == gid, Subgrupo.codigo == cod))
        if sub is None:
            erros.append(("subgrupo", f"subgrupo '{cod}' não existe no grupo"))
        else:
            vals.setdefault("_attrs", {})["subgrupo_id"] = sub.id


def _pc_depois(sessao, obj, vals):
    if obj.grupo not in obj.concorrente.grupos:      # mantém o concorrente associado ao grupo
        obj.concorrente.grupos.append(obj.grupo)


def _pc_exibir(o) -> dict:
    return {"grupo": o.grupo.codigo, "subgrupo": o.subgrupo.codigo if o.subgrupo else None,
            "produto": o.produto.sku if o.produto else None, "concorrente": o.concorrente.nome,
            "descricao": o.descricao, "preco": o.preco, "url": o.url, "fonte": o.fonte,
            "coletado_em": o.coletado_em.strftime("%d/%m/%Y") if o.coletado_em else None}


ALIAS_MODO_QTD = {"m2": "area", "m²": "area", "area_m2": "area", "perimetro_m": "perimetro", "m": "perimetro",
                  "linear": "perimetro", "folha": "aproveitamento", "chapa": "aproveitamento", "un": "fixa",
                  "unidade": "fixa", "quantidade": "fixa"}
ALIAS_TIPO_CV = {"%": "percentual", "pct": "percentual", "r$": "valor_fixo", "fixo": "valor_fixo",
                 "valor": "valor_fixo", "reais": "valor_fixo"}
ALIAS_TEMPO = {"minuto": "min", "minutos": "min", "m": "min", "hora": "h", "horas": "h", "hr": "h"}

ATIVO = Campo("ativo", "Ativo", "bool", ajuda=SIM_NAO, exemplo="sim")

# ============================================================================ módulos
MODULOS: dict[str, Modulo] = {m.chave: m for m in [
    Modulo("unidades", "Unidades de medida", UnidadeMedida, (
        Campo("sigla", "Sigla", obrigatorio=True, exemplo="ml"),
        Campo("descricao", "Descrição", obrigatorio=True, exemplo="Mililitro"),
        Campo("grandeza", "Grandeza", "opcao", obrigatorio=True, opcoes=GRANDEZAS, exemplo="volume"),
    ), ("sigla",), ordem=(UnidadeMedida.sigla,)),

    Modulo("fornecedores", "Fornecedores", Fornecedor, (
        Campo("nome", "Nome", obrigatorio=True, exemplo="Papelaria Central"),
        Campo("documento", "CNPJ/CPF", exemplo="12.345.678/0001-90"),
        Campo("contato", "Contato", exemplo="(51) 99999-0000"),
        ATIVO,
    ), ("nome",), ordem=(Fornecedor.nome,)),

    Modulo("materias_primas", "Matérias-primas (insumos)", MateriaPrima, (
        Campo("sku", "SKU", obrigatorio=True, exemplo="TINTA-CMYK-1L"),
        Campo("nome", "Nome", obrigatorio=True, exemplo="Tinta eco-solvente CMYK 1 L"),
        Campo("unidade_compra", "Un. compra", "ref", obrigatorio=True, atributo="unidade_compra_id",
              ref=(UnidadeMedida, "sigla"), exemplo="frasco", ajuda="sigla da unidade em que é comprado"),
        Campo("unidade_consumo", "Un. consumo", "ref", atributo="unidade_consumo_id", ref=(UnidadeMedida, "sigla"),
              exemplo="ml", ajuda="unidade usada na ficha técnica; vazio = igual à de compra"),
        Campo("fator_conversao", "Conversão", "numero", maior_que=0, exemplo=1000, padrao=1.0,
              ajuda="unidades de consumo em 1 unidade de compra (frasco 1 L = 1000 ml); vazio = 1"),
        Campo("custo_compra", "Custo de compra (R$)", "numero", obrigatorio=True, minimo=0, exemplo=280.0),
        Campo("perda_pct", "Perda (%)", "numero", minimo=0, menor_que=100, exemplo=10, padrao=0.0),
        Campo("fornecedor", "Fornecedor", "ref", atributo="fornecedor_id", ref=(Fornecedor, "nome"), cria_ref=True,
              exemplo="Insumos Gráficos Ltda", ajuda="nome; criado automaticamente se não existir"),
        Campo("largura_m", "Folha: largura (m)", "numero", maior_que=0, ajuda="só para folha/chapa/bobina"),
        Campo("comprimento_m", "Folha: comprimento (m)", "numero", maior_que=0),
        Campo("margem_cm", "Folha: margem (cm)", "numero", minimo=0, na_lista=False, padrao=0.0),
        ATIVO,
    ), ("sku",), ajustar=_mp_ajustar, ordem=(MateriaPrima.sku,)),

    Modulo("mao_de_obra", "Mão de obra", MaoDeObra, (
        Campo("codigo", "Código", obrigatorio=True, exemplo="CORTE"),
        Campo("etapa", "Etapa / função", obrigatorio=True, exemplo="Corte"),
        Campo("modo_custo", "Modo", "opcao", opcoes=MODOS_CUSTO_MO, exemplo="informado",
              ajuda="informado: custo/hora com encargos | calculado: salário + encargos ÷ horas"),
        Campo("custo_hora", "Custo/hora (R$)", "numero", minimo=0, exemplo=27.0, virtual=True,
              ajuda="modo informado, encargos inclusos"),
        Campo("custo_minuto", "Custo/minuto (R$)", "numero", minimo=0, virtual=True, na_lista=False,
              ajuda="alternativa ao custo/hora"),
        Campo("salario_mensal", "Salário (R$)", "numero", minimo=0, ajuda="modo calculado"),
        Campo("encargos_pct", "Encargos (%)", "numero", minimo=0, ajuda="modo calculado"),
        Campo("horas_produtivas_mes", "Horas produtivas/mês", "numero", maior_que=0, ajuda="modo calculado"),
        Campo("qtd_colaboradores", "Colaboradores", "numero", minimo=0, exemplo=1, padrao=1.0),
        ATIVO,
    ), ("codigo",), ajustar=_mo_ajustar, exibir=_mo_exibir, ordem=(MaoDeObra.codigo,)),

    Modulo("custos_fixos", "Custos fixos", CustoFixo, (
        Campo("codigo", "Código", obrigatorio=True, exemplo="ALUGUEL"),
        Campo("descricao", "Descrição", obrigatorio=True, exemplo="Aluguel do galpão"),
        Campo("categoria", "Categoria", exemplo="Ocupação"),
        Campo("valor_mensal", "Valor mensal (R$)", "numero", obrigatorio=True, minimo=0, exemplo=3500.0),
        ATIVO,
    ), ("codigo",), ordem=(CustoFixo.codigo,)),

    Modulo("custos_variaveis", "Custos variáveis", CustoVariavel, (
        Campo("codigo", "Código", obrigatorio=True, exemplo="SIMPLES"),
        Campo("descricao", "Descrição", obrigatorio=True, exemplo="Simples Nacional"),
        Campo("categoria", "Categoria", "opcao", opcoes=CATEGORIAS_CV, exemplo="imposto"),
        Campo("tipo", "Tipo", "opcao", obrigatorio=True, opcoes=TIPOS_CV, aliases=ALIAS_TIPO_CV, exemplo="percentual",
              ajuda="percentual (sobre o preço) ou valor_fixo (R$ por unidade)"),
        Campo("valor", "Valor", "numero", obrigatorio=True, minimo=0, exemplo=6.0),
        Campo("perfis", "Perfis de venda", virtual=True, exemplo="Venda direta; Marketplace",
              ajuda="perfis em que o custo se aplica, separados por ';' (criados se não existirem)"),
        ATIVO,
    ), ("codigo",), depois=_cv_depois, exibir=_cv_exibir, ordem=(CustoVariavel.codigo,)),

    Modulo("grupos", "Grupos", Grupo, (
        Campo("codigo", "Código", obrigatorio=True, exemplo="QDR"),
        Campo("nome", "Nome", obrigatorio=True, exemplo="Quadros"),
    ), ("codigo",), ordem=(Grupo.codigo,)),

    Modulo("subgrupos", "Subgrupos", Subgrupo, (
        Campo("grupo", "Grupo (código)", "ref", obrigatorio=True, atributo="grupo_id", ref=(Grupo, "codigo"),
              exemplo="QDR"),
        Campo("codigo", "Código", obrigatorio=True, exemplo="CNV-G"),
        Campo("nome", "Nome", obrigatorio=True, exemplo="Canvas 60x90"),
    ), ("grupo", "codigo"), buscar=_sub_buscar, exibir=_sub_exibir, ordem=(Subgrupo.grupo_id, Subgrupo.codigo)),

    Modulo("produtos", "Produtos", Produto, (
        Campo("sku", "SKU", obrigatorio=True, exemplo="QDC-6090"),
        Campo("nome", "Nome", obrigatorio=True, exemplo="Quadro Canvas 60x90"),
        Campo("grupo", "Grupo (código)", virtual=True, exemplo="QDR"),
        Campo("subgrupo", "Subgrupo (código)", virtual=True, exemplo="CNV-G"),
        Campo("largura_cm", "Largura (cm)", "numero", maior_que=0, exemplo=60),
        Campo("altura_cm", "Altura (cm)", "numero", maior_que=0, exemplo=90),
        Campo("perfil_venda", "Perfil de venda", "ref", atributo="perfil_venda_id", ref=(PerfilVenda, "nome"),
              ajuda="vazio = perfil padrão"),
        Campo("margem_desejada_pct", "Margem (%)", "numero", minimo=0, menor_que=100,
              ajuda="vazio = margem padrão da configuração"),
        Campo("preco_praticado", "Preço praticado (R$)", "numero", minimo=0),
        ATIVO,
        Campo("custo_atual", "Custo atual (R$)", "numero", minimo=0, na_lista=False,
              ajuda="custo usado hoje (sistema/planilha anterior), para comparar com o custo calculado"),
        *(Campo(f"preco_faixa_{i}", f"Preço aplicado faixa {i} (R$)", virtual=True, na_lista=False,
                ajuda="preço praticado hoje nesta faixa; 'remover' apaga")
          for i in range(1, N_FAIXAS + 1)),
        *(Campo(f"margem_faixa_{i}", f"Margem faixa {i} (%)", virtual=True, na_lista=False,
                ajuda="margem própria do produto na faixa; vazio = margem geral; 'padrao' remove a própria")
          for i in range(1, N_FAIXAS + 1)),
    ), ("sku",), ajustar=_prod_ajustar, depois=_prod_depois, exibir=_prod_exibir, ordem=(Produto.sku,)),

    Modulo("concorrentes", "Concorrentes", Concorrente, (
        Campo("nome", "Nome", obrigatorio=True, exemplo="Loja de Quadros Exemplo"),
        Campo("site", "Site", exemplo="https://www.exemplo.com.br"),
        Campo("grupos", "Grupos (códigos)", virtual=True, exemplo="QDR; PAP",
              ajuda="grupos de produtos em que concorre, separados por ';'"),
        Campo("observacao", "Observação"),
        ATIVO,
    ), ("nome",), ajustar=_conc_ajustar, depois=_conc_depois, exibir=_conc_exibir, ordem=(Concorrente.nome,)),

    Modulo("precos_concorrentes", "Preços de concorrentes", PrecoConcorrente, (
        Campo("grupo", "Grupo (código)", "ref", obrigatorio=True, atributo="grupo_id", ref=(Grupo, "codigo"),
              exemplo="QDR"),
        Campo("subgrupo", "Subgrupo (código)", virtual=True, ajuda="opcional: subgrupo comparável"),
        Campo("produto", "Produto (SKU)", "ref", atributo="produto_id", ref=(Produto, "sku"),
              ajuda="opcional: seu produto equivalente"),
        Campo("concorrente", "Concorrente", "ref", obrigatorio=True, atributo="concorrente_id",
              ref=(Concorrente, "nome"), cria_ref=True, exemplo="Loja de Quadros Exemplo",
              ajuda="criado automaticamente se não existir"),
        Campo("descricao", "Produto similar", obrigatorio=True, exemplo="Quadro canvas 60x90 paisagem"),
        Campo("preco", "Preço (R$)", "numero", obrigatorio=True, maior_que=0, exemplo=149.9),
        Campo("url", "Link", na_lista=False),
        Campo("fonte", "Fonte", "opcao", opcoes=FONTES_PRECO, ajuda="manual, mercadolivre, google_shopping..."),
        Campo("coletado_em", "Coletado em", virtual=True, na_lista=True),
    ), ("concorrente", "grupo", "descricao"), buscar=_pc_buscar, ajustar=_pc_ajustar, depois=_pc_depois,
        exibir=_pc_exibir),

    Modulo("ficha_materiais", "Ficha técnica — materiais", FichaMP, (
        Campo("produto", "Produto (SKU)", "ref", obrigatorio=True, atributo="produto_id", ref=(Produto, "sku"),
              exemplo="QDC-6090"),
        Campo("insumo", "Insumo (SKU)", "ref", obrigatorio=True, atributo="materia_prima_id",
              ref=(MateriaPrima, "sku"), exemplo="TINTA-CMYK-1L"),
        Campo("modo_qtd", "Modo", "opcao", opcoes=MODOS_QTD, aliases=ALIAS_MODO_QTD, exemplo="area",
              ajuda="fixa | area | perimetro | aproveitamento; vazio = fixa"),
        Campo("quantidade", "Quantidade", "numero", obrigatorio=True, minimo=0, exemplo=9.6,
              ajuda="na unidade de consumo do insumo (por m² no modo área, por m no perímetro)"),
        Campo("perda_pct", "Perda (%)", "numero", minimo=0, menor_que=100, ajuda="vazio = perda do insumo"),
        Campo("espacamento_cm", "Espaçamento (cm)", "numero", minimo=0, ajuda="aproveitamento", padrao=0.0),
        Campo("ordem", "Ordem", "numero", minimo=0, padrao=0),
    ), ("produto", "insumo"), buscar=_ficha_mp_buscar),

    Modulo("ficha_mao_de_obra", "Ficha técnica — mão de obra", FichaMO, (
        Campo("produto", "Produto (SKU)", "ref", obrigatorio=True, atributo="produto_id", ref=(Produto, "sku"),
              exemplo="QDC-6090"),
        Campo("etapa", "Etapa (código)", "ref", obrigatorio=True, atributo="mao_de_obra_id",
              ref=(MaoDeObra, "codigo"), exemplo="CORTE"),
        Campo("tempo", "Tempo", "numero", obrigatorio=True, minimo=0, exemplo=6),
        Campo("unidade_tempo", "Unidade", "opcao", opcoes=UNIDADES_TEMPO, aliases=ALIAS_TEMPO, exemplo="min"),
        Campo("ordem", "Ordem", "numero", minimo=0, padrao=0),
    ), ("produto", "etapa"), buscar=_ficha_mo_buscar),
]}

# Ordem de carga respeitando dependências
ORDEM_IMPORTACAO = ("unidades", "fornecedores", "materias_primas", "mao_de_obra", "custos_fixos",
                    "custos_variaveis", "grupos", "subgrupos", "produtos", "ficha_materiais", "ficha_mao_de_obra",
                    "concorrentes", "precos_concorrentes")
