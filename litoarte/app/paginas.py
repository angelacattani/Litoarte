"""Páginas da aplicação. `registrar()` é chamado na inicialização (necessário para os testes)."""

from __future__ import annotations

from nicegui import ui
from sqlalchemy import func, select

from ..domain.models import (CustoFixo, CustoVariavel, Grupo, MaoDeObra, MateriaPrima, PerfilVenda, Subgrupo)
from ..domain.services import configuracao as cfgsvc, perfis as perfsvc
from ..domain.services.cadastros import ErroValidacao
from ..domain.services.precificacao import configuracao, regras_empresa
from . import estado
from .crud import TelaCadastro
from .formatos import brl, num, pct
from .layout import moldura


def _cartao(titulo: str, valor: str, legenda: str = "", destino: str | None = None):
    with ui.card().classes("min-w-48 cursor-pointer" if destino else "min-w-48") as c:
        ui.label(titulo).classes("text-caption text-grey-7")
        ui.label(valor).classes("text-h6 text-weight-medium")
        if legenda:
            ui.label(legenda).classes("text-caption text-grey-7")
    if destino:
        c.on("click", lambda: ui.navigate.to(destino))
    return c


# ============================================================================ início
def pagina_inicio():
    with moldura("Início", "/"):
        with estado.sessao() as s:
            r = regras_empresa(s)
            cfg = configuracao(s)
            cont = {m.__name__: s.scalar(select(func.count()).select_from(m)) for m in
                    (MateriaPrima, MaoDeObra, CustoFixo, CustoVariavel, Grupo, Subgrupo)}
            padrao = perfsvc.listar(s)[0] if perfsvc.listar(s) else None
            pct_cv = perfsvc.resumo(padrao)[0] if padrao else 0
            custos_no_padrao = len(padrao.custos) if padrao else 0
        with ui.row().classes("gap-4"):
            _cartao("Custo fixo mensal", brl(r.custo_fixo_total), f"{cont['CustoFixo']} item(ns)", "/custos-fixos")
            if cfg.metodo_rateio == "pct_faturamento" and cfg.faturamento_base_mensal:
                _cartao("Absorção do custo fixo", pct(100 * r.custo_fixo_total / cfg.faturamento_base_mensal),
                        f"sobre faturamento base de {brl(cfg.faturamento_base_mensal)}", "/configuracao")
            _cartao("Custos variáveis (perfil padrão)", pct(pct_cv), padrao.nome if padrao else "—",
                    "/custos-variaveis")
            _cartao("Margem padrão", pct(cfg.margem_padrao_pct), "Configuração", "/configuracao")
        with ui.row().classes("gap-4"):
            _cartao("Matérias-primas", str(cont["MateriaPrima"]), "", "/materias-primas")
            _cartao("Etapas de mão de obra", str(cont["MaoDeObra"]), "", "/mao-de-obra")
            _cartao("Grupos / subgrupos", f"{cont['Grupo']} / {cont['Subgrupo']}", "", "/grupos")
        passos = [
            ("Definir rateio e faturamento base", "/configuracao",
             cfg.metodo_rateio != "pct_faturamento" or bool(cfg.faturamento_base_mensal)),
            ("Cadastrar custos fixos", "/custos-fixos", cont["CustoFixo"] > 0),
            ("Cadastrar custos variáveis no perfil padrão", "/custos-variaveis", custos_no_padrao > 0),
            ("Cadastrar mão de obra", "/mao-de-obra", cont["MaoDeObra"] > 0),
            ("Cadastrar matérias-primas", "/materias-primas", cont["MateriaPrima"] > 0),
            ("Cadastrar grupos e subgrupos", "/grupos", cont["Subgrupo"] > 0),
        ]
        with ui.card().classes("w-full"):
            ui.label("Primeiros passos").classes("text-subtitle1 text-weight-medium")
            ui.label("Todos os cadastros aceitam importação em massa por planilha (botão Importar em cada tela).") \
                .classes("text-caption text-grey-7")
            for texto, destino, feito in passos:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle" if feito else "radio_button_unchecked",
                            color="positive" if feito else "grey")
                    ui.link(texto, destino).classes("text-body1" + (" text-grey-7" if feito else ""))
            ui.label("Produtos, ficha técnica e composição de preço chegam na fase 3.").classes(
                "text-caption text-grey-7 q-mt-sm")


