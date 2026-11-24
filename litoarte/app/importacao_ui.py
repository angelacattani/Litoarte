"""Assistente de importação: modo -> upload -> pré-visualização validada -> confirmação -> resultado."""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from ..domain.services.cadastros import MODULOS, ErroValidacao
from ..planilhas.importacao import aplicar, analisar
from ..planilhas.modelos import gerar_modelo
from . import estado
from .formatos import brl, num

ROTULO_MODO = {"ambos": "Incluir novos e atualizar existentes", "inserir": "Só incluir novos",
               "atualizar": "Só atualizar existentes (ex.: reajuste de preços)"}
COR_ACAO = {"inserir": "positive", "atualizar": "primary", "ignorar": "grey", "erro": "negative"}


def abrir_importacao(chave: str, ao_concluir: Callable[[], None] | None = None) -> None:
    modulo = MODULOS[chave]
    st = {"conteudo": None, "arquivo": None, "analise": None, "so_problemas": False}

    with ui.dialog().props("persistent") as dlg, ui.card().classes("w-[1100px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label(f"Importar — {modulo.titulo}").classes("text-h6")
            ui.space()
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        ui.label("A chave de atualização é " + " + ".join(modulo.chave_negocio)
                 + ". Células vazias não apagam valores já cadastrados. Nada é gravado antes da confirmação.") \
            .classes("text-caption text-grey-8")
        with ui.row().classes("w-full items-start gap-6"):
            modo = ui.radio(ROTULO_MODO, value="ambos", on_change=lambda: _reanalisar()).props("dense")
            with ui.column().classes("gap-1"):
                ui.upload(label="Arquivo .xlsx ou .csv", auto_upload=True, on_upload=lambda e: _recebido(e)) \
                    .props('accept=".xlsx,.csv,.txt" flat bordered').classes("w-80").mark("upload")
                ui.button("Baixar modelo", icon="description",
                          on_click=lambda: ui.download(gerar_modelo(modulo), f"modelo_{chave}.xlsx")).props("flat dense")
        area = ui.column().classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Fechar", on_click=dlg.close).props("flat")
            botao = ui.button("Importar", icon="check", on_click=lambda: _confirmar()).mark("confirmar-importacao")
            botao.disable()

    async def _recebido(e):
        st["conteudo"] = await e.file.read()
        st["arquivo"] = e.file.name
        _reanalisar()

    def _reanalisar():
        if st["conteudo"] is None:
            return
        with estado.sessao() as s:
            st["analise"] = analisar(s, chave, st["conteudo"], st["arquivo"], modo.value)
        _mostrar()

    def _mostrar():
        a = st["analise"]
        area.clear()
        with area:
            if a.erros_arquivo:
                with ui.card().classes("w-full bg-red-1"):
                    for msg in a.erros_arquivo:
                        ui.label("⚠ " + msg).classes("text-negative")
            c = a.contagem()
            with ui.row().classes("items-center gap-2"):
                ui.label(a.arquivo).classes("text-weight-medium")
                for acao, rot in (("inserir", "incluir"), ("atualizar", "atualizar"), ("ignorar", "ignorar"),
                                  ("erro", "com erro")):
                    ui.badge(f"{c[acao]} {rot}", color=COR_ACAO[acao]).classes("text-body2 q-pa-sm")
                ui.space()
                ui.checkbox("mostrar só erros e ignoradas", value=st["so_problemas"],
                            on_change=lambda e: (st.update(so_problemas=e.value), _mostrar()))
            if a.colunas_ignoradas:
                ui.label("Colunas não reconhecidas (ignoradas): " + ", ".join(a.colunas_ignoradas)) \
                    .classes("text-caption text-warning")
            linhas = [l for l in a.linhas if not st["so_problemas"] or l.acao in ("erro", "ignorar")]
            rows = [{"linha": l.linha, "chave": l.chave, "acao": l.acao,
                     "mensagens": "; ".join(f"{cmp}: {msg}" if cmp else msg for cmp, msg in l.erros) or l.motivo}
                    for l in linhas]
            tab = ui.table(rows=rows, row_key="linha", pagination={"rowsPerPage": 15}, columns=[
                {"name": "linha", "label": "Linha", "field": "linha", "align": "right", "sortable": True},
                {"name": "chave", "label": "Chave", "field": "chave", "align": "left", "sortable": True},
                {"name": "acao", "label": "Ação", "field": "acao", "align": "left", "sortable": True},
                {"name": "mensagens", "label": "Erros / observações", "field": "mensagens", "align": "left"},
            ]).props("flat dense bordered").classes("w-full").mark("previa")
            tab.add_slot("body-cell-acao", r'''
                <q-td :props="props"><q-badge :color="{inserir:'positive',atualizar:'primary',ignorar:'grey',
                    erro:'negative'}[props.value]" :label="props.value"/></q-td>''')
            tab.add_slot("body-cell-mensagens", r'''
                <q-td :props="props" :class="props.row.acao === 'erro' ? 'text-negative' : 'text-grey-8'"
                      style="white-space: normal">{{ props.value }}</q-td>''')
        botao.set_enabled(a.pode_gravar)
        botao.text = f"Importar {c['inserir'] + c['atualizar']} registro(s)" if a.pode_gravar else "Importar"

    def _confirmar():
        a = st["analise"]
        try:
            with estado.sessao() as s:
                r = aplicar(s, a)
        except ErroValidacao as e:
            ui.notify(f"Importação cancelada, nada foi gravado: {e}", type="negative", multi_line=True, timeout=0,
                      close_button="OK")
            _reanalisar()
            return
        area.clear()
        botao.disable()
        botao.text = "Importar"
        st["conteudo"] = None
        with area:
            with ui.card().classes("w-full bg-green-1"):
                ui.label(f"Importação concluída: {r.inseridas} incluído(s), {r.atualizadas} atualizado(s), "
                         f"{r.ignoradas} ignorado(s).").classes("text-positive text-weight-medium")
            if r.reajustes:
                ui.label(f"Custos reajustados ({len(r.reajustes)}):").classes("text-weight-medium")
                ui.table(rows=[{"chave": k, "antes": brl(a_, 4) if a_ is not None else "—", "depois": brl(d, 4),
                                "var": (num(100 * (d / a_ - 1), 2) + " %") if a_ else "—"}
                               for k, a_, d in r.reajustes],
                         columns=[{"name": n, "label": l, "field": n, "align": al} for n, l, al in
                                  (("chave", "Item", "left"), ("antes", "Antes", "right"),
                                   ("depois", "Depois", "right"), ("var", "Variação", "right"))]) \
                    .props("flat dense bordered")
            if r.produtos_afetados:
                ui.label(f"{len(r.produtos_afetados)} produto(s) com custo recalculado: "
                         + ", ".join(r.produtos_afetados[:30]) + (" ..." if len(r.produtos_afetados) > 30 else "")) \
                    .classes("text-caption")
        ui.notify("Importação concluída.", type="positive")
        if ao_concluir:
            ao_concluir()

    dlg.open()
