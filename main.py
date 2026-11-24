"""Arquivo principal para os testes de interface (nicegui.testing) e execução direta."""

from litoarte.app.main import iniciar

if __name__ in {"__main__", "__mp_main__"}:
    iniciar()
