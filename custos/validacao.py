"""Limpeza e validação de DataFrames contra os esquemas.

Toda entrada de dados (edição na interface, CSV, XLSX) passa por `validar`,
que devolve o DataFrame normalizado e a lista de problemas encontrados.
Linhas com erro grave (campo obrigatório vazio, número inválido, negativo)
são descartadas e relatadas; o restante segue.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .modelos import ESQUEMAS, Esquema, normalizar_colunas, normalizar_nome

_NUM_BR = re.compile(r"^-?[\d.]*,\d+$")  # 1.234,56


def para_numero(valor: object) -> float:
    """Converte '1.234,56', 'R$ 12,90', '18%', 12.5 -> float. Vazio -> NaN."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return np.nan
    if isinstance(valor, (int, float, np.number)):
        return float(valor)
    s = str(valor).strip().replace("R$", "").replace("%", "").replace(" ", "").replace("\xa0", "")
    if s == "" or s.lower() in {"nan", "none", "-"}:
        return np.nan
    if _NUM_BR.match(s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"valor numérico inválido: {valor!r}") from None


def validar(df: pd.DataFrame, esquema: Esquema | str) -> tuple[pd.DataFrame, list[str]]:
    esq = ESQUEMAS[esquema] if isinstance(esquema, str) else esquema
    erros: list[str] = []
    df = normalizar_colunas(df.copy(), esq)

    faltando = [c.nome for c in esq.colunas if c.obrigatoria and c.nome not in df.columns]
    if faltando:
        return esq.vazio(), [f"[{esq.tabela}] colunas obrigatórias ausentes: {', '.join(faltando)}"]

    for c in esq.colunas:                       # cria colunas opcionais ausentes
        if c.nome not in df.columns:
            df[c.nome] = c.padrao
    df = df[esq.nomes]
    df = df.dropna(how="all")                   # linhas totalmente vazias (data_editor)

    invalidas = pd.Series(False, index=df.index)
    for c in esq.colunas:
        col = df[c.nome]
        if c.tipo in ("real", "inteiro"):
            conv = []
            for idx, v in col.items():
                try:
                    conv.append(para_numero(v))
                except ValueError as e:
                    erros.append(f"[{esq.tabela}] linha {_linha(idx)}, '{c.nome}': {e}")
                    invalidas[idx] = True
                    conv.append(np.nan)
            col = pd.Series(conv, index=df.index, dtype="float64")
            if c.padrao is not None:
                col = col.fillna(float(c.padrao))
            if c.minimo is not None:
                neg = col < c.minimo
                for idx in col[neg].index:
                    erros.append(f"[{esq.tabela}] linha {_linha(idx)}, '{c.nome}' não pode ser menor que {c.minimo:g}")
                invalidas |= neg
            df[c.nome] = col.round(0).astype("Int64") if c.tipo == "inteiro" else col
        elif c.tipo == "data":
            datas = pd.to_datetime(col, errors="coerce", dayfirst=True)
            df[c.nome] = datas.dt.strftime("%Y-%m-%d").where(datas.notna(), None)
        else:
            # códigos numéricos lidos do Excel como 1001.0 -> "1001"
            col = col.map(lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else v)
            txt = col.astype("string").str.strip()
            txt = txt.mask(txt.isin(["", "nan", "None", "<NA>"]))
            if c.padrao is not None:
                txt = txt.fillna(str(c.padrao))
            df[c.nome] = txt.astype(object).where(txt.notna(), None)

        if c.obrigatoria:
            vazio = df[c.nome].isna()
            for idx in df[vazio].index:
                erros.append(f"[{esq.tabela}] linha {_linha(idx)}: '{c.nome}' é obrigatório")
            invalidas |= vazio

    if esq.tabela == "custos_variaveis":
        tipo = df["tipo"].astype(str).str.lower().str.replace("á", "a")
        tipo = tipo.replace({"%": "percentual", "r$": "unitario", "valor": "unitario"})
        ruins = ~tipo.isin(["percentual", "unitario"])
        for idx in df[ruins].index:
            erros.append(f"[custos_variaveis] linha {_linha(idx)}: tipo deve ser 'percentual' ou 'unitario'")
        df["tipo"] = tipo
        invalidas |= ruins

    if "base" in esq.nomes:
        from .modelos import ALIASES_BASE, BASES_CALCULO, BASES_MO
        permitidas = BASES_MO if esq.tabela in ("produto_mao_de_obra", "mo_subgrupo") else tuple(BASES_CALCULO)
        base = df["base"].astype(str).str.strip().str.lower()
        base = base.map(lambda b: ALIASES_BASE.get(b, b))
        ruins = ~base.isin(permitidas)
        for idx in df[ruins].index:
            erros.append(f"[{esq.tabela}] linha {_linha(idx)}: base '{df.at[idx, 'base']}' inválida "
                         f"(use {', '.join(permitidas)})")
        df["base"] = base
        invalidas |= ruins

    df = df[~invalidas]

    dup = df.duplicated(subset=list(esq.chave), keep="last")
    if dup.any():
        chaves = df.loc[dup, list(esq.chave)].astype(str).agg("/".join, axis=1).tolist()
        erros.append(f"[{esq.tabela}] chaves duplicadas (mantida a última ocorrência): {', '.join(chaves)}")
        df = df[~dup]

    return df.reset_index(drop=True), erros


