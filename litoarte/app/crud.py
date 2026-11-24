"""Tela genérica de cadastro: lista + busca + formulário + importação/exportação.

Tudo é derivado da definição do módulo (domain/services/cadastros.py): colunas, controles do
formulário, obrigatoriedade, opções e validação. A gravação usa o mesmo serviço da importação.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from nicegui import ui
from sqlalchemy import select

from ..domain.services import cadastros as C
from ..planilhas.modelos import exportar, gerar_modelo
from . import estado
from .campos import campo_numero, ler
from .formatos import num
from .importacao_ui import abrir_importacao

ACOES = r'''
<q-td :props="props" auto-width class="q-gutter-x-none">
  <q-btn flat dense round size="sm" icon="edit" color="primary"
         @click="() => $parent.$emit('editar', props.row)"><q-tooltip>Editar</q-tooltip></q-btn>
  <q-btn v-if="props.row.ativo !== undefined" flat dense round size="sm" color="secondary"
         :icon="props.row.ativo === 'não' ? 'toggle_off' : 'toggle_on'"
         @click="() => $parent.$emit('ativo', props.row)">
    <q-tooltip>{{ props.row.ativo === 'não' ? 'Ativar' : 'Inativar' }}</q-tooltip></q-btn>
  <q-btn flat dense round size="sm" icon="delete" color="negative"
         @click="() => $parent.$emit('excluir', props.row)"><q-tooltip>Excluir</q-tooltip></q-btn>
</q-td>
'''


def _escapar(txt: str) -> str:
    return txt.replace('"', "'")


class TelaCadastro:
    def __init__(self, chave: str, *, ao_mudar: Callable[[], None] | None = None, descricao: str = ""):
        self.modulo = C.MODULOS[chave]
        self.ao_mudar = ao_mudar
        self.descricao = descricao
        self.busca = ""
        self.inativos = False
        self._brutas: list[dict] = []

    # ------------------------------------------------------------------ lista
    def render(self) -> "TelaCadastro":
        m = self.modulo
        with ui.card().classes("w-full"):
            if self.descricao:
                ui.label(self.descricao).classes("text-body2 text-grey-8")
            with ui.row().classes("w-full items-center gap-2"):
                ui.input(placeholder="Buscar...", on_change=lambda e: self._filtrar(e.value)) \
                    .props("dense outlined clearable debounce=250").classes("w-64").mark(f"busca-{m.chave}")
                if m.tem_ativo:
                    ui.switch("mostrar inativos", on_change=lambda e: self._mostrar_inativos(e.value)).props("dense")
                ui.space()
                ui.button("Novo", icon="add", on_click=lambda: self.abrir_form()).mark(f"novo-{m.chave}")
                ui.button("Importar", icon="upload", on_click=self._importar).props("outline")
                ui.button("Modelo", icon="description", on_click=self._baixar_modelo).props("flat")
                ui.button("Exportar", icon="download", on_click=self._exportar).props("flat")
            colunas = [{"name": "acoes", "label": "", "field": "id", "align": "left"}]   # ações sempre visíveis
            colunas += [{"name": c.nome, "label": c.rotulo, "field": c.nome, "sortable": True,
                         "align": "right" if c.tipo == "numero" else "left",
                         "headerStyle": "white-space: normal; min-width: 70px"}
                        for c in m.campos if c.na_lista]
            self.tabela = ui.table(rows=[], columns=colunas, row_key="id", pagination={"rowsPerPage": 25}) \
                .props("flat dense bordered").classes("w-full").mark(f"tabela-{m.chave}")
            self.tabela.add_slot("body-cell-acoes", ACOES)
            self.tabela.on("editar", lambda e: self.abrir_form(e.args))
            self.tabela.on("ativo", lambda e: self._alternar_ativo(e.args))
            self.tabela.on("excluir", lambda e: self._confirmar_exclusao(e.args))
        self.atualizar()
        return self

    def atualizar(self) -> None:
        with estado.sessao() as s:
            self._brutas = C.listar(s, self.modulo)
        self._aplicar_filtro()

    def _linha_tela(self, r: dict) -> dict:
        moeda = {c.nome for c in self.modulo.campos if "R$" in c.rotulo}
        def fmt(k, v):
            if isinstance(v, str):
                return v
            if k in moeda and isinstance(v, (int, float)):
                return num(v, 4, minimo=2)
            return num(v)
        return {k: fmt(k, v) for k, v in r.items() if k != "id"} | {"id": r["id"]}

    def _aplicar_filtro(self) -> None:
        termo = (self.busca or "").lower()
        linhas = []
        for r in self._brutas:
            if self.modulo.tem_ativo and not self.inativos and r.get("ativo") is False:
                continue
            if termo and not any(termo in str(v).lower() for k, v in r.items() if k != "id"):
                continue
            linhas.append(self._linha_tela(r))
        self.tabela.rows = linhas
        self.tabela.update()

    def _filtrar(self, termo) -> None:
        self.busca = termo or ""
        self._aplicar_filtro()

    def _mostrar_inativos(self, v: bool) -> None:
        self.inativos = v
        self._aplicar_filtro()

    def _mudou(self) -> None:
        self.atualizar()
        if self.ao_mudar:
            self.ao_mudar()

    # ------------------------------------------------------------------ formulário
    def abrir_form(self, linha: dict | None = None) -> None:
        m = self.modulo
        bruta = next((r for r in self._brutas if linha and r["id"] == linha["id"]), None)
        edicao = bruta is not None
        controles: dict[str, ui.element] = {}
        with ui.dialog() as dlg, ui.card().classes("w-[760px] max-w-full"):
            ui.label(("Editar — " if edicao else "Novo — ") + m.titulo).classes("text-h6")
            with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1"):
                for c in m.campos:
                    controles[c.nome] = self._controle(c, bruta.get(c.nome) if bruta else None, edicao)
            self._ligar_custo_minuto(controles)
            with ui.row().classes("w-full justify-end q-mt-md"):
                ui.button("Cancelar", on_click=dlg.close).props("flat")
                ui.button("Salvar", icon="save",
                          on_click=lambda: self._salvar(dlg, controles, bruta["id"] if edicao else None)) \
                    .mark("salvar-form")
        dlg.open()

    def _controle(self, c: C.Campo, valor, edicao: bool):
        rotulo = c.rotulo + (" *" if c.obrigatorio or c.nome in self.modulo.chave_negocio else "")
        if c.tipo == "bool":
            el = ui.switch(rotulo, value=True if valor is None and not edicao else bool(valor))
        elif c.tipo == "numero":
            el = campo_numero(rotulo, valor)
        elif c.tipo == "opcao":
            el = ui.select(list(c.opcoes), label=rotulo, value=valor).props("outlined dense clearable")
        elif c.tipo == "ref":
            opcoes = self._opcoes_ref(c)
            if valor is not None and valor not in opcoes:
                opcoes.append(valor)
            el = ui.select(opcoes, label=rotulo, value=valor, with_input=True,
                           new_value_mode="add-unique" if c.cria_ref else None).props("outlined dense clearable")
        else:
            el = ui.input(rotulo, value="" if valor is None else str(valor)).props("outlined dense clearable")
        if c.ajuda:
            el.props(f'hint="{_escapar(c.ajuda)}"')
        return el.mark(f"campo-{c.nome}")

    @staticmethod
    def _opcoes_ref(c: C.Campo) -> list[str]:
        modelo, coluna = c.ref
        with estado.sessao() as s:
            q = select(getattr(modelo, coluna))
            if hasattr(modelo, "ativo"):
                q = q.where(modelo.ativo)
            return sorted(str(v) for v in s.scalars(q))

    @staticmethod
    def _ligar_custo_minuto(ctl: dict) -> None:
        """Mão de obra: custo por hora e por minuto ficam sincronizados (grava-se o custo/hora)."""
        if "custo_hora" not in ctl or "custo_minuto" not in ctl:
            return
        h, m = ctl["custo_hora"], ctl["custo_minuto"]
        if ler(h.value) is not None:
            m.value = num(ler(h.value) / 60, 6)
        trava = {"ativa": False}

        def de_hora(e):
            if not trava["ativa"]:
                trava["ativa"] = True
                v = ler(e.value)
                m.value = "" if v is None else num(v / 60, 6)
                trava["ativa"] = False

        def de_minuto(e):
            if not trava["ativa"]:
                trava["ativa"] = True
                v = ler(e.value)
                h.value = "" if v is None else num(v * 60, 4)
                trava["ativa"] = False

        h.on_value_change(de_hora)
        m.on_value_change(de_minuto)

    def _salvar(self, dlg, controles: dict, id_edicao: int | None) -> None:
        bruto = {nome: el.value for nome, el in controles.items()}
        bruto.pop("custo_minuto", None) if "custo_hora" in bruto else None
        for el in controles.values():
            el.props(remove="error error-message")
        try:
            with estado.sessao() as s:
                C.gravar(s, self.modulo, bruto, id_edicao=id_edicao, vazios_apagam=id_edicao is not None)
        except C.ErroValidacao as e:
            gerais = []
            for campo, msg in e.erros:
                alvo = controles.get(campo) or (controles.get("custo_hora") if campo == "custo_minuto" else None)
                if alvo is not None:
                    alvo.props(f'error error-message="{_escapar(msg)}"')
                else:
                    gerais.append(msg)
            ui.notify("Corrija os campos destacados." + (" " + "; ".join(gerais) if gerais else ""),
                      type="negative", multi_line=True)
            return
        dlg.close()
        ui.notify("Registro salvo.", type="positive")
        self._mudou()

    # ------------------------------------------------------------------ ações de linha
    def _alternar_ativo(self, linha: dict) -> None:
        with estado.sessao() as s:
            C.definir_ativo(s, self.modulo, linha["id"], linha.get("ativo") == "não")
        self._mudou()

    def _confirmar_exclusao(self, linha: dict) -> None:
        chave = " / ".join(str(linha.get(k, "")) for k in self.modulo.chave_negocio)
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Excluir {chave}?").classes("text-subtitle1")
            ui.label("Esta ação não pode ser desfeita.").classes("text-caption text-grey-7")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancelar", on_click=dlg.close).props("flat")
                ui.button("Excluir", color="negative", on_click=lambda: self._excluir(dlg, linha)) \
                    .mark("confirmar-exclusao")
        dlg.open()

    def _excluir(self, dlg, linha: dict) -> None:
        dlg.close()
        try:
            with estado.sessao() as s:
                C.excluir(s, self.modulo, linha["id"])
        except C.ErroValidacao as e:
            ui.notify(str(e), type="warning", multi_line=True, timeout=8000)
            return
        ui.notify("Registro excluído.", type="positive")
        self._mudou()

    # ------------------------------------------------------------------ planilhas
    def _importar(self) -> None:
        abrir_importacao(self.modulo.chave, ao_concluir=self._mudou)

    def _baixar_modelo(self) -> None:
        ui.download(gerar_modelo(self.modulo), f"modelo_{self.modulo.chave}.xlsx")

    def _exportar(self) -> None:
        with estado.sessao() as s:
            conteudo = exportar(s, self.modulo)
        ui.download(conteudo, f"{self.modulo.chave}_{date.today().isoformat()}.xlsx")
