"""Lista de produtos: filtros, situação da margem, ações (abrir, duplicar, excluir) e planilhas."""

from __future__ import annotations

from datetime import date

from nicegui import ui

from ..domain.services import composicao as C
from ..domain.services.cadastros import MODULOS
from ..planilhas import relatorios as R
from ..planilhas.modelos import exportar, gerar_modelo
from . import estado
from .composicao_ui import abrir_clonagem
from .formatos import brl, pct
from .importacao_ui import abrir_importacao

ACOES = r'''
<q-td :props="props" auto-width>
  <q-btn flat dense round size="sm" icon="calculate" color="primary"
         @click.stop="() => $parent.$emit('abrir', props.row)"><q-tooltip>Composição</q-tooltip></q-btn>
  <q-btn flat dense round size="sm" icon="content_copy" color="secondary"
         @click.stop="() => $parent.$emit('duplicar', props.row)"><q-tooltip>Duplicar</q-tooltip></q-btn>
  <q-btn flat dense round size="sm" icon="delete" color="negative"
         @click.stop="() => $parent.$emit('excluir', props.row)"><q-tooltip>Excluir</q-tooltip></q-btn>
</q-td>
'''
SITUACAO = r'''
<q-td :props="props">
  <q-badge v-if="props.row.situacao === 'abaixo'" color="negative" label="margem abaixo"/>
  <q-badge v-else-if="props.row.situacao === 'alerta'" color="warning" label="verificar">
    <q-tooltip>{{ props.row.alertas }}</q-tooltip></q-badge>
  <q-badge v-else-if="props.row.situacao === 'ok'" color="positive" label="ok"/>
  <span v-else class="text-grey-6">sem preço praticado</span>
</q-td>
'''