# ============================================================================ cadastros simples
def _pagina_simples(titulo: str, rota: str, chave: str, descricao: str):
    with moldura(titulo, rota):
        TelaCadastro(chave, descricao=descricao).render()


def pagina_materias_primas():
    _pagina_simples("Matérias-primas", "/materias-primas", "materias_primas",
                    "Custo de compra por unidade de compra. A conversão diz quantas unidades de consumo há em cada "
                    "unidade comprada (frasco de 1 L = 1000 ml): a ficha técnica usa a unidade de consumo. "
                    "Para folhas/chapas usadas por aproveitamento, informe largura e comprimento.")


def pagina_mao_de_obra():
    _pagina_simples("Mão de obra", "/mao-de-obra", "mao_de_obra",
                    "Custo por etapa produtiva. Modo informado: custo por hora ou por minuto com encargos inclusos. "
                    "Modo calculado: salário × (1 + encargos) ÷ horas produtivas do mês.")


def pagina_unidades():
    _pagina_simples("Unidades de medida", "/unidades", "unidades",
                    "Siglas usadas como unidade de compra e de consumo das matérias-primas.")


def pagina_fornecedores():
    _pagina_simples("Fornecedores", "/fornecedores", "fornecedores",
                    "Fornecedores também são criados automaticamente ao informar um nome novo na matéria-prima.")


# ============================================================================ custos fixos
def pagina_custos_fixos():
    with moldura("Custos fixos", "/custos-fixos"):
        @ui.refreshable
        def resumo():
            with estado.sessao() as s:
                r = regras_empresa(s)
                cfg = configuracao(s)
            with ui.row().classes("gap-4 items-stretch"):
                _cartao("Custo fixo total mensal", brl(r.custo_fixo_total), "soma dos itens ativos")
                if r.metodo_rateio == "pct_faturamento":
                    if cfg.faturamento_base_mensal:
                        _cartao("Absorção no preço (%CF)", pct(100 * r.custo_fixo_total / cfg.faturamento_base_mensal),
                                f"÷ faturamento base {brl(cfg.faturamento_base_mensal)}", "/configuracao")
                    else:
                        _cartao("Absorção no preço (%CF)", "—", "defina o faturamento base", "/configuracao")
                elif r.metodo_rateio == "hora_produtiva":
                    taxa = r.custo_fixo_total / r.capacidade_horas if r.capacidade_horas else None
                    _cartao("Custo fixo por hora produtiva", brl(taxa), f"÷ {num(r.capacidade_horas, 1)} h/mês",
                            "/configuracao")
                else:
                    taxa = r.custo_fixo_total / r.capacidade_unidades if r.capacidade_unidades else None
                    _cartao("Custo fixo por unidade", brl(taxa), f"÷ {num(r.capacidade_unidades, 0)} un/mês",
                            "/configuracao")
        resumo()
        TelaCadastro("custos_fixos", ao_mudar=resumo.refresh,
                     descricao="Despesas mensais que não variam com o volume vendido (aluguel, energia, internet, "
                               "pró-labore, softwares...). Não inclua aqui a mão de obra já cadastrada por etapa.").render()


