"""Exibição do relatório de impacto (reajuste manual ou por importação)."""

from __future__ import annotations

from datetime import date

from nicegui import ui

from ..domain.services.impacto import LinhaImpacto
from ..planilhas.relatorios import impacto_df, xlsx
from .formatos import brl, pct

SITUACAO = r'''
<q-td :props="props">
  <q-badge v-if="props.value" color="negative" :label="props.value"/>
</q-td>
'''


def tabela_impacto(linhas: list[LinhaImpacto]) -> None:
    rows = [{"sku": l.sku, "nome": l.nome, "antes": brl(l.preco_antes), "depois": brl(l.preco_depois),
             "var": pct(l.variacao_pct) if l.variacao_pct is not None else "—",
             "praticado": brl(l.praticado) if l.praticado else "—",
             "margem": (f"{pct(l.margem_antes)} → {pct(l.margem_depois)}" if l.margem_depois is not None else "—"),
             "situacao": "abaixo da desejada" if l.abaixo_da_margem else ""} for l in linhas]
    t = ui.table(rows=rows, row_key="sku", pagination={"rowsPerPage": 10}, columns=[
        {"name": "sku", "label": "SKU", "field": "sku", "align": "left", "sortable": True},
        {"name": "nome", "label": "Produto", "field": "nome", "align": "left"},
        {"name": "antes", "label": "Sugerido antes", "field": "antes", "align": "right"},
        {"name": "depois", "label": "Sugerido depois", "field": "depois", "align": "right"},
        {"name": "var", "label": "Variação", "field": "var", "align": "right"},
        {"name": "praticado", "label": "Preço praticado", "field": "praticado", "align": "right"},
        {"name": "margem", "label": "Margem real (antes → depois)", "field": "margem", "align": "right"},
        {"name": "situacao", "label": "", "field": "situacao", "align": "left"},
    ]).props("flat dense bordered").classes("w-full").mark("tabela-impacto")
    t.add_slot("body-cell-situacao", SITUACAO)
    abaixo = sum(1 for l in linhas if l.abaixo_da_margem)
    with ui.row().classes("w-full items-center"):
        if abaixo:
            ui.label(f"{abaixo} produto(s) passam a render menos que a margem desejada no preço praticado. "
                     "O preço praticado não é alterado automaticamente.").classes("text-negative text-caption")
        else:
            ui.label("O preço praticado não é alterado automaticamente.").classes("text-caption text-grey-7")
        ui.space()
        ui.button("Exportar impacto", icon="download", on_click=lambda: ui.download(
            xlsx({"Impacto": impacto_df(linhas)}), f"impacto_{date.today().isoformat()}.xlsx")).props("flat dense")


def mostrar_impacto(linhas: list[LinhaImpacto], titulo: str) -> None:
    with ui.dialog() as dlg, ui.card().classes("w-[1000px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label(titulo).classes("text-h6")
            ui.space()
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        ui.label(f"{len(linhas)} produto(s) tiveram o custo recalculado.").classes("text-body2")
        tabela_impacto(linhas)
        with ui.row().classes("w-full justify-end"):
            ui.button("OK", on_click=dlg.close)
    dlg.open()