class TelaProdutos:
    def __init__(self):
        self.filtro = {"busca": "", "grupo": None, "subgrupo": None, "inativos": False, "abaixo": False}
        self.linhas: list[C.ResumoProduto] = []

    def render(self):
        with ui.row().classes("w-full items-center gap-2"):
            ui.input(placeholder="Buscar SKU ou nome...", on_change=lambda e: self._f("busca", e.value or "")) \
                .props("dense outlined clearable debounce=250").classes("w-64")
            self.sel_grupo = ui.select({}, label="Grupo", clearable=True, on_change=lambda e: self._grupo(e.value)) \
                .props("dense outlined").classes("w-48")
            self.sel_sub = ui.select({}, label="Subgrupo", clearable=True,
                                     on_change=lambda e: self._f("subgrupo", e.value)).props("dense outlined") \
                .classes("w-48")
            ui.switch("inativos", on_change=lambda e: self._f("inativos", e.value)).props("dense")
            ui.switch("só margem abaixo", on_change=lambda e: self._f("abaixo", e.value)).props("dense")
            ui.space()
            ui.button("Novo produto", icon="add", on_click=lambda: ui.navigate.to("/produtos/novo")).mark("novo-produto")
            with ui.button("Planilhas", icon="table_view").props("outline").mark("menu-planilhas"):
                with ui.menu():
                    ui.menu_item("Exportar tabela de preços", self._exportar_precos).mark("exportar-precos")
                    ui.menu_item("Exportar composição detalhada", self._exportar_composicao)
                    ui.separator()
                    for chave, rotulo in (("produtos", "produtos"), ("ficha_materiais", "ficha — materiais"),
                                          ("ficha_mao_de_obra", "ficha — mão de obra")):
                        ui.menu_item(f"Importar {rotulo}", lambda c=chave: abrir_importacao(c, ao_concluir=self.atualizar))
                        ui.menu_item(f"Modelo {rotulo}", lambda c=chave: ui.download(
                            gerar_modelo(MODULOS[c]), f"modelo_{c}.xlsx"))
                        ui.menu_item(f"Exportar {rotulo}", lambda c=chave: self._exportar(c))
                        ui.separator()
        colunas = [
            {"name": "acoes", "label": "", "field": "id"},
            {"name": "sku", "label": "SKU", "field": "sku", "align": "left", "sortable": True},
            {"name": "nome", "label": "Nome", "field": "nome", "align": "left", "sortable": True},
            {"name": "subgrupo", "label": "Grupo › Subgrupo", "field": "classe", "align": "left", "sortable": True},
            {"name": "cd", "label": "Custo direto", "field": "cd", "align": "right"},
            {"name": "sugerido", "label": "Preço sugerido", "field": "sugerido", "align": "right"},
            {"name": "praticado", "label": "Preço praticado", "field": "praticado", "align": "right"},
            {"name": "margem", "label": "Margem real", "field": "margem", "align": "right"},
            {"name": "situacao", "label": "Situação", "field": "situacao", "align": "left"},
        ]
        self.tabela = ui.table(rows=[], columns=colunas, row_key="id", pagination={"rowsPerPage": 25}) \
            .props("flat dense bordered").classes("w-full").mark("tabela-produtos")
        self.tabela.add_slot("body-cell-acoes", ACOES)
        self.tabela.add_slot("body-cell-situacao", SITUACAO)
        self.tabela.on("abrir", lambda e: ui.navigate.to(f"/produtos/{e.args['id']}"))
        self.tabela.on("duplicar", lambda e: abrir_clonagem(e.args["id"]))
        self.tabela.on("excluir", lambda e: self._excluir(e.args))
        self.tabela.on("rowClick", lambda e: ui.navigate.to(f"/produtos/{e.args[1]['id']}"))
        self.atualizar()

    def atualizar(self):
        with estado.sessao() as s:
            self.linhas = C.resumo_produtos(s)
        grupos = sorted({l.grupo for l in self.linhas})
        self.sel_grupo.options = {g: g for g in grupos}
        self.sel_grupo.update()
        self._aplicar()

    def _grupo(self, g):
        self.filtro["grupo"], self.filtro["subgrupo"] = g, None
        self.sel_sub.options = {s: s for s in sorted({l.subgrupo for l in self.linhas if l.grupo == g})}
        self.sel_sub.value = None
        self.sel_sub.update()
        self._aplicar()

    def _f(self, chave, valor):
        self.filtro[chave] = valor
        self._aplicar()

    def _aplicar(self):
        f, termo = self.filtro, self.filtro["busca"].lower()
        rows = []
        for l in self.linhas:
            if not f["inativos"] and not l.ativo:
                continue
            if f["grupo"] and l.grupo != f["grupo"] or f["subgrupo"] and l.subgrupo != f["subgrupo"]:
                continue
            if f["abaixo"] and not l.abaixo_da_margem:
                continue
            if termo and termo not in l.sku.lower() and termo not in l.nome.lower():
                continue
            situacao = "abaixo" if l.abaixo_da_margem else "alerta" if l.alertas else \
                "ok" if l.preco_praticado else "sem"
            rows.append({"id": l.id, "sku": l.sku, "nome": l.nome + ("" if l.ativo else " (inativo)"),
                         "classe": f"{l.grupo} › {l.subgrupo}", "cd": brl(l.cd), "sugerido": brl(l.preco_sugerido),
                         "praticado": brl(l.preco_praticado) if l.preco_praticado else "—",
                         "margem": pct(l.margem_praticada) if l.margem_praticada is not None else "—",
                         "situacao": situacao, "alertas": "; ".join(l.alertas)})
        self.tabela.rows = rows
        self.tabela.update()

    def _excluir(self, linha):
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Excluir {linha['sku']} e sua ficha técnica?").classes("text-subtitle1")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancelar", on_click=dlg.close).props("flat")

                def ok():
                    with estado.sessao() as s:
                        C.excluir(s, linha["id"])
                    dlg.close()
                    ui.notify("Produto excluído.", type="positive")
                    self.atualizar()
                ui.button("Excluir", color="negative", on_click=ok)
        dlg.open()

    def _exportar_precos(self):
        with estado.sessao() as s:
            conteudo = R.xlsx({"Tabela de preços": R.tabela_precos(s, apenas_ativos=not self.filtro["inativos"])})
        ui.download(conteudo, f"tabela_precos_{date.today().isoformat()}.xlsx")

    def _exportar_composicao(self):
        with estado.sessao() as s:
            conteudo = R.xlsx({"Composição": R.composicao_detalhada(s, apenas_ativos=not self.filtro["inativos"])})
        ui.download(conteudo, f"composicao_detalhada_{date.today().isoformat()}.xlsx")

    def _exportar(self, chave):
        with estado.sessao() as s:
            conteudo = exportar(s, MODULOS[chave])
        ui.download(conteudo, f"{chave}_{date.today().isoformat()}.xlsx")