# ============================================================================ custos variáveis + perfis
def pagina_custos_variaveis():
    with moldura("Custos variáveis e perfis de venda", "/custos-variaveis"):
        @ui.refreshable
        def painel_perfis():
            with estado.sessao() as s:
                lista = perfsvc.listar(s)
                custos = list(s.scalars(select(CustoVariavel).order_by(CustoVariavel.codigo)))
                membros = {p.id: {c.id for c in p.custos} for p in lista}
                resumos = {p.id: perfsvc.resumo(p) for p in lista}
                dados = [(p.id, p.nome, p.padrao) for p in lista]
                custos = [(c.id, c.codigo, c.descricao, c.tipo, c.valor, c.ativo) for c in custos]
            with ui.row().classes("w-full items-center"):
                ui.label("Perfis de venda").classes("text-subtitle1 text-weight-medium")
                ui.label("Cada canal reúne os custos que incidem sobre a venda. O produto usa o perfil padrão "
                         "salvo indicação contrária.").classes("text-caption text-grey-7")
                ui.space()
                ui.button("Novo perfil", icon="add", on_click=novo_perfil).props("outline")
            with ui.row().classes("w-full gap-4 items-stretch"):
                for pid, nome, padrao in dados:
                    pct_cv, fixo = resumos[pid]
                    with ui.card().classes("w-80"):
                        with ui.row().classes("w-full items-center no-wrap"):
                            ui.label(nome).classes("text-subtitle1 text-weight-medium")
                            if padrao:
                                ui.badge("padrão", color="accent")
                            ui.space()
                            with ui.button(icon="more_vert").props("flat round dense"):
                                with ui.menu():
                                    ui.menu_item("Renomear", lambda p=pid, n=nome: renomear(p, n))
                                    if not padrao:
                                        ui.menu_item("Tornar padrão", lambda p=pid: acao(perfsvc.definir_padrao, p))
                                        ui.menu_item("Excluir", lambda p=pid: acao(perfsvc.excluir, p))
                                    ui.menu_item("Duplicar", lambda p=pid, n=nome: novo_perfil(copiar=(p, n)))
                        ui.label(f"{pct(pct_cv)} do preço" + (f" + {brl(fixo)}/un" if fixo else "")) \
                            .classes("text-h6 text-primary")
                        for cid, cod, desc, tipo, valor, ativo in custos:
                            rot = f"{desc} ({pct(valor) if tipo == 'percentual' else brl(valor)})" + \
                                  ("" if ativo else " — inativo")
                            ui.checkbox(rot, value=cid in membros[pid],
                                        on_change=lambda e, p=pid, c=cid: acao(perfsvc.definir_custo, p, c, e.value)) \
                                .props("dense").classes("" if ativo else "text-grey-6")
                        if not custos:
                            ui.label("Cadastre custos variáveis abaixo.").classes("text-caption text-grey-7")

        def acao(fn, *args):
            try:
                with estado.sessao() as s:
                    fn(s, *args)
            except ErroValidacao as e:
                ui.notify(str(e), type="warning")
            painel_perfis.refresh()

        def novo_perfil(copiar=None):
            with ui.dialog() as dlg, ui.card().classes("w-96"):
                ui.label("Duplicar perfil " + copiar[1] if copiar else "Novo perfil de venda").classes("text-h6")
                nome = ui.input("Nome", value=f"{copiar[1]} (cópia)" if copiar else "").props("outlined autofocus")

                def ok():
                    try:
                        with estado.sessao() as s:
                            perfsvc.criar(s, nome.value, copiar_de=copiar[0] if copiar else None)
                    except ErroValidacao as e:
                        nome.props(f'error error-message="{e}"')
                        return
                    dlg.close()
                    painel_perfis.refresh()
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancelar", on_click=dlg.close).props("flat")
                    ui.button("Criar", on_click=ok)
            dlg.open()

        def renomear(pid, atual):
            with ui.dialog() as dlg, ui.card().classes("w-96"):
                nome = ui.input("Novo nome", value=atual).props("outlined autofocus")

                def ok():
                    try:
                        with estado.sessao() as s:
                            perfsvc.renomear(s, pid, nome.value)
                    except ErroValidacao as e:
                        nome.props(f'error error-message="{e}"')
                        return
                    dlg.close()
                    painel_perfis.refresh()
                with ui.row().classes("w-full justify-end"):
                    ui.button("Cancelar", on_click=dlg.close).props("flat")
                    ui.button("Salvar", on_click=ok)
            dlg.open()

        with ui.card().classes("w-full"):
            painel_perfis()
        TelaCadastro("custos_variaveis", ao_mudar=painel_perfis.refresh,
                     descricao="Impostos, taxas de cartão, comissões, marketplace e frete. Tipo percentual incide "
                               "sobre o preço de venda; valor_fixo é R$ por unidade vendida.").render()


# ============================================================================ grupos e subgrupos
def pagina_grupos():
    with moldura("Grupos e subgrupos", "/grupos"):
        subs = TelaCadastro("subgrupos", descricao="Subgrupo: código único dentro do grupo (ex.: Canvas 60x90).")
        with ui.row().classes("w-full gap-4 items-start no-wrap"):
            with ui.column().classes("w-2/5"):
                ui.label("Grupos").classes("text-subtitle1 text-weight-medium")
                TelaCadastro("grupos", ao_mudar=lambda: subs.atualizar(),
                             descricao="Primeiro nível da classificação (ex.: Quadros).").render()
            with ui.column().classes("w-3/5"):
                ui.label("Subgrupos").classes("text-subtitle1 text-weight-medium")
                subs.render()


