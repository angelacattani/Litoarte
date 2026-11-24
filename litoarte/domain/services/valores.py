"""Conversão e normalização de valores digitados ou importados (formato brasileiro)."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

_NUM_BR = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$|^-?\d+,\d+$")   # 1.234,56 | 12,5


class ValorInvalido(ValueError):
    """Valor que não pode ser convertido; a mensagem é exibida ao usuário."""


def vazio(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return isinstance(v, str) and v.strip() in ("", "-", "nan", "None", "NaN")


def numero(v: Any) -> float | None:
    """'1.234,56', 'R$ 12,90', '18%', 12.5, '3.5' -> float. Vazio -> None."""
    if vazio(v):
        return None
    if isinstance(v, bool):
        raise ValorInvalido(f"número inválido: {v!r}")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace("%", "").replace("\xa0", "").replace(" ", "")
    if _NUM_BR.match(s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        raise ValorInvalido(f"número inválido: {v!r}") from None


_VERDADEIRO = {"sim", "s", "true", "verdadeiro", "1", "x", "ativo", "yes", "y"}
_FALSO = {"nao", "n", "false", "falso", "0", "inativo", "no"}


def booleano(v: Any) -> bool | None:
    if vazio(v):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = chave(v)
    if s in _VERDADEIRO:
        return True
    if s in _FALSO:
        return False
    raise ValorInvalido(f"use sim/não: {v!r}")


def texto(v: Any) -> str | None:
    if vazio(v):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)                       # código 1001 lido do Excel como 1001.0
    s = " ".join(str(v).split())
    return s or None


def chave(v: Any) -> str:
    """Forma canônica para comparação: sem acentos, minúsculas, '_' no lugar de separadores."""
    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().lower().strip()
    return "_".join(p for p in re.split(r"[^a-z0-9%$²]+", s) if p)


def opcao(v: Any, opcoes: tuple[str, ...], aliases: dict[str, str] | None = None) -> str | None:
    if vazio(v):
        return None
    k = chave(v)
    for o in opcoes:
        if chave(o) == k:
            return o
    if aliases and k in aliases:
        return aliases[k]
    raise ValorInvalido(f"valor '{v}' inválido (use: {', '.join(opcoes)})")
