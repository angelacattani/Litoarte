"""Importação em duas etapas: `analisar` (não grava nada) e `aplicar` (tudo-ou-nada).

Modos:
  inserir    -> inclui registros novos; chaves já cadastradas são ignoradas
  atualizar  -> atualiza registros existentes (match pela chave/SKU); chaves novas são ignoradas
  ambos      -> inclui e atualiza
Em atualização, células vazias não apagam o valor cadastrado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import FichaMO, FichaMP, ImportacaoLog, MaoDeObra, MateriaPrima, Produto
from ..domain.services import impacto
from ..domain.services.cadastros import MODULOS, ErroValidacao, Modulo, gravar, validar_registro
from .leitura import linhas_do_arquivo

MODOS = ("inserir", "atualizar", "ambos")


@dataclass
class LinhaAnalise:
    linha: int
    chave: str
    acao: str                                   # inserir | atualizar | ignorar | erro
    erros: list[tuple[str, str]] = field(default_factory=list)
    motivo: str = ""
    bruto: dict = field(default_factory=dict)


@dataclass
class Analise:
    modulo: str
    arquivo: str
    modo: str
    colunas: list[str]
    colunas_ignoradas: list[str]
    erros_arquivo: list[str]
    linhas: list[LinhaAnalise]

    def contagem(self) -> dict[str, int]:
        c = {"inserir": 0, "atualizar": 0, "ignorar": 0, "erro": 0}
        for l in self.linhas:
            c[l.acao] += 1
        return c

    @property
    def pode_gravar(self) -> bool:
        c = self.contagem()
        return not self.erros_arquivo and c["erro"] == 0 and (c["inserir"] + c["atualizar"]) > 0


@dataclass
class ResultadoImportacao:
    inseridas: int
    atualizadas: int
    ignoradas: int
    reajustes: list[tuple[str, float | None, float]]     # (chave, custo anterior, custo novo)
    produtos_afetados: list[str]
    impacto: list = field(default_factory=list)          # LinhaImpacto: preço antes/depois por produto


def _texto_chave(modulo: Modulo, bruto: dict) -> str:
    return " / ".join(str(bruto.get(k, "")).strip() for k in modulo.chave_negocio)


def analisar(sessao: Session, chave_modulo: str, conteudo: bytes, arquivo: str, modo: str = "ambos") -> Analise:
    if modo not in MODOS:
        raise ValueError(f"modo inválido: {modo}")
    modulo = MODULOS[chave_modulo]
    try:
        linhas, cols, ignoradas = linhas_do_arquivo(modulo, conteudo, arquivo)
    except Exception as e:  # arquivo ilegível
        return Analise(chave_modulo, arquivo, modo, [], [], [f"não foi possível ler o arquivo: {e}"], [])
    erros_arq = [f"coluna obrigatória ausente: {k}" for k in modulo.chave_negocio if k not in cols]
    if modo != "atualizar":
        faltam = [c.nome for c in modulo.campos if c.obrigatorio and c.nome not in cols
                  and c.nome not in modulo.chave_negocio]
        if faltam:
            erros_arq.append(f"colunas necessárias para incluir registros novos: {', '.join(faltam)}")
    if not linhas and not erros_arq:
        erros_arq.append("o arquivo não tem linhas de dados")
    if erros_arq:
        return Analise(chave_modulo, arquivo, modo, cols, ignoradas, erros_arq, [])

    resultado, vistas = [], {}
    for n, bruto in linhas:
        k = _texto_chave(modulo, bruto)
        _, existente, erros = validar_registro(sessao, modulo, bruto, criar_refs=False)
        la = LinhaAnalise(n, k, "erro", erros, bruto=bruto)
        if k in vistas:
            la.erros.append((modulo.chave_negocio[0], f"chave repetida no arquivo (linha {vistas[k]})"))
        vistas.setdefault(k, n)
        if existente is None and modo == "atualizar":
            la.acao, la.motivo, la.erros = "ignorar", "não cadastrado (modo atualizar)", []
        elif existente is not None and modo == "inserir":
            la.acao, la.motivo, la.erros = "ignorar", "já cadastrado (modo inserir)", []
        elif not la.erros:
            la.acao = "atualizar" if existente is not None else "inserir"
        resultado.append(la)
    return Analise(chave_modulo, arquivo, modo, cols, ignoradas, [], resultado)


def aplicar(sessao: Session, analise: Analise, usuario: str | None = None) -> ResultadoImportacao:
    """Grava as linhas válidas da análise. Erro em qualquer linha -> exceção (o chamador faz rollback)."""
    if not analise.pode_gravar:
        raise ErroValidacao([("", "a análise contém erros ou nada a gravar; corrija o arquivo e analise de novo")])
    modulo = MODULOS[analise.modulo]
    custo_attr = {"materias_primas": ("custo_compra", MateriaPrima), "mao_de_obra": ("custo_hora", MaoDeObra)}
    # fotografa os preços dos produtos que usam os itens a atualizar (relatório de impacto)
    fotos = {}
    if analise.modulo in custo_attr:
        ids = [validar_registro(sessao, modulo, la.bruto)[1].id for la in analise.linhas if la.acao == "atualizar"]
        prod = impacto.produtos_com_insumos(sessao, ids) if analise.modulo == "materias_primas" \
            else impacto.produtos_com_etapas(sessao, ids)
        fotos = impacto.fotografar(sessao, prod)
    reajustes: list[tuple[str, float | None, float]] = []
    alterados: list[int] = []
    ins = atu = 0
    for la in analise.linhas:
        if la.acao not in ("inserir", "atualizar"):
            continue
        antes = None
        if analise.modulo in custo_attr:
            _, existente, _ = validar_registro(sessao, modulo, la.bruto)
            antes = getattr(existente, custo_attr[analise.modulo][0]) if existente is not None else None
        try:
            obj = gravar(sessao, modulo, la.bruto, origem="importacao")
        except ErroValidacao as e:
            raise ErroValidacao([(c, f"linha {la.linha}: {m}") for c, m in e.erros]) from None
        if la.acao == "inserir":
            ins += 1
        else:
            atu += 1
        if analise.modulo in custo_attr and la.acao == "atualizar":
            depois = getattr(obj, custo_attr[analise.modulo][0])
            if antes is None or abs(depois - antes) > 1e-9:
                reajustes.append((la.chave, antes, depois))
                alterados.append(obj.id)

    afetados: list[str] = []
    if alterados:
        ficha, col = (FichaMP, FichaMP.materia_prima_id) if analise.modulo == "materias_primas" \
            else (FichaMO, FichaMO.mao_de_obra_id)
        afetados = list(sessao.scalars(select(Produto.sku).join(ficha).where(col.in_(alterados))
                                       .distinct().order_by(Produto.sku)))
    linhas_impacto = impacto.comparar(sessao, fotos) if fotos else []
    c = analise.contagem()
    sessao.add(ImportacaoLog(modulo=analise.modulo, arquivo=analise.arquivo[:255], modo=analise.modo,
                             linhas_lidas=len(analise.linhas), inseridas=ins, atualizadas=atu,
                             rejeitadas=c["ignorar"], usuario=usuario,
                             detalhes=json.dumps({"reajustes": reajustes[:500], "produtos_afetados": afetados[:500],
                                                  "colunas_ignoradas": analise.colunas_ignoradas},
                                                 ensure_ascii=False)))
    sessao.flush()
    return ResultadoImportacao(ins, atu, c["ignorar"], reajustes, afetados, linhas_impacto)
