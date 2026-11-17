"""Persistência em SQLite.

O repositório trabalha com DataFrames inteiros por tabela: a interface edita
a tabela e devolve tudo de uma vez (`salvar`), ou a importação mescla
registros pela chave primária (`mesclar`). Todas as escritas passam por
`validacao.validar`.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pandas as pd

from .modelos import ESQUEMAS, ORDEM_TABELAS, PARAMETROS_PADRAO
from .trava import TravaEdicao
from .modelos import (GRUPO_PADRAO, GRUPO_PADRAO_COD, SUBGRUPO_PADRAO, SUBGRUPO_PADRAO_COD)
from .validacao import (checar_referencias, proteger_grupos_em_uso, proximo_codigo,
                        resolver_grupos_produtos, validar)


class SomenteLeitura(PermissionError):
    """Outro computador está com a trava de edição do banco."""


class Repositorio:
    """Acesso ao banco SQLite.

    trava: quando informada (banco em pasta compartilhada), toda gravação
    exige a trava de edição; sem ela, levanta SomenteLeitura.
    """

    def __init__(self, caminho: str | Path = "custos.db", trava: TravaEdicao | None = None):
        self.caminho = str(caminho)
        self.trava = trava
        with self._conexao() as con:
            # DELETE (e não WAL): WAL não funciona em pastas de rede.
            con.execute("PRAGMA journal_mode=DELETE")
            v1 = self._grupos_v1_pendente(con)
            for esq in ESQUEMAS.values():
                con.execute(esq.ddl())
                # migração: bancos criados por versões anteriores ganham as colunas novas
                existentes = {r[1] for r in con.execute(f'PRAGMA table_info("{esq.tabela}")')}
                for c in esq.colunas:
                    if c.nome not in existentes:
                        con.execute(f'ALTER TABLE "{esq.tabela}" ADD COLUMN "{c.nome}" {c.sql}')
            con.execute('CREATE TABLE IF NOT EXISTS parametros (chave TEXT PRIMARY KEY, valor TEXT)')
            if v1:
                self._migrar_grupos_v1(con)
            # grupo/subgrupo padrão sempre disponível para produtos sem classificação
            con.execute("INSERT OR IGNORE INTO grupos (codigo, descricao) VALUES (?, ?)",
                        (GRUPO_PADRAO_COD, GRUPO_PADRAO))
            con.execute("INSERT OR IGNORE INTO subgrupos (grupo_codigo, codigo, descricao) VALUES (?, ?, ?)",
                        (GRUPO_PADRAO_COD, SUBGRUPO_PADRAO_COD, SUBGRUPO_PADRAO))
            con.execute("UPDATE produtos SET grupo_codigo = ? WHERE grupo_codigo IS NULL", (GRUPO_PADRAO_COD,))
            con.execute("UPDATE produtos SET subgrupo_codigo = ? WHERE subgrupo_codigo IS NULL",
                        (SUBGRUPO_PADRAO_COD,))

    # ------------------------------------------------------------- migrações
    @staticmethod
    def _grupos_v1_pendente(con) -> bool:
        """Versão anterior: tabela grupos(grupo, subgrupo) e produtos com nomes."""
        cols = {r[1] for r in con.execute('PRAGMA table_info("grupos")')}
        if "grupo" in cols and "codigo" not in cols:
            con.execute('ALTER TABLE grupos RENAME TO grupos_v1')
            return True
        return False

    @staticmethod
    def _migrar_grupos_v1(con) -> None:
        """Gera códigos (01, 02...) para os grupos/subgrupos por nome e vincula os produtos."""
        pares = set(con.execute("SELECT grupo, subgrupo FROM grupos_v1").fetchall())
        cols_p = {r[1] for r in con.execute('PRAGMA table_info("produtos")')}
        if {"grupo", "subgrupo"} <= cols_p:
            pares |= set(con.execute("SELECT grupo, subgrupo FROM produtos WHERE grupo IS NOT NULL").fetchall())
        cod_g: dict[str, str] = {GRUPO_PADRAO: GRUPO_PADRAO_COD}
        cod_s: dict[tuple[str, str], str] = {}
        for g, sg in sorted(pares, key=lambda x: (str(x[0]).casefold(), str(x[1]).casefold())):
            g, sg = str(g), str(sg or SUBGRUPO_PADRAO)
            if g not in cod_g:
                cod_g[g] = proximo_codigo([c for c in cod_g.values() if c != GRUPO_PADRAO_COD])
            gc = cod_g[g]
            if (gc, sg) not in cod_s:
                existentes = [c for (a, _), c in cod_s.items() if a == gc]
                cod_s[(gc, sg)] = SUBGRUPO_PADRAO_COD if sg == SUBGRUPO_PADRAO else proximo_codigo(existentes)
        con.executemany("INSERT OR IGNORE INTO grupos (codigo, descricao) VALUES (?, ?)",
                        [(c, g) for g, c in cod_g.items()])
        con.executemany("INSERT OR IGNORE INTO subgrupos (grupo_codigo, codigo, descricao) VALUES (?, ?, ?)",
                        [(gc, c, sg) for (gc, sg), c in cod_s.items()])
        if {"grupo", "subgrupo"} <= cols_p:
            for g, gc in cod_g.items():
                con.execute("UPDATE produtos SET grupo_codigo = ? WHERE grupo = ?", (gc, g))
            for (gc, sg), c in cod_s.items():
                con.execute("UPDATE produtos SET subgrupo_codigo = ? WHERE grupo_codigo = ? AND subgrupo = ?",
                            (c, gc, sg))

    @property
    def pode_gravar(self) -> bool:
        return self.trava is None or self.trava.adquirir()

    def _exigir_escrita(self) -> None:
        if not self.pode_gravar:
            info = self.trava.ler()
            quem = f" por {info.dono}" if info else ""
            raise SomenteLeitura(f"O banco está em edição{quem}. Alterações não foram salvas.")

    @contextmanager
    def _conexao(self):
        # timeout: espera até 30 s se o arquivo estiver momentaneamente bloqueado (rede)
        con = sqlite3.connect(self.caminho, timeout=30)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ------------------------------------------------------------------ leitura
    def carregar(self, tabela: str) -> pd.DataFrame:
        esq = ESQUEMAS[tabela]
        with self._conexao() as con:
            df = pd.read_sql_query(f'SELECT * FROM "{tabela}"', con)
        if df.empty:
            return esq.vazio()
        df, _ = validar(df, esq)  # garante dtypes consistentes
        return df.sort_values(list(esq.chave)).reset_index(drop=True)

    def carregar_tudo(self) -> dict[str, pd.DataFrame]:
        return {t: self.carregar(t) for t in ORDEM_TABELAS}

    # ------------------------------------------------------------------ escrita
    def salvar(self, tabela: str, df: pd.DataFrame) -> list[str]:
        """Substitui o conteúdo da tabela. Retorna avisos de validação."""
        return self.importar({tabela: df}, modo="substituir")

    def mesclar(self, tabela: str, df: pd.DataFrame) -> list[str]:
        """Insere ou atualiza registros pela chave primária (upsert)."""
        return self.importar({tabela: df}, modo="mesclar")

    def importar(self, novos: dict[str, pd.DataFrame], modo: str = "mesclar") -> list[str]:
        """Importa várias tabelas de uma vez, numa única transação.

        modo='mesclar'   -> upsert pela chave; registros existentes não citados permanecem.
        modo='substituir'-> as tabelas presentes em `novos` são substituídas integralmente.
        """
        if modo not in ("mesclar", "substituir"):
            raise ValueError("modo deve ser 'mesclar' ou 'substituir'")
        erros: list[str] = []
        dados = self.carregar_tudo()
        antes = dict(dados)
        for tabela in ORDEM_TABELAS:
            if tabela not in novos:
                continue
            bruto = novos[tabela]
            if tabela == "produtos":
                bruto, dados["grupos"], dados["subgrupos"], e = resolver_grupos_produtos(
                    bruto, dados["grupos"], dados["subgrupos"])
                erros += e
            df, e = validar(bruto, tabela)
            erros += e
            if modo == "mesclar" and not dados[tabela].empty:
                chave = list(ESQUEMAS[tabela].chave)
                base = dados[tabela].set_index(chave)
                df = pd.concat([base[~base.index.isin(df.set_index(chave).index)].reset_index(), df],
                               ignore_index=True)
            dados[tabela] = df
        dados, e = proteger_grupos_em_uso(dados, antes)
        erros += e
        dados, e = checar_referencias(dados)
        erros += e
        self._gravar(dados)
        return erros

    def alterar_codigo_grupo(self, antigo: str, novo: str) -> int:
        """Troca o código de um grupo em cascata (subgrupos e produtos). Retorna nº de produtos."""
        if antigo == GRUPO_PADRAO_COD:
            raise ValueError(f"O grupo padrão ({GRUPO_PADRAO_COD} - {GRUPO_PADRAO}) não pode ter o código alterado.")
        dados = self.carregar_tudo()
        if novo in set(dados["grupos"]["codigo"]):
            raise ValueError(f"Já existe um grupo com o código {novo}.")
        for t, col in (("grupos", "codigo"), ("subgrupos", "grupo_codigo"), ("produtos", "grupo_codigo")):
            dados[t].loc[dados[t][col] == antigo, col] = novo
        n = int((dados["produtos"]["grupo_codigo"] == novo).sum())
        self.importar({t: dados[t] for t in ("grupos", "subgrupos", "produtos")}, modo="substituir")
        return n

    def alterar_codigo_subgrupo(self, grupo: str, antigo: str, novo: str) -> int:
        """Troca o código de um subgrupo (dentro do grupo) e nos produtos. Retorna nº de produtos."""
        dados = self.carregar_tudo()
        sg, p = dados["subgrupos"], dados["produtos"]
        if ((sg["grupo_codigo"] == grupo) & (sg["codigo"] == novo)).any():
            raise ValueError(f"O grupo {grupo} já tem um subgrupo com o código {novo}.")
        sg.loc[(sg["grupo_codigo"] == grupo) & (sg["codigo"] == antigo), "codigo"] = novo
        mp = (p["grupo_codigo"] == grupo) & (p["subgrupo_codigo"] == antigo)
        p.loc[mp, "subgrupo_codigo"] = novo
        self.importar({"subgrupos": sg, "produtos": p}, modo="substituir")
        return int(mp.sum())

    def excluir_tudo(self) -> None:
        self._exigir_escrita()
        with self._conexao() as con:
            for t in ORDEM_TABELAS:
                con.execute(f'DELETE FROM "{t}"')
            con.execute("DELETE FROM parametros")
            con.execute("INSERT INTO grupos (codigo, descricao) VALUES (?, ?)", (GRUPO_PADRAO_COD, GRUPO_PADRAO))
            con.execute("INSERT INTO subgrupos (grupo_codigo, codigo, descricao) VALUES (?, ?, ?)",
                        (GRUPO_PADRAO_COD, SUBGRUPO_PADRAO_COD, SUBGRUPO_PADRAO))

    def _gravar(self, dados: dict[str, pd.DataFrame]) -> None:
        self._exigir_escrita()
        with self._conexao() as con:
            for tabela, df in dados.items():
                esq = ESQUEMAS[tabela]
                con.execute(f'DELETE FROM "{tabela}"')
                if df.empty:
                    continue
                linhas = df[esq.nomes].astype(object).where(df[esq.nomes].notna(), None).values.tolist()
                cols = ", ".join(f'"{c}"' for c in esq.nomes)   # nomeadas: ordem física pode diferir após migração
                ph = ", ".join("?" * len(esq.nomes))
                con.executemany(f'INSERT INTO "{tabela}" ({cols}) VALUES ({ph})', linhas)

    # --------------------------------------------------------------- parâmetros
    def parametros(self) -> dict[str, object]:
        with self._conexao() as con:
            linhas = con.execute("SELECT chave, valor FROM parametros").fetchall()
        p = dict(PARAMETROS_PADRAO)
        p.update({k: json.loads(v) for k, v in linhas})
        return p

    def salvar_parametros(self, valores: dict[str, object]) -> None:
        self._exigir_escrita()
        with self._conexao() as con:
            con.executemany(
                "INSERT INTO parametros (chave, valor) VALUES (?, ?) "
                "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                [(k, json.dumps(v)) for k, v in valores.items()],
            )

    # ------------------------------------------------------------------ backup
    def copiar_para(self, destino: str | Path) -> Path:
        """Cópia consistente do banco (API de backup do SQLite, segura mesmo em uso)."""
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with self._conexao() as origem:
            dst = sqlite3.connect(destino)
            try:
                origem.backup(dst)
            finally:
                dst.close()
        return destino

    def backup_diario(self, pasta: str | Path | None = None, manter: int = 30) -> Path | None:
        """Faz no máximo um backup por dia em <pasta do banco>/backups. Retorna o arquivo criado."""
        pasta = Path(pasta) if pasta else Path(self.caminho).parent / "backups"
        alvo = pasta / f"{Path(self.caminho).stem}_{date.today().isoformat()}.db"
        if alvo.exists():
            return None
        self.copiar_para(alvo)
        antigos = sorted(pasta.glob(f"{Path(self.caminho).stem}_*.db"))[:-manter]
        for a in antigos:
            a.unlink(missing_ok=True)
        return alvo
