"""Campo numérico no formato brasileiro.

O <input type=number> do navegador descarta a vírgula: em pt-BR, "139,90" virava 13990. Este campo
é texto e interpreta 139,90 · 1.234,56 · 139.90; valores inválidos ficam destacados em vermelho.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from ..domain.services import valores as V
from .formatos import num


def ler(v) -> float | None:
    """Converte o valor do campo (texto BR ou número) em float; inválido -> None."""
    try:
        return V.numero(v)
    except V.ValorInvalido:
        return None


def campo_numero(rotulo: str, valor: float | None = None, on_change: Callable[[float | None], None] | None = None,
                 *, casas: int = 6, limpar: bool = True) -> ui.input:
    el = ui.input(rotulo, value=num(valor, casas) if valor is not None else "") \
        .props("inputmode=decimal outlined dense" + (" clearable" if limpar else ""))

    def mudou(e):
        txt = e.value
        try:
            n = V.numero(txt)
            el.props(remove="error error-message")
        except V.ValorInvalido:
            el.props('error error-message="número inválido"')
            return
        if on_change:
            return on_change(n)
    el.on_value_change(mudou)
    return el
