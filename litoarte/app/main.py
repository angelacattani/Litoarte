"""Inicialização da interface."""

from __future__ import annotations

import os

from nicegui import ui

from . import estado, paginas

PORTA_PADRAO = 8503


def iniciar(url: str | None = None, *, porta: int | None = None, abrir_navegador: bool = True) -> None:
    estado.configurar(url)          # aplica migrações pendentes antes de abrir
    paginas.registrar()
    ui.run(title="Litoarte", port=porta or int(os.environ.get("LITOARTE_PORTA", PORTA_PADRAO)),
           language="pt-BR", reload=False, show=abrir_navegador, favicon="💲",
           show_welcome_message=False, storage_secret=os.environ.get("LITOARTE_SEGREDO", "litoarte-local"))
