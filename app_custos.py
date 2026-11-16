"""Interface Streamlit do sistema de custos e formação de preço.

Execução:  streamlit run app_custos.py
Banco:     custos.db (SQLite) na pasta do app, ou caminho em CUSTOS_DB.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from custos import ESQUEMAS, METODOS_RATEIO, ORDEM_TABELAS, MotorCustos, Repositorio
from custos.calculo import brl
from custos.exemplo import dados_exemplo
from custos.importexport import (COLUNAS_RELATORIO, exportar_csv, exportar_xlsx, ler_csv,
                                 ler_parametros_xlsx, ler_xlsx, planilha_modelo, relatorio_precos)

st.set_page_config(page_title="Custos e Preço de Venda", page_icon="💲", layout="wide")

DB = os.environ.get("CUSTOS_DB", str(Path(__file__).with_name("custos.db")))


@st.cache_resource
def repositorio() -> Repositorio:
    return Repositorio(DB)


repo = repositorio()


def motor() -> MotorCustos:
    return MotorCustos(repo.carregar_tudo(), repo.parametros())


def mostrar_avisos(avisos: list[str], sucesso: str = "Dados salvos.") -> None:
    if avisos:
        st.warning("Salvo com ressalvas:\n\n" + "\n".join(f"- {a}" for a in avisos))
    else:
        st.success(sucesso)


def pct(v) -> str:
    return "—" if pd.isna(v) else f"{v:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")


# Configuração de colunas do data_editor por tipo lógico
def config_colunas(tabela: str, opcoes: dict[str, list[str]] | None = None) -> dict:
    cfg = {}
    for c in ESQUEMAS[tabela].colunas:
        rotulo = c.nome.replace("_", " ").capitalize() + (" *" if c.obrigatoria else "")
        if opcoes and c.nome in opcoes:
            cfg[c.nome] = st.column_config.SelectboxColumn(rotulo, options=opcoes[c.nome], required=c.obrigatoria, help=c.descricao)
        elif c.tipo == "real":
            fmt = "%.2f %%" if c.nome.endswith("_pct") else "%.4f"
            cfg[c.nome] = st.column_config.NumberColumn(rotulo, min_value=c.minimo, format=fmt, help=c.descricao)
        elif c.tipo == "inteiro":
            cfg[c.nome] = st.column_config.NumberColumn(rotulo, min_value=0, step=1, help=c.descricao)
        elif c.tipo == "data":
            cfg[c.nome] = st.column_config.DateColumn(rotulo, format="DD/MM/YYYY", help=c.descricao)
        else:
            cfg[c.nome] = st.column_config.TextColumn(rotulo, required=c.obrigatoria, help=c.descricao)
    return cfg


def editor_tabela(tabela: str, ajuda: str = "", opcoes: dict | None = None) -> None:
    esq = ESQUEMAS[tabela]
    st.header(esq.titulo)
    if ajuda:
        st.caption(ajuda)
    df = repo.carregar(tabela)
    if "data_coleta" in df:
        df["data_coleta"] = pd.to_datetime(df["data_coleta"]).dt.date
    editado = st.data_editor(df, num_rows="dynamic", width="stretch", hide_index=True,
                             column_config=config_colunas(tabela, opcoes), key=f"ed_{tabela}")
    c1, c2, _ = st.columns([1, 1, 4])
    if c1.button("💾 Salvar", key=f"salvar_{tabela}", type="primary"):
        mostrar_avisos(repo.salvar(tabela, editado))
    c2.download_button("⬇ CSV", exportar_csv(repo.carregar(tabela)), f"{tabela}.csv", "text/csv",
                       key=f"csv_{tabela}")


# --------------------------------------------------------------------- páginas
def pagina_painel() -> None:
    st.header("Painel de preços")
    m = motor()
    tab = m.tabela_precos()
    if tab.empty:
        st.info("Nenhum produto cadastrado. Cadastre em **Produtos** ou importe uma planilha em **Importar / Exportar**. "
                "Para conhecer o sistema, carregue a base de exemplo em **Parâmetros**.")
        return

    escolha = st.radio("Projetar resultado com:", ["preço sugerido", "preço atual"], horizontal=True)
    r = m.resumo("preco_sugerido" if escolha == "preço sugerido" else "preco_atual")

    k = st.columns(5)
    k[0].metric("Faturamento projetado", brl(r.faturamento_projetado))
    k[1].metric("Margem de contribuição", brl(r.margem_contribuicao_total))
    k[2].metric("Custos fixos + ociosidade", brl(r.total_fixos + r.ociosidade_mo))
    k[3].metric("Lucro projetado", brl(r.lucro_projetado), pct(r.margem_liquida_projetada_pct))
    k[4].metric("Ponto de equilíbrio", brl(r.ponto_equilibrio_faturamento))
    for a in r.alertas:
        st.warning(a)

    st.subheader("Formação de preço por produto")
    st.caption(f"Variáveis: {pct(m.pct_var)} do preço + {brl(m.var_unit)}/un · "
               f"Fixos: {METODOS_RATEIO[m.p['metodo_rateio']]}"
               + (f" = {pct(m.pct_fix)}" if m.pct_fix else (f" = {brl(m.taxa_rateio)}" if m.taxa_rateio else "")))
    cols = ["codigo", "descricao", "custo_mp", "custo_mo", "custo_var_unit", "custo_fixo_unit", "custo_total",
            "margem_pct", "markup_multiplicador", "preco_sugerido", "preco_minimo", "preco_atual",
            "margem_preco_atual_pct", "conc_media", "dif_vs_conc_media_pct", "posicao_mercado",
            "margem_no_preco_conc_pct", "alertas"]
    moeda = {c: st.column_config.NumberColumn(COLUNAS_RELATORIO[c], format="R$ %.2f") for c in
             ["custo_mp", "custo_mo", "custo_var_unit", "custo_fixo_unit", "custo_total", "preco_sugerido",
              "preco_minimo", "preco_atual", "conc_media"]}
    percent = {c: st.column_config.NumberColumn(COLUNAS_RELATORIO[c], format="%.1f %%") for c in
               ["margem_pct", "margem_preco_atual_pct", "dif_vs_conc_media_pct", "margem_no_preco_conc_pct"]}
    st.dataframe(tab[cols], hide_index=True, width="stretch",
                 column_config={**moeda, **percent,
                                "markup_multiplicador": st.column_config.NumberColumn("Markup (×)", format="%.3f"),
                                "codigo": "Código", "descricao": "Descrição", "posicao_mercado": "Posição",
                                "alertas": "Alertas"})

    st.subheader("Preço sugerido × concorrência")
    graf = tab.set_index("descricao")[["preco_minimo", "preco_sugerido", "preco_atual", "conc_media"]]
    graf.columns = ["Mínimo (lucro zero)", "Sugerido", "Atual", "Média concorrência"]
    st.bar_chart(graf, stack=False, height=340)

    with st.expander("Ocupação da mão de obra direta"):
        oc = r.ocupacao_mo.rename(columns={"codigo": "Código", "funcao": "Função", "quantidade": "Qtd.",
                                           "capacidade_horas": "Capacidade (h/mês)", "custo_hora": "Custo-hora (R$)",
                                           "custo_mensal_total": "Custo mensal (R$)",
                                           "horas_previstas": "Horas previstas", "ocupacao_pct": "Ocupação %"})
        st.dataframe(oc.round(2), hide_index=True, width="stretch")


def pagina_ficha() -> None:
    st.header("Ficha de custos e simulador")
    m = motor()
    tab = m.tabela_precos()
    if tab.empty:
        st.info("Cadastre produtos primeiro.")
        return
    rotulos = dict(zip(tab["codigo"], tab["codigo"] + " — " + tab["descricao"]))
    cod = st.selectbox("Produto", list(rotulos), format_func=rotulos.get)
    d = m.detalhar(cod)
    r = d["resultado"]

    c1, c2 = st.columns([3, 2])
    with c1:
        st.markdown("**Matérias-primas**")
        st.dataframe(d["materias_primas"].round(4), hide_index=True, width="stretch")
        st.markdown("**Mão de obra**")
        st.dataframe(d["mao_de_obra"].round(4), hide_index=True, width="stretch")
    with c2:
        st.markdown("**Composição do preço sugerido**")
        p = r["preco_sugerido"]
        linhas = [
            ("Matéria-prima", r["custo_mp"]), ("Mão de obra", r["custo_mo"]),
            ("Variáveis unitários", r["custo_var_unit"]), ("Fixos rateados (R$/un)", r["custo_fixo_unit"]),
            ("Variáveis % (impostos, comissões...)", p * m.pct_var / 100 if pd.notna(p) else None),
            ("Fixos % do faturamento", p * m.pct_fix / 100 if pd.notna(p) else None),
            ("Lucro líquido", r["lucro_unit"]),
        ]
        comp = pd.DataFrame(linhas, columns=["Componente", "R$"])
        comp["% do preço"] = 100 * comp["R$"] / p if pd.notna(p) else None
        st.dataframe(comp.round(2), hide_index=True, width="stretch")
        st.metric("Preço sugerido", brl(p), f"markup {r['markup_multiplicador']:.3f}×" if pd.notna(p) else None)
        st.caption(f"Preço mínimo (lucro zero): **{brl(r['preco_minimo'])}** · "
                   f"Preço de cobertura (MC zero): **{brl(r['preco_cobertura'])}**")
        if r["alertas"]:
            st.error(r["alertas"])

    st.subheader("Simulador de preço")
    ref = [v for v in [r["preco_minimo"], r["preco_sugerido"], r["preco_atual"], r["conc_max"]] if pd.notna(v)]
    if not ref:
        return
    teto = max(ref) * 1.5
    preco = st.slider("Preço de venda (R$)", 0.01, float(round(teto, 2)),
                      float(round(r["preco_sugerido"] if pd.notna(r["preco_sugerido"]) else ref[0], 2)), step=0.5)
    s = m.simular(cod, preco)
    k = st.columns(4)
    k[0].metric("Margem líquida", pct(s["margem_liquida_pct"]))
    k[1].metric("Lucro por unidade", brl(s["lucro_unit"]))
    k[2].metric("Margem de contribuição", brl(s["margem_contribuicao_unit"]), pct(s["margem_contribuicao_pct"]))
    if pd.notna(r["conc_media"]):
        k[3].metric("vs. média da concorrência", brl(r["conc_media"]), pct(100 * (preco / r["conc_media"] - 1)),
                    delta_color="inverse")
    if not d["concorrentes"].empty:
        st.markdown("**Concorrentes**")
        st.dataframe(d["concorrentes"], hide_index=True, width="stretch")


def pagina_ficha_tecnica() -> None:
    st.header("Ficha técnica do produto")
    prod = repo.carregar("produtos")
    if prod.empty:
        st.info("Cadastre produtos primeiro.")
        return
    rotulos = dict(zip(prod["codigo"], prod["codigo"] + " — " + prod["descricao"]))
    cod = st.selectbox("Produto", list(rotulos), format_func=rotulos.get)
    mp = repo.carregar("materias_primas")
    mo = repo.carregar("mao_de_obra")

    for tabela, catalogo, col, rot in [("composicao", mp, "mp_codigo", "descricao"),
                                       ("produto_mao_de_obra", mo, "mo_codigo", "funcao")]:
        st.subheader(ESQUEMAS[tabela].titulo)
        tudo = repo.carregar(tabela)
        filtro = tudo[tudo["produto_codigo"] == cod].drop(columns="produto_codigo")
        st.caption("Disponíveis: " + ", ".join(catalogo["codigo"] + " = " + catalogo[rot]) if not catalogo.empty
                   else "Nenhum item cadastrado.")
        cfg = {k: v for k, v in config_colunas(tabela, {col: catalogo["codigo"].tolist()}).items()
               if k != "produto_codigo"}
        ed = st.data_editor(filtro, num_rows="dynamic", hide_index=True, width="stretch",
                            column_config=cfg, key=f"ft_{tabela}_{cod}")
        if st.button("💾 Salvar", key=f"sft_{tabela}_{cod}", type="primary"):
            novo = pd.concat([tudo[tudo["produto_codigo"] != cod], ed.assign(produto_codigo=cod)], ignore_index=True)
            mostrar_avisos(repo.salvar(tabela, novo))


def pagina_parametros() -> None:
    st.header("Parâmetros de precificação")
    p = repo.parametros()
    with st.form("parametros"):
        margem = st.number_input("Margem de lucro líquida padrão (%)", 0.0, 99.0, float(p["margem_padrao_pct"]), 0.5,
                                 help="Usada nos produtos sem margem própria.")
        metodos = list(METODOS_RATEIO)
        metodo = st.radio("Rateio dos custos fixos", metodos, metodos.index(p["metodo_rateio"]),
                          format_func=METODOS_RATEIO.get)
        fat = st.number_input("Faturamento mensal previsto (R$)", 0.0, value=float(p["faturamento_mensal_previsto"]),
                              step=1000.0, help="Necessário no método '% sobre o faturamento'.")
        tol = st.number_input("Tolerância para considerar 'alinhado' à concorrência (± %)", 0.0, 100.0,
                              float(p["tolerancia_concorrencia_pct"]), 0.5)
        if st.form_submit_button("💾 Salvar parâmetros", type="primary"):
            repo.salvar_parametros({"margem_padrao_pct": margem, "metodo_rateio": metodo,
                                    "faturamento_mensal_previsto": fat, "tolerancia_concorrencia_pct": tol})
            st.success("Parâmetros salvos.")

    st.markdown("""
