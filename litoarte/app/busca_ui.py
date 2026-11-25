"""Assistente de busca de preços de produtos similares na web."""

from __future__ import annotations

from typing import Callable

from nicegui import run, ui

from ..busca import ErroBusca, estatisticas, remover_extremos
from ..domain.services import concorrencia
from . import estado
from .formatos import brl

FONTES = {"mercadolivre": "Mercado Livre", "google_shopping": "Google Shopping"}


def abrir_busca(*, consulta: str = "", grupo_id: int | None = None, subgrupo_id: int | None = None,
                produto_id: int | None = None, grupos: dict[int, str] | None = None,
                subgrupos: dict[int, tuple[int, str]] | None = None, ao_gravar: Callable[[], None] | None = None):
    """grupos/subgrupos: opções de seleção quando a busca não parte de um produto."""
    st = {"resultados": [], "selecionados": set(), "extremos": True}

    with ui.dialog().props("persistent") as dlg, ui.card().classes("w-[1100px] max-w-full"):
        with ui.row().classes("w-full items-center"):
            ui.label("Buscar preços de produtos similares na web").classes("text-h6")
            ui.space()
            ui.button(icon="close", on_click=dlg.close).props("flat round dense")
        ui.label("Os resultados são só para consulta: nada é gravado até você marcar os itens e confirmar.") \
            .classes("text-caption text-grey-7")
        with ui.row().classes("w-full items-center gap-3"):
            entrada = ui.input("O que buscar", value=consulta).props("outlined dense clearable") \
                .classes("grow min-w-64").mark("busca-consulta")
            fonte = ui.toggle(FONTES, value="mercadolivre").props("dense no-caps").mark("busca-fonte")
            botao_buscar = ui.button("Buscar", icon="search", on_click=lambda: _buscar()).mark("busca-executar")
        if grupos is not None:
            with ui.row().classes("w-full gap-3"):
                sel_grupo = ui.select(grupos, label="Grupo dos preços *", value=grupo_id,
                                      on_change=lambda e: _opcoes_sub(e.value)).props("outlined dense").classes("w-72")
                sel_sub = ui.select({}, label="Subgrupo (opcional)", clearable=True).props("outlined dense") \
                    .classes("w-72")
        area = ui.column().classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Fechar", on_click=dlg.close).props("flat")
            gravar = ui.button("Gravar selecionados", icon="save", on_click=lambda: _gravar()).mark("busca-gravar")
            gravar.disable()

    def _opcoes_sub(gid):
        if grupos is None:
            return
        sel_sub.options = {sid: nome for sid, (g, nome) in (subgrupos or {}).items() if g == gid}
        sel_sub.value = None
        sel_sub.update()
    if grupos is not None:
        _opcoes_sub(grupo_id)

    async def _buscar():
        consulta_txt = (entrada.value or "").strip()
        if not consulta_txt:
            ui.notify("Informe o que buscar.", type="warning")
            return
        with estado.sessao() as s:
            cred = concorrencia.credenciais(s)
        botao_buscar.props("loading")
        try:
            resultados, novo = await run.io_bound(concorrencia.buscar_web, cred, fonte.value, consulta_txt)
        except ErroBusca as e:
            area.clear()
            with area:
                ui.label(f"Não foi possível buscar: {e}").classes("text-negative")
                ui.link("Configurar credenciais de busca", "/configuracao")
            return
        finally:
            botao_buscar.props(remove="loading")
        if novo:
            with estado.sessao() as s:
                concorrencia.guardar_token(s, *novo)
        st["resultados"], st["selecionados"] = resultados, set()
        _mostrar()

    def _mostrar():
        area.clear()
        visiveis = remover_extremos(st["resultados"]) if st["extremos"] else list(st["resultados"])
        with area:
            if not st["resultados"]:
                ui.label("Nenhum resultado.").classes("text-grey-7")
                return
            e = estatisticas([r.preco for r in visiveis])
            with ui.row().classes("items-center gap-2"):
                ui.badge(f"{e['n']} resultado(s)", color="primary").classes("q-pa-sm")
                ui.label(f"mínimo {brl(e['minimo'])} · mediana {brl(e['mediana'])} · média {brl(e['media'])} · "
                         f"máximo {brl(e['maximo'])}").classes("text-body2").mark("busca-estatisticas")
                ui.space()
                ui.checkbox("ocultar preços extremos", value=st["extremos"],
                            on_change=lambda ev: (st.update(extremos=ev.value), _mostrar()))
            rows = [{"i": i, "titulo": r.titulo, "loja": r.loja, "preco": brl(r.preco), "url": r.url or "",
                     "condicao": r.condicao or ""} for i, r in enumerate(st["resultados"]) if r in visiveis]
            tab = ui.table(rows=rows, row_key="i", selection="multiple", pagination={"rowsPerPage": 10}, columns=[
                {"name": "titulo", "label": "Produto similar", "field": "titulo", "align": "left"},
                {"name": "loja", "label": "Loja / vendedor", "field": "loja", "align": "left", "sortable": True},
                {"name": "preco", "label": "Preço", "field": "preco", "align": "right"},
                {"name": "condicao", "label": "", "field": "condicao", "align": "left"},
                {"name": "url", "label": "", "field": "url", "align": "left"},
            ], on_select=lambda ev: _selecao(ev.selection)).props("flat dense bordered").classes("w-full") \
                .mark("busca-resultados")
            tab.add_slot("body-cell-titulo", r'''<q-td :props="props" style="white-space: normal; max-width: 460px">
                {{ props.value }}</q-td>''')
            tab.add_slot("body-cell-url", r'''<q-td :props="props"><a v-if="props.value" :href="props.value"
                target="_blank" rel="noopener">abrir</a></q-td>''')

    def _selecao(sel):
        st["selecionados"] = {r["i"] for r in sel}
        gravar.set_enabled(bool(st["selecionados"]))
        gravar.text = f"Gravar {len(st['selecionados'])} selecionado(s)" if st["selecionados"] else "Gravar selecionados"

    def _gravar():
        gid = sel_grupo.value if grupos is not None else grupo_id
        sid = sel_sub.value if grupos is not None else subgrupo_id
        if not gid:
            ui.notify("Escolha o grupo dos preços.", type="warning")
            return
        escolhidos = [st["resultados"][i] for i in sorted(st["selecionados"])]
        with estado.sessao() as s:
            n = concorrencia.registrar_resultados(s, escolhidos, grupo_id=gid, subgrupo_id=sid, produto_id=produto_id)
        ui.notify(f"{n} preço(s) de concorrentes gravado(s).", type="positive")
        dlg.close()
        if ao_gravar:
            ao_gravar()

    dlg.open()