# ============================================================================ configuração
def pagina_configuracao():
    with moldura("Configuração de precificação", "/configuracao"):
        with estado.sessao() as s:
            c = configuracao(s)
            r = regras_empresa(s)
            auto_horas = s.scalar(select(func.sum(MaoDeObra.qtd_colaboradores * MaoDeObra.horas_produtivas_mes))
                                  .where(MaoDeObra.ativo, MaoDeObra.horas_produtivas_mes.is_not(None)))
            vals = dict(metodo_rateio=c.metodo_rateio, faturamento_base_mensal=c.faturamento_base_mensal,
                        capacidade_horas_mes=c.capacidade_horas_mes, capacidade_unidades_mes=c.capacidade_unidades_mes,
                        margem_padrao_pct=c.margem_padrao_pct, modo_perda=c.modo_perda)
        with ui.card().classes("w-full max-w-3xl"):
            ui.label("Rateio do custo fixo").classes("text-subtitle1 text-weight-medium")
            ui.label(f"Custo fixo total mensal: {brl(r.custo_fixo_total)}").classes("text-caption text-grey-7")
            metodo = ui.radio(cfgsvc.ROTULOS_RATEIO, value=vals["metodo_rateio"]).props("dense").mark("metodo")
            with ui.grid(columns=3).classes("w-full gap-4"):
                fat = ui.number("Faturamento base mensal (R$)", value=vals["faturamento_base_mensal"]) \
                    .props("outlined dense clearable").mark("faturamento")
                horas = ui.number("Capacidade de horas/mês", value=vals["capacidade_horas_mes"]) \
                    .props(f'outlined dense clearable hint="vazio = soma das etapas ({num(auto_horas, 1) or "0"} h)"')
                unid = ui.number("Capacidade de unidades/mês", value=vals["capacidade_unidades_mes"]) \
                    .props("outlined dense clearable")
            ui.separator()
            ui.label("Margem e perda").classes("text-subtitle1 text-weight-medium")
            margem = ui.number("Margem de lucro padrão (%)", value=vals["margem_padrao_pct"], min=0, max=99.99) \
                .props('outlined dense hint="usada nos produtos sem margem própria"').classes("w-64").mark("margem")
            perda = ui.radio(cfgsvc.ROTULOS_PERDA, value=vals["modo_perda"]).props("dense")
            ui.label("Com 10 % de perda: sobre o material comprado = fator 1,111; acréscimo = fator 1,100.") \
                .classes("text-caption text-grey-7")
            controles = {"metodo_rateio": metodo, "faturamento_base_mensal": fat, "capacidade_horas_mes": horas,
                         "capacidade_unidades_mes": unid, "margem_padrao_pct": margem, "modo_perda": perda}

            def salvar():
                for el in controles.values():
                    el.props(remove="error error-message")
                try:
                    with estado.sessao() as s:
                        cfgsvc.salvar(s, {k: el.value for k, el in controles.items()})
                except ErroValidacao as e:
                    for campo, msg in e.erros:
                        controles[campo].props(f'error error-message="{msg}"')
                    ui.notify("Corrija os campos destacados.", type="negative")
                    return
                ui.notify("Configuração salva. Os preços de todos os produtos usam os novos parâmetros.",
                          type="positive")
            with ui.row().classes("w-full justify-end"):
                ui.button("Salvar", icon="save", on_click=salvar).mark("salvar-config")


# ============================================================================ registro
ROTAS = {
    "/": pagina_inicio,
    "/materias-primas": pagina_materias_primas,
    "/mao-de-obra": pagina_mao_de_obra,
    "/custos-fixos": pagina_custos_fixos,
    "/custos-variaveis": pagina_custos_variaveis,
    "/grupos": pagina_grupos,
    "/unidades": pagina_unidades,
    "/fornecedores": pagina_fornecedores,
    "/configuracao": pagina_configuracao,
}


def registrar() -> None:
    for rota, fn in ROTAS.items():
        ui.page(rota, title="Litoarte")(fn)
