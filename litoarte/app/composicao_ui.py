"""Tela central: Composição de Preço (ficha técnica + formação do preço em tempo real + simulador)."""

from __future__ import annotations

from nicegui import ui

from ..domain.services import composicao as C
from ..domain.services.cadastros import ErroValidacao
from . import estado
from .campos import campo_numero, ler
from .formatos import brl, num, pct

ROTULO_MODO = {"fixa": "fixa", "area": "por área (m²)", "perimetro": "por perímetro (m)",
               "aproveitamento": "aproveitamento de folha"}


def _f(v) -> float | None:
    """Valor numérico do controle (formato brasileiro; None se vazio ou inválido)."""
    return ler(v)


# ============================================================================ clonagem (usada também na lista)
def abrir_clonagem(produto_id: int, ao_criar=None) -> None:
    with estado.sessao() as s:
        r = C.rascunho_de_produto(s, produto_id)
        cat = C.carregar_catalogo(s)
        sku_sugerido = C.sugerir_sku(s, r.sku)
    subs = {sid: f"{g} - {gn} › {sc} - {sn}" for sid, (g, gn, sc, sn) in cat.subgrupos.items()}
    with ui.dialog() as dlg, ui.card().classes("w-[620px] max-w-full"):
        ui.label(f"Duplicar “{r.sku} — {r.nome}”").classes("text-h6")
        ui.label("O novo produto herda grupo/subgrupo, ficha técnica (materiais e mão de obra), perfil de venda "
                 "e margem. Ajuste o que mudar.").classes("text-caption text-grey-7")
        with ui.grid(columns=2).classes("w-full gap-x-4"):
            sku = ui.input("Novo SKU *", value=sku_sugerido).props("outlined dense").mark("clone-sku")
            nome = ui.input("Novo nome *", value=f"{r.nome} (cópia)").props("outlined dense").mark("clone-nome")
            sub = ui.select(subs, label="Subgrupo", value=r.subgrupo_id, with_input=True) \
                .props("outlined dense").classes("col-span-2")
            larg = campo_numero("Largura (cm)", r.largura_cm)
            alt = campo_numero("Altura (cm)", r.altura_cm)
        with ui.row().classes("gap-4"):
            c_mat = ui.checkbox("materiais", value=True)
            c_mo = ui.checkbox("mão de obra", value=True)
            c_cfg = ui.checkbox("perfil de venda e margem", value=True)
            c_preco = ui.checkbox("preço praticado", value=False)

        def criar():
            for el in (sku, nome):
                el.props(remove="error error-message")
            try:
                with estado.sessao() as s:
                    novo = C.clonar(s, produto_id, sku=(sku.value or "").strip(), nome=nome.value or "",
                                    subgrupo_id=sub.value, largura_cm=_f(larg.value), altura_cm=_f(alt.value),
                                    copiar_materiais=c_mat.value, copiar_mao_de_obra=c_mo.value,
                                    copiar_perfil_margem=c_cfg.value, copiar_preco=c_preco.value)
                    novo_id = novo.id
            except ErroValidacao as e:
                for campo, msg in e.erros:
                    alvo = {"sku": sku, "nome": nome}.get(campo)
                    if alvo is not None:
                        alvo.props(f'error error-message="{msg}"')
                ui.notify(str(e), type="negative", multi_line=True)
                return
            dlg.close()
            ui.notify("Produto duplicado.", type="positive")
            if ao_criar:
                ao_criar(novo_id)
            else:
                ui.navigate.to(f"/produtos/{novo_id}")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancelar", on_click=dlg.close).props("flat")
            ui.button("Duplicar e abrir", icon="content_copy", on_click=criar).mark("clone-confirmar")
    dlg.open()


