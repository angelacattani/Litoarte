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

from .modelos import ESQUEMAS, Esquema, normalizar_colunas

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
            validos = set(saida.get(t_alvo, ESQUEMAS[t_alvo].vazio())[c_alvo].astype(str))
            orfas = ~df[col].astype(str).isin(validos)
            for v in sorted(set(df.loc[orfas, col].astype(str))):
                erros.append(f"[{tabela}] '{col}' = {v} não existe em {t_alvo}; linhas ignoradas")
            ok &= ~orfas
        saida[tabela] = df[ok].reset_index(drop=True)
    return saida, erros


def _linha(idx: object) -> str:
    # índice 0-based do DataFrame + 2 = linha da planilha (cabeçalho na 1)
    return str(idx + 2) if isinstance(idx, (int, np.integer)) else str(idx)


def _chave_nome(valor: object) -> str:
    """Comparação tolerante: ignora maiúsculas/minúsculas e espaços extras."""
    return " ".join(str(valor).split()).casefold()


def sincronizar_grupos(dados: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Mantém produtos e cadastro de grupos coerentes.

    - Grafias equivalentes ('cozinha', ' Cozinha ') são unificadas na grafia
      já cadastrada (ou na primeira encontrada).
    - Toda combinação grupo/subgrupo usada por um produto passa a existir no
      cadastro de grupos (nunca se descarta produto por grupo inexistente).
    """
    from .modelos import GRUPOS  # import local evita ciclo

    avisos: list[str] = []
    grupos = dados.get("grupos", GRUPOS.vazio()).copy()
    prod = dados.get("produtos", ESQUEMAS["produtos"].vazio()).copy()

    canon_g: dict[str, str] = {}
    canon_s: dict[tuple[str, str], str] = {}

    def canonizar(g: str, sg: str) -> tuple[str, str]:
        g = canon_g.setdefault(_chave_nome(g), " ".join(str(g).split()))
        sg = canon_s.setdefault((_chave_nome(g), _chave_nome(sg)), " ".join(str(sg).split()))
        return g, sg

    if not grupos.empty:
        pares = [canonizar(g, sg) for g, sg in zip(grupos["grupo"], grupos["subgrupo"])]
        grupos[["grupo", "subgrupo"]] = pares
        grupos = grupos.drop_duplicates(subset=["grupo", "subgrupo"], keep="first")

    if not prod.empty:
        pares = [canonizar(g, sg) for g, sg in zip(prod["grupo"], prod["subgrupo"])]
        prod[["grupo", "subgrupo"]] = pares
        existentes = set(zip(grupos["grupo"], grupos["subgrupo"]))
        novos = sorted({p for p in pares if p not in existentes})
        if novos:
            grupos = pd.concat([grupos, pd.DataFrame(novos, columns=["grupo", "subgrupo"])], ignore_index=True)
            avisos.append("Grupos/subgrupos incluídos no cadastro por estarem em uso nos produtos: "
                          + "; ".join(f"{g} › {sg}" for g, sg in novos))

    saida = dict(dados)
    saida["grupos"] = grupos.sort_values(["grupo", "subgrupo"]).reset_index(drop=True)
    saida["produtos"] = prod
    return saida, avisos
