"""Moldura comum das páginas: cabeçalho e menu lateral."""

from __future__ import annotations

from contextlib import contextmanager

from nicegui import ui

from .. import __version__
from . import estado

MENU = [
    ("Início", "/", "home"),
    ("Produtos e composição", "/produtos", "calculate"),
    None,
    ("Matérias-primas", "/materias-primas", "inventory_2"),
    ("Mão de obra", "/mao-de-obra", "engineering"),
    ("Custos fixos", "/custos-fixos", "account_balance"),
    ("Custos variáveis", "/custos-variaveis", "percent"),
    ("Grupos e subgrupos", "/grupos", "account_tree"),
    None,
    ("Unidades de medida", "/unidades", "straighten"),
    ("Fornecedores", "/fornecedores", "local_shipping"),
    ("Configuração", "/configuracao", "tune"),
    ("Histórico de custos", "/historico", "history"),
]

CORES = {"primary": "#1f4e79", "secondary": "#5b7083", "accent": "#c27c0e", "positive": "#2e7d32",
         "negative": "#c62828", "warning": "#b26a00"}


@contextmanager
def moldura(titulo: str, rota: str):
    ui.colors(**CORES)
    ui.query("body").style("background:#f5f7fa")
    with ui.header(elevated=True).classes("items-center bg-primary text-white q-px-md"):
        ui.button(icon="menu", on_click=lambda: menu.toggle()).props("flat round color=white")
        ui.label("Litoarte").classes("text-h6 text-weight-bold")
        ui.label("Composição de custos e preço de venda").classes("text-caption gt-xs opacity-80")
        ui.space()
        banco = "PostgreSQL" if (estado.URL or "").startswith("postgresql") else "SQLite"
        ui.label(f"v{__version__} · {banco}").classes("text-caption opacity-70")
    with ui.left_drawer(value=True, bordered=True).classes("bg-white q-pa-none") as menu:
        with ui.list().props("dense padding").classes("w-full"):
            for item in MENU:
                if item is None:
                    ui.separator().classes("q-my-sm")
                    continue
                nome, destino, icone = item
                ativo = destino == rota or (destino != "/" and rota.startswith(destino + "/"))
                with ui.item(on_click=lambda d=destino: ui.navigate.to(d)).props(
                        f'clickable {"active" if ativo else ""} active-class="bg-blue-1 text-primary"'):
                    with ui.item_section().props("avatar"):
                        ui.icon(icone)
                    ui.item_section(nome)
    with ui.column().classes("w-full q-pa-md gap-4 max-w-screen-xl mx-auto"):
        ui.label(titulo).classes("text-h5 text-weight-medium text-grey-9")
        yield
