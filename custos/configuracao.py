"""Configuração local da máquina: onde fica o banco de dados.

Cada computador guarda em `config_local.json` (não versionado, ao lado do
app) o caminho do arquivo do banco. Assim, várias máquinas podem apontar
para o mesmo `custos.db` numa pasta compartilhada, por exemplo:

    \\\\SERVIDOR\\Compartilhado\\Litoarte\\custos.db   (caminho de rede)
    Z:\\Litoarte\\custos.db                         (unidade mapeada)

Prioridade: variável de ambiente CUSTOS_DB > config_local.json > pasta do app.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

PASTA_APP = Path(__file__).resolve().parent.parent
ARQ_CONFIG = PASTA_APP / "config_local.json"
BANCO_PADRAO = PASTA_APP / "custos.db"

# Pastas sincronizadas por serviços de nuvem: o SQLite funciona, mas a
# sincronização pode gerar cópias em conflito se duas pessoas editarem.
_NUVEM = ("onedrive", "dropbox", "google drive", "googledrive", "meu drive", "icloud")


def ler_config() -> dict:
    try:
        return json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar_config(**valores) -> None:
    cfg = ler_config()
    cfg.update(valores)
    ARQ_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def caminho_banco() -> Path:
    if os.environ.get("CUSTOS_DB"):
        return Path(os.environ["CUSTOS_DB"])
    if ler_config().get("banco"):
        return Path(ler_config()["banco"])
    return BANCO_PADRAO


def normalizar_caminho(texto: str) -> Path:
    """Aceita pasta ou arquivo; se for pasta, usa <pasta>/custos.db."""
    p = Path(texto.strip().strip('"'))
    if p.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        p = p / "custos.db"
    return p


def checar_pasta(caminho: Path) -> str | None:
    """Retorna mensagem de erro se a pasta não existir ou não aceitar escrita."""
    pasta = caminho.parent
    if not pasta.exists():
        return f"A pasta {pasta} não existe ou não está acessível (rede desconectada?)."
    teste = pasta / f".teste_escrita_{uuid.uuid4().hex}"
    try:
        teste.write_text("ok")
        teste.unlink()
    except OSError as e:
        return f"Sem permissão de escrita em {pasta}: {e}"
    return None


def em_pasta_de_nuvem(caminho: Path) -> bool:
    return any(n in str(caminho).lower() for n in _NUVEM)