def checar_referencias(dados: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Remove linhas de tabelas-filhas que apontam para registros inexistentes."""
    erros: list[str] = []
    saida = dict(dados)
    for tabela, esq in ESQUEMAS.items():
        if not esq.referencias or tabela not in saida:
            continue
        df = saida[tabela]
        ok = pd.Series(True, index=df.index)
        for col, alvo in esq.referencias.items():
            t_alvo, c_alvo = alvo.split(".")
            cols, cols_alvo = (list(col), c_alvo.split(",")) if isinstance(col, tuple) else ([col], [c_alvo])
            base_alvo = saida.get(t_alvo, ESQUEMAS[t_alvo].vazio())
            validos = set(base_alvo[cols_alvo].astype(str).agg("/".join, axis=1)) if not base_alvo.empty else set()
            chaves = df[cols].astype(str).agg("/".join, axis=1) if not df.empty else pd.Series(dtype=str)
            orfas = ~chaves.isin(validos)
            for v in sorted(set(chaves[orfas])):
                erros.append(f"[{tabela}] {'/'.join(cols)} = {v} não existe em {t_alvo}; linhas ignoradas")
            ok &= ~orfas
        saida[tabela] = df[ok].reset_index(drop=True)
    return saida, erros


def _linha(idx: object) -> str:
    # índice 0-based do DataFrame + 2 = linha da planilha (cabeçalho na 1)
    return str(idx + 2) if isinstance(idx, (int, np.integer)) else str(idx)



# --------------------------------------------------------------------------
# Grupos e subgrupos
# --------------------------------------------------------------------------
def _k(valor: object) -> str:
    """Comparação tolerante de nomes: ignora maiúsculas/minúsculas e espaços extras."""
    return " ".join(str(valor).split()).casefold()


def _limpo(valor: object) -> str | None:
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    s = " ".join(str(valor).split())
    return s or None


def proximo_codigo(existentes) -> str:
    """Próximo código numérico livre, com zeros à esquerda (mín. 2 dígitos)."""
    nums = [c for c in map(str, existentes) if c.isdigit()]
    largura = max([2] + [len(c) for c in nums])
    return str(max([0] + [int(c) for c in nums]) + 1).zfill(largura)


def resolver_grupos_produtos(bruto: pd.DataFrame, grupos: pd.DataFrame, subgrupos: pd.DataFrame
                             ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Preenche grupo_codigo/subgrupo_codigo de uma planilha de produtos.

    Aceita planilhas com códigos, só com nomes (Grupo, Família, Subcategoria...)
    ou com ambos. Regras:
      - código informado e existente: usado (o nome é ignorado);
      - código informado e inexistente: grupo/subgrupo criado com esse código
        e o nome da planilha (ou 'Grupo <código>');
      - só o nome: procura pela descrição cadastrada (sem diferenciar
        maiúsculas/espaços) ou por um código igual ao texto; se não achar,
        cria com o próximo código livre;
      - nada informado: grupo 00 'Sem grupo' / subgrupo 00 'Geral'.
    Retorna (produtos, grupos, subgrupos, avisos).
    """
    from .modelos import (GRUPO_PADRAO, GRUPO_PADRAO_COD, NOMES_GRUPO, NOMES_SUBGRUPO, PRODUTOS,
                          SUBGRUPO_PADRAO, SUBGRUPO_PADRAO_COD)

    ren = {}
    for col in bruto.columns:
        n = normalizar_nome(col)
        if n in NOMES_GRUPO:
            ren[col] = "_grupo_nome"
        elif n in NOMES_SUBGRUPO:
            ren[col] = "_subgrupo_nome"
    df = normalizar_colunas(bruto.rename(columns=ren), PRODUTOS)

    g_desc = dict(zip(grupos["codigo"].astype(str), grupos["descricao"]))
    s_desc = {(str(a), str(b)): d for a, b, d in zip(subgrupos["grupo_codigo"], subgrupos["codigo"],
                                                   subgrupos["descricao"])}
    criados_g, criados_s = [], []

    def criar_g(cod, nome):
        g_desc[cod] = nome
        criados_g.append(f"{cod} {nome}")

    def criar_s(gc, cod, nome):
        s_desc[(gc, cod)] = nome
        criados_s.append(f"{gc}/{cod} {nome}")

    def equivalente(cod, existentes):
        """'1' casa com '01' (o Excel remove zeros à esquerda de códigos numéricos)."""
        if cod in existentes or not cod.isdigit():
            return cod
        return next((c for c in existentes if c.isdigit() and int(c) == int(cod)), cod)

    def grupo(cod, nome):
        if cod:
            cod = equivalente(cod, g_desc)
            if cod not in g_desc:
                criar_g(cod, nome or f"Grupo {cod}")
            return cod
        if nome:
            achado = next((c for c, d in g_desc.items() if _k(d) == _k(nome)), None)
            if achado is None and nome in g_desc:
                achado = nome
            if achado is None:
                achado = proximo_codigo(g_desc)
                criar_g(achado, nome)
            return achado
        if GRUPO_PADRAO_COD not in g_desc:
            criar_g(GRUPO_PADRAO_COD, GRUPO_PADRAO)
        return GRUPO_PADRAO_COD

    def subgrupo(gc, cod, nome):
        do_grupo = {c: d for (g, c), d in s_desc.items() if g == gc}
        if cod:
            cod = equivalente(cod, do_grupo)
            if cod not in do_grupo:
                criar_s(gc, cod, nome or f"Subgrupo {cod}")
            return cod
        if nome:
            achado = next((c for c, d in do_grupo.items() if _k(d) == _k(nome)), None)
            if achado is None and nome in do_grupo:
                achado = nome
            if achado is None:
                achado = proximo_codigo(do_grupo)
                criar_s(gc, achado, nome)
            return achado
        if SUBGRUPO_PADRAO_COD not in do_grupo:
            criar_s(gc, SUBGRUPO_PADRAO_COD, SUBGRUPO_PADRAO)
        return SUBGRUPO_PADRAO_COD

    gcods, scods = [], []
    for _, r in df.iterrows():
        if all(_limpo(r.get(c)) is None for c in ("codigo", "descricao")):
            gcods.append(None)
            scods.append(None)
            continue
        gc = grupo(_limpo(r.get("grupo_codigo")), _limpo(r.get("_grupo_nome")))
        gcods.append(gc)
        scods.append(subgrupo(gc, _limpo(r.get("subgrupo_codigo")), _limpo(r.get("_subgrupo_nome"))))
    df["grupo_codigo"], df["subgrupo_codigo"] = gcods, scods
    df = df.drop(columns=[c for c in ("_grupo_nome", "_subgrupo_nome") if c in df.columns])

    avisos = []
    if criados_g:
        avisos.append("Grupos criados: " + "; ".join(criados_g))
    if criados_s:
        avisos.append("Subgrupos criados (grupo/subgrupo): " + "; ".join(criados_s))
    novos_g = pd.DataFrame({"codigo": list(g_desc), "descricao": list(g_desc.values())})
    novos_s = pd.DataFrame([{"grupo_codigo": g, "codigo": c, "descricao": d} for (g, c), d in s_desc.items()],
                           columns=["grupo_codigo", "codigo", "descricao"])
    return df, novos_g, novos_s, avisos


def proteger_grupos_em_uso(dados: dict[str, pd.DataFrame], antes: dict[str, pd.DataFrame]
                           ) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Grupo/subgrupo usado por produto não pode sumir: é restaurado (com a
    descrição anterior) ou, se nunca existiu, criado com nome provisório."""
    avisos: list[str] = []
    g, sg, p = dados["grupos"].copy(), dados["subgrupos"].copy(), dados["produtos"]
    if p.empty:
        return dados, avisos
    uso_g = p.groupby("grupo_codigo").size()
    faltam = [c for c in uso_g.index if c not in set(g["codigo"])]
    if faltam:
        ant = antes["grupos"].set_index("codigo")["descricao"]
        g = pd.concat([g, pd.DataFrame({"codigo": faltam,
                                        "descricao": [ant.get(c, f"Grupo {c}") for c in faltam]})],
                      ignore_index=True)
        avisos.append("Grupos mantidos por estarem em uso: "
                      + "; ".join(f"{c} ({uso_g[c]} produto(s))" for c in faltam))
    uso_s = p.groupby(["grupo_codigo", "subgrupo_codigo"]).size()
    atuais = set(zip(sg["grupo_codigo"], sg["codigo"]))
    faltam_s = [k for k in uso_s.index if k not in atuais]
    if faltam_s:
        ant = {(a, b): d for a, b, d in zip(antes["subgrupos"]["grupo_codigo"], antes["subgrupos"]["codigo"],
                                            antes["subgrupos"]["descricao"])}
        sg = pd.concat([sg, pd.DataFrame([{"grupo_codigo": a, "codigo": b,
                                           "descricao": ant.get((a, b), f"Subgrupo {b}")} for a, b in faltam_s])],
                       ignore_index=True)
        avisos.append("Subgrupos mantidos por estarem em uso: "
                      + "; ".join(f"{a}/{b} ({uso_s[(a, b)]} produto(s))" for a, b in faltam_s))
    saida = dict(dados)
    saida["grupos"], saida["subgrupos"] = g, sg
    return saida, avisos