**Fórmula** — markup divisor:  `Preço = (CD + CFu) / [1 − (%CV + %CF + %ML)/100]`

- **CD** custo direto (MP com perdas + MO + variáveis em R$/un) · **CFu** fixo rateado por unidade
- **%CV** variáveis sobre o preço · **%CF** fixos ÷ faturamento previsto · **%ML** margem líquida desejada

Não inclua em *custos fixos* os salários da mão de obra direta já cadastrada em *Mão de obra* — isso
duplicaria o custo. A parcela da folha não consumida pelos volumes previstos aparece como **ociosidade**.
""")

    st.divider()
    st.subheader("Base de dados")
    c1, c2 = st.columns(2)
    if c1.button("Carregar base de exemplo (substitui tudo)"):
        dados, params = dados_exemplo()
        repo.excluir_tudo()
        mostrar_avisos(repo.importar(dados, "substituir"), "Base de exemplo carregada.")
        repo.salvar_parametros(params)
    if c2.checkbox("Confirmo que desejo apagar todos os dados") and c2.button("🗑 Apagar tudo", type="secondary"):
        repo.excluir_tudo()
        st.success("Base apagada.")
    st.caption(f"Arquivo do banco: `{DB}`")


def pagina_io() -> None:
    st.header("Importar / Exportar")
    t1, t2 = st.tabs(["⬆ Importar", "⬇ Exportar"])
    with t1:
        st.markdown("**Planilha completa (XLSX)** — uma aba por tabela. Abas não reconhecidas são ignoradas, "
                    "então um arquivo exportado por este sistema pode ser reimportado.")
        st.download_button("Baixar planilha-modelo", planilha_modelo(), "modelo_importacao_custos.xlsx")
        modo = st.radio("Modo", ["mesclar", "substituir"], horizontal=True,
                        help="mesclar: insere novos e atualiza existentes pela chave. "
                             "substituir: as tabelas presentes no arquivo substituem as atuais.")
        arq = st.file_uploader("Arquivo XLSX", type=["xlsx"], key="up_xlsx")
        if arq is not None:
            try:
                lidos = ler_xlsx(arq)
                st.write({ESQUEMAS[t].titulo: f"{len(df)} linha(s)" for t, df in lidos.items()})
                params_arq = ler_parametros_xlsx(arq)
                usar_params = bool(params_arq) and st.checkbox("Importar também os parâmetros do arquivo", True)
                if st.button("Confirmar importação", type="primary", key="imp_xlsx"):
                    mostrar_avisos(repo.importar(lidos, modo), "Importação concluída.")
                    if usar_params:
                        repo.salvar_parametros(params_arq)
            except Exception as e:  # arquivo malformado
                st.error(f"Falha ao ler o arquivo: {e}")

        st.divider()
        st.markdown("**Tabela única (CSV)** — aceita `;` ou `,`, números como `1.234,56`, e nomes de coluna "
                    "usuais (ex.: *SKU*, *Produto*, *Preço Venda* para produtos).")
        tabela = st.selectbox("Tabela de destino", ORDEM_TABELAS, format_func=lambda t: ESQUEMAS[t].titulo)
        st.caption("Colunas: " + ", ".join(f"`{c.nome}`{'*' if c.obrigatoria else ''}" for c in ESQUEMAS[tabela].colunas))
        modo_csv = st.radio("Modo", ["mesclar", "substituir"], horizontal=True, key="modo_csv")
        arq_csv = st.file_uploader("Arquivo CSV", type=["csv", "txt"], key="up_csv")
        if arq_csv is not None:
            try:
                bruto = ler_csv(arq_csv, tabela)
                st.dataframe(bruto.head(20), width="stretch")
                if st.button("Confirmar importação", type="primary", key="imp_csv"):
                    mostrar_avisos(repo.importar({tabela: bruto}, modo_csv), "Importação concluída.")
            except Exception as e:
                st.error(f"Falha ao ler o arquivo: {e}")

    with t2:
        dados, params = repo.carregar_tudo(), repo.parametros()
        hoje = date.today().isoformat()
        st.download_button("📘 Base completa + relatório de preços (XLSX)", exportar_xlsx(dados, params),
                           f"custos_{hoje}.xlsx", type="primary")
        st.download_button("📄 Relatório de preços (CSV)", exportar_csv(relatorio_precos(MotorCustos(dados, params))),
                           f"precos_{hoje}.csv")
        tabela = st.selectbox("Exportar tabela individual (CSV)", ORDEM_TABELAS,
                              format_func=lambda t: ESQUEMAS[t].titulo, key="exp_tab")
        st.download_button("Baixar CSV", exportar_csv(dados[tabela]), f"{tabela}_{hoje}.csv")


# ----------------------------------------------------------------- navegação
PAGINAS = {
    "📊 Painel de preços": pagina_painel,
    "🧮 Ficha de custos / simulador": pagina_ficha,
    "📦 Produtos": lambda: editor_tabela("produtos", "Margem vazia = margem padrão. Volume mensal é usado em rateios, "
                                                     "ocupação de MO e projeção de resultado."),
    "🧾 Ficha técnica": pagina_ficha_tecnica,
    "🧱 Matérias-primas": lambda: editor_tabela("materias_primas", "Custo unitário de reposição, já com frete e "
                                                                  "impostos não recuperáveis."),
    "👷 Mão de obra": lambda: editor_tabela("mao_de_obra", "Custo-hora = salário × (1 + encargos%) ÷ horas produtivas."),
    "🏢 Custos fixos": lambda: editor_tabela("custos_fixos", "Valores mensais que não variam com o volume "
                                                            "(aluguel, pró-labore, administrativo, depreciação...)."),
    "📈 Custos variáveis": lambda: editor_tabela("custos_variaveis", "tipo = percentual (sobre o preço: impostos, "
                                                                    "comissão, cartão) ou unitario (R$/un: frete...).",
                                                {"tipo": ["percentual", "unitario"]}),
    "🏷 Concorrentes": lambda: editor_tabela("concorrentes", "Um preço por produto e concorrente.",
                                            {"produto_codigo": repo.carregar("produtos")["codigo"].tolist()}),
    "⚙ Parâmetros": pagina_parametros,
    "🔄 Importar / Exportar": pagina_io,
}

with st.sidebar:
    st.title("💲 Custos & Preço")
    pagina = st.radio("Navegação", list(PAGINAS), label_visibility="collapsed")

PAGINAS[pagina]()
