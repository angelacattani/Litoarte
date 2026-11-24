"""Formatação pt-BR para exibição."""

from __future__ import annotations


def _br(txt: str) -> str:
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def brl(v: float | None, casas: int = 2) -> str:
    return "—" if v is None else "R$ " + _br(f"{v:,.{casas}f}")


def pct(v: float | None, casas: int = 2) -> str:
    return "—" if v is None else _br(f"{v:,.{casas}f}") + " %"


def num(v, casas: int = 4, minimo: int = 0) -> str:
    """Número com até `casas` decimais, sem zeros à direita (mantém ao menos `minimo` casas)."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, (int, float)):
        s = _br(f"{v:,.{casas}f}")
        if "," in s:
            inteiro, dec = s.split(",")
            dec = dec.rstrip("0")
            dec = dec.ljust(minimo, "0")
            s = inteiro + ("," + dec if dec else "")
        return s
    return str(v)
