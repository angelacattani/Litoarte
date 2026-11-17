"""Trava de edição para banco SQLite em pasta compartilhada.

O SQLite não foi feito para vários computadores gravando ao mesmo tempo
pela rede (o bloqueio de arquivos em SMB/OneDrive não é confiável). Por
isso o sistema usa uma regra simples: **um editor por vez**.

Ao lado do banco fica `custos.db.lock`, com quem está editando e quando foi
a última atividade. Quem abre o sistema enquanto a trava pertence a outra
pessoa entra em **modo leitura** (vê preços e relatórios, não grava).
A trava expira após `validade_min` minutos sem atividade, para não ficar
presa se o editor fechar o programa sem liberar.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


def identidade_local() -> str:
    try:
        usuario = getpass.getuser()
    except Exception:
        usuario = "usuario"
    return f"{usuario}@{socket.gethostname()}"


@dataclass
class InfoTrava:
    dono: str
    desde: datetime
    atividade: datetime


class TravaEdicao:
    def __init__(self, caminho_banco: str | Path, validade_min: float = 15, dono: str | None = None):
        self.arquivo = Path(f"{caminho_banco}.lock")
        self.validade = timedelta(minutes=validade_min)
        self.dono = dono or identidade_local()

    # ---------------------------------------------------------------- consulta
    def ler(self) -> InfoTrava | None:
        try:
            d = json.loads(self.arquivo.read_text(encoding="utf-8"))
            return InfoTrava(d["dono"], datetime.fromisoformat(d["desde"]), datetime.fromisoformat(d["atividade"]))
        except (FileNotFoundError, ValueError, KeyError, OSError):
            return None

    def expirada(self, info: InfoTrava) -> bool:
        return datetime.now() - info.atividade > self.validade

    def minha(self) -> bool:
        info = self.ler()
        return info is not None and info.dono == self.dono and not self.expirada(info)

    # ---------------------------------------------------------------- operação
    def adquirir(self) -> bool:
        """Tenta obter (ou renovar) a trava. True = este computador pode gravar."""
        info = self.ler()
        if info and info.dono != self.dono and not self.expirada(info):
            return False
        desde = info.desde if info and info.dono == self.dono and not self.expirada(info) else datetime.now()
        self._gravar(desde)
        # confere se outra máquina não gravou ao mesmo tempo
        info = self.ler()
        return info is not None and info.dono == self.dono

    def liberar(self) -> None:
        if self.minha():
            try:
                self.arquivo.unlink()
            except FileNotFoundError:
                pass

    def forcar(self) -> None:
        """Toma a trava de outra pessoa (use só se tiver certeza de que ela saiu)."""
        try:
            self.arquivo.unlink()
        except FileNotFoundError:
            pass
        self.adquirir()

    def _gravar(self, desde: datetime) -> None:
        tmp = self.arquivo.with_name(f"{self.arquivo.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"dono": self.dono, "desde": desde.isoformat(timespec="seconds"),
                                   "atividade": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
        os.replace(tmp, self.arquivo)
