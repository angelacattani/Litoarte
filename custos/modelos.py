"""Esquema de dados do sistema de custos.

Cada tabela é descrita por um `Esquema`: colunas, tipos, chave primária e
valores padrão. O mesmo esquema serve para:
  - criar as tabelas no SQLite (repositorio.py);
  - validar/normalizar DataFrames vindos da interface ou de importação
    (importexport.py);
  - gerar a planilha-modelo de importação.

Convenção: todo percentual é armazenado em pontos percentuais
(18.0 significa 18 %), nunca como fração.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

import pandas as pd

# Tipos lógicos aceitos nos esquemas -> tipo SQLite
_SQL = {"texto": "TEXT", "real": "REAL", "inteiro": "INTEGER", "data": "TEXT"}


@dataclass(frozen=True)
class Coluna:
    nome: str
    tipo: str = "texto"          # texto | real | inteiro | data
    obrigatoria: bool = False
    padrao: object = None
    minimo: float | None = 0.0   # só para numéricos; None = sem limite
    descricao: str = ""


@dataclass(frozen=True)
class Esquema:
    tabela: str
    titulo: str
    colunas: tuple[Coluna, ...]
    chave: tuple[str, ...]
    referencias: dict[str, str] = field(default_factory=dict)  # coluna -> tabela.coluna

    @property
    def nomes(self) -> list[str]:
        return [c.nome for c in self.colunas]

    def coluna(self, nome: str) -> Coluna:
        return next(c for c in self.colunas if c.nome == nome)

    def ddl(self) -> str:
        cols = ", ".join(f'"{c.nome}" {_SQL[c.tipo]}' for c in self.colunas)
        pk = ", ".join(f'"{k}"' for k in self.chave)
        return f'CREATE TABLE IF NOT EXISTS "{self.tabela}" ({cols}, PRIMARY KEY ({pk}))'

    def vazio(self) -> pd.DataFrame:
        return pd.DataFrame({c.nome: pd.Series(dtype=_dtype(c.tipo)) for c in self.colunas})


def _dtype(tipo: str) -> str:
    return {"real": "float64", "inteiro": "Int64"}.get(tipo, "object")


# --------------------------------------------------------------------------
# Esquemas
# --------------------------------------------------------------------------
MATERIAS_PRIMAS = Esquema(
    "materias_primas", "Matérias-primas",
    (
        Coluna("codigo", obrigatoria=True),
        Coluna("descricao", obrigatoria=True),
        Coluna("unidade", padrao="un", descricao="kg, m, L, un..."),
        Coluna("custo_unitario", "real", obrigatoria=True, descricao="R$ por unidade de compra, já com frete e impostos não recuperáveis"),
        Coluna("fornecedor"),
    ),
    chave=("codigo",),
)

MAO_DE_OBRA = Esquema(
    "mao_de_obra", "Mão de obra direta",
    (
        Coluna("codigo", obrigatoria=True),
        Coluna("funcao", obrigatoria=True),
        Coluna("salario_mensal", "real", obrigatoria=True),
        Coluna("encargos_pct", "real", padrao=70.0, descricao="encargos sociais + provisões (13º, férias, FGTS, INSS...) em % do salário"),
        Coluna("horas_produtivas_mes", "real", padrao=176.0, descricao="horas efetivamente produtivas por funcionário"),
        Coluna("quantidade", "inteiro", padrao=1, descricao="nº de funcionários nesta função"),
    ),
    chave=("codigo",),
)

CUSTOS_FIXOS = Esquema(
    "custos_fixos", "Custos e despesas fixas",
    (
        Coluna("codigo", obrigatoria=True),
        Coluna("descricao", obrigatoria=True),
        Coluna("categoria", padrao="Geral"),
        Coluna("valor_mensal", "real", obrigatoria=True),
    ),
    chave=("codigo",),
)

CUSTOS_VARIAVEIS = Esquema(
    "custos_variaveis", "Custos e despesas variáveis",
    (
        Coluna("codigo", obrigatoria=True),
        Coluna("descricao", obrigatoria=True),
        Coluna("tipo", padrao="percentual", descricao="percentual (sobre o preço de venda) ou unitario (R$ por unidade vendida)"),
        Coluna("valor", "real", obrigatoria=True),
    ),
    chave=("codigo",),
)

PRODUTOS = Esquema(
    "produtos", "Produtos",
    (
        Coluna("codigo", obrigatoria=True),
        Coluna("descricao", obrigatoria=True),
        Coluna("unidade", padrao="un"),
        Coluna("margem_desejada_pct", "real", descricao="vazio = usa a margem padrão dos parâmetros"),
        Coluna("volume_mensal", "real", padrao=0.0, descricao="vendas mensais previstas (unidades)"),
        Coluna("preco_atual", "real", descricao="preço praticado hoje (opcional)"),
    ),
    chave=("codigo",),
)

COMPOSICAO = Esquema(
    "composicao", "Ficha técnica — matérias-primas",
    (
        Coluna("produto_codigo", obrigatoria=True),
        Coluna("mp_codigo", obrigatoria=True),
        Coluna("quantidade", "real", obrigatoria=True, descricao="na unidade da matéria-prima, por unidade de produto"),
        Coluna("perda_pct", "real", padrao=0.0, descricao="perda/refugo do processo"),
    ),
    chave=("produto_codigo", "mp_codigo"),
    referencias={"produto_codigo": "produtos.codigo", "mp_codigo": "materias_primas.codigo"},
)

PRODUTO_MAO_DE_OBRA = Esquema(
    "produto_mao_de_obra", "Ficha técnica — mão de obra",
    (
        Coluna("produto_codigo", obrigatoria=True),
        Coluna("mo_codigo", obrigatoria=True),
        Coluna("horas", "real", obrigatoria=True, descricao="horas por unidade de produto"),
    ),
    chave=("produto_codigo", "mo_codigo"),
    referencias={"produto_codigo": "produtos.codigo", "mo_codigo": "mao_de_obra.codigo"},
)

CONCORRENTES = Esquema(
    "concorrentes", "Preços de concorrentes",
    (
        Coluna("produto_codigo", obrigatoria=True),
        Coluna("concorrente", obrigatoria=True),
        Coluna("preco", "real", obrigatoria=True),
        Coluna("data_coleta", "data"),
        Coluna("observacao"),
    ),
    chave=("produto_codigo", "concorrente"),
    referencias={"produto_codigo": "produtos.codigo"},
)

ESQUEMAS: dict[str, Esquema] = {
    e.tabela: e
    for e in (MATERIAS_PRIMAS, MAO_DE_OBRA, CUSTOS_FIXOS, CUSTOS_VARIAVEIS,
              PRODUTOS, COMPOSICAO, PRODUTO_MAO_DE_OBRA, CONCORRENTES)
}

# Ordem que respeita dependências (pais antes dos filhos) — usada em import.
ORDEM_TABELAS = list(ESQUEMAS)

# --------------------------------------------------------------------------
# Parâmetros gerais (tabela chave/valor)
# --------------------------------------------------------------------------
METODOS_RATEIO = {
    "percentual_faturamento": "% sobre o faturamento previsto (fixos ÷ faturamento)",
    "por_hora_mo": "Por hora de mão de obra direta (fixos ÷ horas produtivas)",
    "por_unidade": "Igual por unidade vendida (fixos ÷ volume total)",
}

PARAMETROS_PADRAO: dict[str, object] = {
    "margem_padrao_pct": 15.0,
    "metodo_rateio": "percentual_faturamento",
    "faturamento_mensal_previsto": 0.0,
    "tolerancia_concorrencia_pct": 5.0,  # faixa ± em torno da média para "alinhado"
}


# --------------------------------------------------------------------------
# Normalização de nomes de colunas (importação de planilhas de terceiros)
# --------------------------------------------------------------------------
ALIASES = {
    "cod": "codigo", "codigo_produto": "codigo", "sku": "codigo", "id": "codigo",
    "nome": "descricao", "produto": "descricao", "descricao_produto": "descricao",
    "un": "unidade", "und": "unidade",
    "custo": "custo_unitario", "preco_custo": "custo_unitario", "valor_unitario": "custo_unitario",
    "preco": "preco", "preco_venda": "preco_atual", "preco_praticado": "preco_atual",
    "margem": "margem_desejada_pct", "margem_pct": "margem_desejada_pct",
    "volume": "volume_mensal", "vendas_mes": "volume_mensal",
    "salario": "salario_mensal", "encargos": "encargos_pct", "horas_mes": "horas_produtivas_mes",
    "valor_mes": "valor_mensal", "produto_cod": "produto_codigo", "materia_prima": "mp_codigo",
    "perda": "perda_pct",
}


def normalizar_nome(nome: object) -> str:
    """'Preço Atual (R$)' -> 'preco_atual_rs'."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    s = "".join(ch if ch.isalnum() else "_" for ch in s.lower().strip())
    s = "_".join(p for p in s.split("_") if p)
    return s


def normalizar_colunas(df: pd.DataFrame, esquema: Esquema) -> pd.DataFrame:
    """Renomeia colunas para os nomes do esquema, aceitando aliases comuns."""
    validos = set(esquema.nomes)
    mapa = {}
    for col in df.columns:
        n = normalizar_nome(col)
        for sufixo in ("_rs", "_r", "_pct_", "_un"):   # "(R$)", "R$", unidades
            if n.endswith(sufixo) and n[: -len(sufixo)] in validos | set(ALIASES):
                n = n[: -len(sufixo)]
                break
        if n not in validos:
            n = ALIASES.get(n, n)
        if n in validos and n not in mapa.values():
            mapa[col] = n
    return df.rename(columns=mapa)
