"""Leitura de XLSX/CSV e reconhecimento de colunas."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from ..domain.services import valores as V
from ..domain.services.cadastros import Modulo

ABA_DADOS = "dados"

# nomes de coluna usuais em planilhas de terceiros -> campo do módulo
ALIASES = {
    "*": {"descricao_nome": "nome", "situacao": "ativo", "status": "ativo"},
    "materias_primas": {"codigo": "sku", "cod": "sku", "descricao": "nome", "custo": "custo_compra",
                        "custo_unitario": "custo_compra", "preco": "custo_compra", "preco_compra": "custo_compra",
                        "unidade": "unidade_compra", "un": "unidade_compra", "perda": "perda_pct",
                        "conteudo": "fator_conversao", "rendimento": "fator_conversao"},
    "mao_de_obra": {"funcao": "etapa", "descricao": "etapa", "custo_hora_r": "custo_hora", "valor_hora": "custo_hora",
                    "custo_min": "custo_minuto", "valor_minuto": "custo_minuto", "salario": "salario_mensal",
                    "encargos": "encargos_pct", "horas_mes": "horas_produtivas_mes"},
    "custos_fixos": {"valor": "valor_mensal", "valor_mes": "valor_mensal"},
    "custos_variaveis": {"percentual": "valor", "perfil": "perfis", "canal": "perfis", "canais": "perfis"},
    "grupos": {"descricao": "nome"},
    "subgrupos": {"grupo_codigo": "grupo", "cod_grupo": "grupo", "descricao": "nome"},
    "produtos": {"codigo": "sku", "descricao": "nome", "grupo_codigo": "grupo", "cod_grupo": "grupo",
                 "subgrupo_codigo": "subgrupo", "cod_subgrupo": "subgrupo", "largura": "largura_cm",
                 "altura": "altura_cm", "margem": "margem_desejada_pct", "preco": "preco_praticado",
                 "preco_venda": "preco_praticado", "perfil": "perfil_venda", "canal": "perfil_venda"},
    "ficha_materiais": {"produto_sku": "produto", "sku_produto": "produto", "insumo_sku": "insumo",
                        "materia_prima": "insumo", "sku_insumo": "insumo", "modo": "modo_qtd", "qtd": "quantidade",
                        "perda": "perda_pct"},
    "ficha_mao_de_obra": {"produto_sku": "produto", "sku_produto": "produto", "etapa_codigo": "etapa",
                          "mao_de_obra": "etapa", "minutos": "tempo", "unidade": "unidade_tempo"},
}


def mapear_colunas(modulo: Modulo, cabecalhos: list[str]) -> tuple[dict[str, str], list[str]]:
    """{cabeçalho original: nome do campo}, [cabeçalhos ignorados]."""
    por_chave = {}
    for c in modulo.campos:
        por_chave[V.chave(c.nome)] = c.nome
        por_chave.setdefault(V.chave(c.rotulo), c.nome)
    aliases = {**ALIASES["*"], **ALIASES.get(modulo.chave, {})}
    validos = {c.nome for c in modulo.campos}
    mapa, ignoradas = {}, []
    for h in cabecalhos:
        k = V.chave(h)
        for suf in ("_r$", "_r", "_%"):          # "Custo (R$)", "Perda (%)"
            if k.endswith(suf) and k[: -len(suf)] in por_chave | aliases:
                k = k[: -len(suf)]
        nome = por_chave.get(k) or aliases.get(k)
        if nome in validos and nome not in mapa.values():
            mapa[h] = nome
        else:
            ignoradas.append(str(h))
    return mapa, ignoradas


def ler_tabela(conteudo: bytes, nome_arquivo: str) -> pd.DataFrame:
    sufixo = Path(nome_arquivo).suffix.lower()
    if sufixo in (".xlsx", ".xlsm", ".xls"):
        abas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, dtype=object)
        df = abas.get(ABA_DADOS)
        if df is None:
            df = next(iter(v for k, v in abas.items() if k.lower() != "instrucoes"), None)
        if df is None:
            raise ValueError("planilha sem abas de dados")
        return df
    if sufixo in (".csv", ".txt"):
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                texto = conteudo.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        return pd.read_csv(io.StringIO(texto), sep=None, engine="python", dtype=str, keep_default_na=False)
    raise ValueError(f"formato não suportado: {sufixo or nome_arquivo} (use .xlsx ou .csv)")


def linhas_do_arquivo(modulo: Modulo, conteudo: bytes, nome_arquivo: str
                      ) -> tuple[list[tuple[int, dict]], list[str], list[str]]:
    """[(nº da linha na planilha, {campo: valor bruto})], colunas reconhecidas, colunas ignoradas."""
    df = ler_tabela(conteudo, nome_arquivo)
    mapa, ignoradas = mapear_colunas(modulo, [str(c) for c in df.columns])
    df = df.rename(columns={str(k): v for k, v in mapa.items()})
    linhas = []
    for i, registro in enumerate(df[list(mapa.values())].to_dict("records"), start=2):
        if all(V.vazio(v) for v in registro.values()):
            continue
        linhas.append((i, registro))
    return linhas, list(mapa.values()), ignoradas