# ============================================================================ tela de composição
class TelaComposicao:
    def __init__(self, produto_id: int | None):
        with estado.sessao() as s:
            self.cat = C.carregar_catalogo(s)
            self.r = C.rascunho_de_produto(s, produto_id) if produto_id else C.Rascunho(
                subgrupo_id=next(iter(self.cat.subgrupos), None))
        self.sujo = False
        self.sim = {"margem": None, "preco": None}
        self.rotulos_mat: dict[int, ui.label] = {}
        self.rotulos_mo: dict[int, ui.label] = {}
        self.res = C.calcular_rascunho(self.cat, self.r)

    # ------------------------------------------------------------------ montagem
    def render(self) -> None:
        r = self.r
        with ui.row().classes("w-full items-center"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/produtos")).props("flat round")
            self.titulo = ui.label().classes("text-h6")
            self.chip_sujo = ui.badge("alterações não salvas", color="warning").props("outline")
            ui.space()
            if r.id:
                ui.button("Duplicar", icon="content_copy", on_click=self._duplicar).props("outline") \
                    .mark("duplicar")
                ui.button("Excluir", icon="delete", color="negative", on_click=self._excluir).props("flat")
            ui.button("Salvar", icon="save", on_click=self._salvar).mark("salvar-produto")
        self._atualizar_titulo()

        self._cabecalho()
        with ui.row().classes("w-full gap-4 items-start no-wrap max-lg:flex-wrap"):
            with ui.column().classes("grow min-w-0 gap-4"):
                with ui.card().classes("w-full"):
                    with ui.tabs().classes("w-full").props("align=left dense") as abas:
                        t_mat = ui.tab("Materiais", icon="inventory_2")
                        t_mo = ui.tab("Mão de obra", icon="engineering")
                    with ui.tab_panels(abas, value=t_mat).classes("w-full"):
                        with ui.tab_panel(t_mat).classes("q-pa-none"):
                            self._materiais()
                        with ui.tab_panel(t_mo).classes("q-pa-none"):
                            self._mao_de_obra()
                self._canais()
            with ui.column().classes("w-[400px] max-lg:w-full shrink-0 gap-4 sticky top-16"):
                self._painel()
                self._simulador()
        self._recalcular(marcar=False)

    def _atualizar_titulo(self):
        self.titulo.text = f"{self.r.sku or 'Novo produto'}" + (f" — {self.r.nome}" if self.r.nome else "")
        self.chip_sujo.set_visibility(self.sujo)
        # o navegador pede confirmação ao sair/fechar enquanto houver alterações não salvas
        if self.sujo != getattr(self, "_aviso_saida", False):
            self._aviso_saida = self.sujo
            ui.run_javascript("window.onbeforeunload = (e) => { e.preventDefault(); return ''; };" if self.sujo
                              else "window.onbeforeunload = null;")

    def _mudou(self, recalcular: bool = True):
        self.sujo = True
        self._atualizar_titulo()
        if recalcular:
            self._recalcular()

    # ------------------------------------------------------------------ cabeçalho
    def _cabecalho(self):
        r, cat = self.r, self.cat
        grupos = {}
        for sid, (g, gn, sc, sn) in cat.subgrupos.items():
            grupos.setdefault(g, gn)
        grupo_atual = cat.subgrupos[r.subgrupo_id][0] if r.subgrupo_id in cat.subgrupos else None
        padrao = cat.perfil_padrao
        perfis = {0: f"Padrão ({padrao.nome})" if padrao else "Padrão"} | \
                 {p.id: p.nome for p in cat.perfis.values()}
        self.ctl: dict[str, ui.element] = {}
        with ui.card().classes("w-full"):
            with ui.grid(columns=6).classes("w-full gap-x-3 gap-y-1 max-md:grid-cols-2"):
                self.ctl["sku"] = ui.input("SKU *", value=r.sku, on_change=lambda e: self._set("sku", e.value, False)) \
                    .props("outlined dense").mark("prod-sku")
                self.ctl["nome"] = ui.input("Nome *", value=r.nome,
                                            on_change=lambda e: self._set("nome", e.value, False)) \
                    .props("outlined dense").classes("col-span-3 max-md:col-span-2").mark("prod-nome")
                self.ctl["ativo"] = ui.switch("Ativo", value=r.ativo, on_change=lambda e: self._set("ativo", e.value, False))
                ui.space()
                self.ctl["grupo"] = ui.select({g: f"{g} - {n}" for g, n in grupos.items()}, label="Grupo *",
                                              value=grupo_atual, on_change=lambda e: self._grupo(e.value)) \
                    .props("outlined dense").classes("col-span-2")
                self.ctl["subgrupo_id"] = ui.select(self._subs_do_grupo(grupo_atual), label="Subgrupo *",
                                                    value=r.subgrupo_id,
                                                    on_change=lambda e: self._set("subgrupo_id", e.value, False)) \
                    .props("outlined dense").classes("col-span-2").mark("prod-subgrupo")
                self.ctl["largura_cm"] = campo_numero("Largura (cm)", r.largura_cm, lambda v: self._set("largura_cm", v)).props("debounce=300").mark("prod-largura")
                self.ctl["altura_cm"] = campo_numero("Altura (cm)", r.altura_cm, lambda v: self._set("altura_cm", v)).props("debounce=300").mark("prod-altura")
                self.ctl["perfil_venda_id"] = ui.select(perfis, label="Perfil de venda",
                                                        value=r.perfil_venda_id or 0,
                                                        on_change=lambda e: self._set("perfil_venda_id", e.value or None)) \
                    .props("outlined dense").classes("col-span-2")
                self.ctl["margem_desejada_pct"] = campo_numero(
                    "Margem desejada (%)", r.margem_desejada_pct, lambda v: self._set("margem_desejada_pct", v)) \
                    .props(f'debounce=300 hint="vazio = padrão ({num(cat.regras.margem_padrao_pct)} %)"') \
                    .mark("prod-margem")
                self.ctl["preco_praticado"] = campo_numero(
                    "Preço praticado (R$)", r.preco_praticado, lambda v: self._set("preco_praticado", v)) \
                    .props('debounce=300 hint="preço de tabela atual (opcional)"').mark("prod-preco")

    def _subs_do_grupo(self, grupo: str | None) -> dict:
        return {sid: f"{sc} - {sn}" for sid, (g, gn, sc, sn) in self.cat.subgrupos.items() if g == grupo}

    def _grupo(self, grupo):
        sel = self.ctl["subgrupo_id"]
        sel.options = self._subs_do_grupo(grupo)
        sel.value = next(iter(sel.options), None)
        sel.update()

    def _set(self, campo, valor, recalcular=True):
        setattr(self.r, campo, valor)
        self._mudou(recalcular)

    # ------------------------------------------------------------------ ficha: materiais
    @ui.refreshable_method
    def _materiais(self):
        r, cat = self.r, self.cat
        self.rotulos_mat.clear()
        opcoes = {i.id: f"{i.sku} — {i.nome} ({brl(i.custo_consumo, 4)}/{i.unidade_consumo})"
                  + ("" if i.ativo else " — INATIVO") for i in cat.insumos.values()}
        if not r.materiais:
            ui.label("Nenhum material na ficha.").classes("text-grey-7 q-pa-sm")
        for idx, l in enumerate(r.materiais):
            ins = cat.insumos.get(l.insumo_id)
            with ui.row().classes("w-full items-center gap-2 no-wrap q-py-xs"):
                ui.select(opcoes, label="Insumo", value=l.insumo_id, with_input=True,
                          on_change=lambda e, l=l: self._mat_insumo(l, e.value)) \
                    .props("outlined dense options-dense").classes("grow min-w-56").mark(f"mat-insumo-{idx}")
                ui.select(ROTULO_MODO, label="Modo", value=l.modo_qtd,
                          on_change=lambda e, l=l: self._mat(l, "modo_qtd", e.value, refazer=True)) \
                    .props("outlined dense").classes("w-44").mark(f"mat-modo-{idx}")
                sufixo = (ins.unidade_consumo if ins else "") + {"area": " por m²", "perimetro": " por m",
                                                                  "aproveitamento": " folha", "fixa": ""}[l.modo_qtd]
                campo_numero("Qtd", l.quantidade, lambda v, l=l: self._mat(l, "quantidade", v), limpar=False) \
                    .props(f'debounce=250 suffix="{sufixo}" input-class="text-right"').classes("w-40") \
                    .mark(f"mat-qtd-{idx}")
                campo_numero("Perda %", l.perda_pct, lambda v, l=l: self._mat(l, "perda_pct", v), limpar=False) \
                    .props(f'debounce=250 placeholder="{num(ins.perda_pct) if ins else ""}" '
                           f'input-class="text-right"').classes("w-24")
                if l.modo_qtd == "aproveitamento":
                    campo_numero("Espaço cm", l.espacamento_cm,
                                 lambda v, l=l: self._mat(l, "espacamento_cm", v or 0.0), limpar=False) \
                        .props("debounce=250").classes("w-24")
                self.rotulos_mat[idx] = ui.label("—").classes("w-28 text-right text-weight-medium")
                ui.button(icon="close", on_click=lambda l=l: self._remover(r.materiais, l, self._materiais)) \
                    .props("flat round dense size=sm color=negative")
            if l.modo_qtd == "aproveitamento":
                self.rotulos_mat[(idx, "info")] = ui.label("").classes("text-caption text-grey-7 q-pl-sm")
        with ui.row().classes("w-full items-center"):
            ui.button("Adicionar material", icon="add",
                      on_click=lambda: self._adicionar(r.materiais, C.LinhaMat(), self._materiais)) \
                .props("flat").mark("add-material")
            ui.space()
            self.total_mp = ui.label().classes("text-weight-bold q-pr-xl")
        self._rotulos_materiais()

    async def _mat_insumo(self, l: C.LinhaMat, insumo_id):
        l.insumo_id = insumo_id
        ins = self.cat.insumos.get(insumo_id)
        if ins and ins.folha and l.modo_qtd == "fixa":
            l.modo_qtd = "aproveitamento"        # folha/chapa: sugere aproveitamento
            if l.quantidade is None:
                l.quantidade = 1.0
        await self._redesenhar(self._materiais)

    async def _mat(self, l, campo, valor, refazer=False):
        setattr(l, campo, valor)
        if refazer:
            await self._redesenhar(self._materiais)
        else:
            self._mudou()

    # ------------------------------------------------------------------ ficha: mão de obra
    @ui.refreshable_method
    def _mao_de_obra(self):
        r, cat = self.r, self.cat
        self.rotulos_mo.clear()
        opcoes = {e.id: f"{e.codigo} — {e.etapa} ({brl(e.custo_hora / 60, 4)}/min)"
                  + ("" if e.ativo else " — INATIVA") for e in cat.etapas.values()}
        if not r.mao_de_obra:
            ui.label("Nenhuma etapa de mão de obra.").classes("text-grey-7 q-pa-sm")
        for idx, l in enumerate(r.mao_de_obra):
            with ui.row().classes("w-full items-center gap-2 no-wrap q-py-xs"):
                ui.select(opcoes, label="Etapa", value=l.etapa_id, with_input=True,
                          on_change=lambda e, l=l: self._mo(l, "etapa_id", e.value)) \
                    .props("outlined dense options-dense").classes("grow min-w-56").mark(f"mo-etapa-{idx}")
                campo_numero("Tempo", l.tempo, lambda v, l=l: self._mo(l, "tempo", v), limpar=False) \
                    .props("debounce=250").classes("w-28").mark(f"mo-tempo-{idx}")
                ui.toggle({"min": "min", "h": "h"}, value=l.unidade_tempo,
                          on_change=lambda e, l=l: self._mo(l, "unidade_tempo", e.value)).props("dense no-caps")
                self.rotulos_mo[idx] = ui.label("—").classes("w-28 text-right text-weight-medium")
                ui.button(icon="close", on_click=lambda l=l: self._remover(r.mao_de_obra, l, self._mao_de_obra)) \
                    .props("flat round dense size=sm color=negative")
        with ui.row().classes("w-full items-center"):
            ui.button("Adicionar etapa", icon="add",
                      on_click=lambda: self._adicionar(r.mao_de_obra, C.LinhaMO(), self._mao_de_obra)) \
                .props("flat").mark("add-etapa")
            ui.space()
            self.total_mo = ui.label().classes("text-weight-bold q-pr-xl")
        self._rotulos_mao_de_obra()

    def _mo(self, l, campo, valor):
        setattr(l, campo, valor)
        self._mudou()

    async def _adicionar(self, lista, linha, area):
        lista.append(linha)
        await self._redesenhar(area)

    async def _remover(self, lista, linha, area):
        lista.remove(linha)
        await self._redesenhar(area)

    async def _redesenhar(self, area):
        """Recalcula ANTES de redesenhar (o desenho usa self.res) e aguarda o redesenho.

        No NiceGUI 4 o refresh é assíncrono: sem aguardar, rótulos seriam atualizados nos elementos antigos.
        """
        self.sujo = True
        self._atualizar_titulo()
        self.res = C.calcular_rascunho(self.cat, self.r)
        await area.refresh()
        self._recalcular()

    # ------------------------------------------------------------------ cálculo e painéis
    def _recalcular(self, marcar: bool = True):
        self.res = C.calcular_rascunho(self.cat, self.r)
        self._rotulos_materiais()
        self._rotulos_mao_de_obra()
        self._painel.refresh()
        self._ajustar_slider()
        self._sim_margem.refresh()
        self._sim_preco.refresh()
        self._canais.refresh()

    def _rotulos_materiais(self):
        res, r, cat = self.res, self.r, self.cat
        completas = [i for i, l in enumerate(r.materiais) if l.insumo_id in cat.insumos and l.quantidade is not None]
        por_idx = dict(zip(completas, res.materiais))
        for idx, rot in list(self.rotulos_mat.items()):
            if isinstance(idx, tuple):
                m = por_idx.get(idx[0])
                rot.text = (f"{m.pecas_folha} peças/folha ({m.disposicao}) · aproveitamento "
                            f"{pct(m.aproveitamento_pct, 1)} · consumo {num(m.qtd_comprada, 6)} folha"
                            if m and m.pecas_folha else (m.alerta or "") if m else "")
                continue
            m = por_idx.get(idx)
            rot.text = brl(m.custo, 4) if m else "—"
            rot.classes(replace="w-28 text-right text-weight-medium" + (" text-negative" if m and m.alerta else ""))
        self.total_mp.text = f"Materiais: {brl(res.mp)}"

    def _rotulos_mao_de_obra(self):
        res, r, cat = self.res, self.r, self.cat
        completas_mo = [i for i, l in enumerate(r.mao_de_obra) if l.etapa_id in cat.etapas and l.tempo is not None]
        for idx, m in zip(completas_mo, res.mao_de_obra):
            self.rotulos_mo[idx].text = brl(m.custo, 4)
        for idx in set(self.rotulos_mo) - set(completas_mo):
            self.rotulos_mo[idx].text = "—"
        self.total_mo.text = f"Mão de obra: {brl(res.mo)}"

    @ui.refreshable_method
    def _painel(self):
        res = self.res
        with ui.card().classes("w-full").mark("painel-preco"):
            ui.label("Formação do preço").classes("text-subtitle1 text-weight-medium")

            def linha(rot, val, forte=False, cor=""):
                with ui.row().classes("w-full justify-between no-wrap"):
                    ui.label(rot).classes("text-grey-8" + (" text-weight-bold" if forte else ""))
                    ui.label(val).classes(("text-weight-bold " if forte else "") + cor)
            linha("Materiais", brl(res.mp))
            linha("Mão de obra", brl(res.mo))
            linha("Custo direto", brl(res.cd), forte=True)
            if res.pct_cf:
                linha(f"Custo fixo ({pct(res.pct_cf)} do preço)", brl(res.parcela_cf))
            elif res.cf_unit:
                linha("Custo fixo (rateio por unidade/hora)", brl(res.cf_unit))
            cv_txt = f"Custos variáveis ({pct(res.pct_cv)}" + (f" + {brl(res.cv_fixo)}" if res.cv_fixo else "") + ")"
            linha(cv_txt, brl(res.parcela_cv))
            linha(f"Lucro ({pct(res.pct_ml)})", brl(res.lucro), cor="text-positive")
            ui.separator()
            with ui.row().classes("w-full justify-between items-end no-wrap"):
                ui.label("Preço de venda sugerido").classes("text-weight-medium")
                ui.label(brl(res.preco)).classes("text-h5 text-primary text-weight-bold").mark("preco-sugerido")
            ui.label(f"Markup {num(res.markup, 4)} × · divisor {num(res.markup_divisor, 4)} · "
                     f"mínimo (lucro zero) {brl(res.preco_minimo)} · cobertura (MC zero) {brl(res.preco_cobertura)}") \
                .classes("text-caption text-grey-7")
            if self.r.preco_praticado and res.preco:
                s = res.simular(self.r.preco_praticado)
                cor = "text-negative" if s.margem_pct < res.pct_ml else "text-positive"
                ui.label(f"No preço praticado {brl(self.r.preco_praticado)}: margem {pct(s.margem_pct)} "
                         f"({brl(s.lucro)})").classes(f"text-body2 {cor}")
            for a in res.alertas:
                ui.label("⚠ " + a).classes("text-caption text-warning")

    def _simulador(self):
        """Controles criados UMA vez (não perdem o foco ao digitar); só os resultados são redesenhados."""
        res = self.res
        with ui.card().classes("w-full"):
            ui.label("Simulador").classes("text-subtitle1 text-weight-medium")
            self.lbl_margem = ui.label().classes("text-body2")
            self._ignorar_slider = False
            self.slider = ui.slider(min=0, max=95, step=0.5, value=res.pct_ml,
                                    on_change=self._slider_mudou).props("label").mark("sim-margem")
            self._sim_margem()
            ui.separator()
            campo_numero("Preço manual (R$)", None, lambda v: self._sim("preco", v)) \
                .props("debounce=300").classes("w-full").mark("sim-preco")
            self._sim_preco()

    def _slider_mudou(self, e):
        if self._ignorar_slider:
            return
        self._sim("margem", e.value)

    def _ajustar_slider(self):
        res = self.res
        maximo = round(max(1.0, min(95.0, res.margem_maxima_pct - 0.5)), 1)
        self.slider.props(f"max={maximo}")
        margem = self.sim["margem"] if self.sim["margem"] is not None else res.pct_ml
        self.lbl_margem.text = f"Margem desejada: {pct(margem, 1)}"
        if self.sim["margem"] is None and self.slider.value != min(res.pct_ml, maximo):
            self._ignorar_slider = True
            self.slider.value = min(res.pct_ml, maximo)
            self._ignorar_slider = False

    @ui.refreshable_method
    def _sim_margem(self):
        margem = self.sim["margem"] if self.sim["margem"] is not None else self.res.pct_ml
        rm = C.calcular_rascunho(self.cat, self.r, margem_pct=margem)
        if rm.preco:
            self._resultado_sim(f"Preço para {pct(margem, 1)}", rm.preco, rm.simular(rm.preco))
            ui.button("Aplicar esta margem ao produto", on_click=lambda: self._aplicar_margem(margem)) \
                .props("flat dense no-caps")
        else:
            ui.label("Margem impossível com os custos variáveis e fixos atuais.").classes("text-negative")

    @ui.refreshable_method
    def _sim_preco(self):
        preco = self.sim["preco"]
        if preco and preco > 0 and self.res.cd > 0:
            self._resultado_sim("Resultado", preco, self.res.simular(preco), destaque=True)
            ui.button("Usar como preço praticado", on_click=lambda: self._aplicar_preco(preco)) \
                .props("flat dense no-caps")

    def _resultado_sim(self, titulo, preco, s, destaque=False):
        cor = "text-negative" if s.lucro < 0 else "text-positive"
        with ui.column().classes("w-full gap-0" + (" bg-blue-1 q-pa-sm rounded-borders" if destaque else "")) \
                .mark("sim-resultado" if destaque else "sim-margem-resultado"):
            ui.label(f"{titulo}: {brl(preco)}").classes("text-weight-medium")
            ui.label(f"Lucro líquido {brl(s.lucro)} · {pct(s.margem_pct)}").classes(cor)
            ui.label(f"Margem de contribuição {brl(s.margem_contribuicao)} · {pct(s.margem_contribuicao_pct)}") \
                .classes("text-caption")
            pe = f"{s.ponto_equilibrio_un} un/mês" if s.ponto_equilibrio_un else "não atinge (MC ≤ 0)"
            ui.label(f"Ponto de equilíbrio: {pe} só deste produto para cobrir {brl(self.res.custo_fixo_total)} "
                     f"de custo fixo").classes("text-caption text-grey-8")

    def _sim(self, chave, valor):
        self.sim[chave] = valor
        self._ajustar_slider()
        (self._sim_margem if chave == "margem" else self._sim_preco).refresh()

    def _aplicar_margem(self, margem):
        self.r.margem_desejada_pct = margem
        self.ctl["margem_desejada_pct"].value = num(margem, 6)
        self.sim["margem"] = None
        self._mudou()

    def _aplicar_preco(self, preco):
        self.r.preco_praticado = preco
        self.ctl["preco_praticado"].value = num(preco, 6)
        self._mudou()

    @ui.refreshable_method
    def _canais(self):
        canais = C.comparar_canais(self.cat, self.r)
        if len(canais) < 2:
            return
        with ui.card().classes("w-full"):
            ui.label("Comparativo por canal de venda").classes("text-subtitle1 text-weight-medium")
            rows = [{"canal": c.nome + (" (padrão)" if c.padrao else "") + (" ◀ atual" if c.atual else ""),
                     "cv": pct(c.resultado.pct_cv) + (f" + {brl(c.resultado.cv_fixo)}" if c.resultado.cv_fixo else ""),
                     "preco": brl(c.resultado.preco), "pratic": pct(c.margem_no_praticado) if c.margem_no_praticado
                     is not None else "—"} for c in canais]
            ui.table(rows=rows, row_key="canal", columns=[
                {"name": "canal", "label": "Perfil", "field": "canal", "align": "left"},
                {"name": "cv", "label": "Custos variáveis", "field": "cv", "align": "right"},
                {"name": "preco", "label": "Preço sugerido", "field": "preco", "align": "right"},
                {"name": "pratic", "label": "Margem no preço praticado", "field": "pratic", "align": "right"},
            ]).props("flat dense").classes("w-full").mark("tabela-canais")

    # ------------------------------------------------------------------ ações
    def _salvar(self):
        for el in self.ctl.values():
            el.props(remove="error error-message")
        novo = self.r.id is None
        try:
            with estado.sessao() as s:
                C.salvar(s, self.r)
        except ErroValidacao as e:
            linhas = []
            for campo, msg in e.erros:
                alvo = self.ctl.get(campo)
                if alvo is not None:
                    alvo.props(f'error error-message="{msg}"')
                else:
                    linhas.append(f"{campo}: {msg}")
            ui.notify("Não foi possível salvar. " + ("; ".join(linhas) if linhas else "Corrija os campos destacados."),
                      type="negative", multi_line=True, timeout=8000)
            return
        self.sujo = False
        self._atualizar_titulo()
        ui.notify("Produto salvo.", type="positive")
        if novo:
            ui.navigate.to(f"/produtos/{self.r.id}")

    def _duplicar(self):
        if self.sujo:
            ui.notify("Salve as alterações antes de duplicar (a cópia parte do produto gravado).", type="warning")
            return
        abrir_clonagem(self.r.id)

    def _excluir(self):
        with ui.dialog() as dlg, ui.card():
            ui.label(f"Excluir o produto {self.r.sku} e sua ficha técnica?").classes("text-subtitle1")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancelar", on_click=dlg.close).props("flat")

                def ok():
                    with estado.sessao() as s:
                        C.excluir(s, self.r.id)
                    self.sujo = False
                    self._atualizar_titulo()
                    dlg.close()
                    ui.notify("Produto excluído.", type="positive")
                    ui.navigate.to("/produtos")
                ui.button("Excluir", color="negative", on_click=ok)
        dlg.open()
