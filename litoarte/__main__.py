"""python -m litoarte  -> abre o sistema no navegador (http://localhost:8503)."""

from .app.main import iniciar

if __name__ in {"__main__", "__mp_main__"}:
    iniciar()
