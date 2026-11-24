"""Composição por subgrupo e custeio pelas dimensões do produto."""

import io
import sqlite3

import pandas as pd
import pytest

from custos import MotorCustos, Repositorio
from custos.dimensoes import pecas_por_folha
from custos.exemplo import dados_exemplo
from custos.importexport import exportar_xlsx, ler_xlsx


@pytest.fixture
def repo(tmp_path):
    r = Repositorio(tmp_path / "d.db")
    d, p = dados_exemplo()
    r.importar(d, "substituir")
    r.salvar_parametros(p)
    return r


def motor(repo):
    return MotorCustos(repo.carregar_tudo(), repo.parametros())


def linhas(repo, produto):
    return motor(repo).detalhar(produto)["materias_primas"].set_index("mp_codigo")


# ------------------------------------------------------------ encaixe na folha
@pytest.mark.parametrize("args,pecas", [
    ((100, 200, 15, 15), 78),            # exemplo: 6 × 13
    ((100, 200, 15, 15, 1.0), 72),       # 1 cm entre peças: 6 × 12
    ((100, 200, 15, 15, 0, 3.0), 72),    # 3 cm de margem: útil 94 × 194 -> 6 × 12
    ((100, 200, 15, 20), 65),            # melhor girada: 5 × 13
    ((100, 200, 20, 30), 33),            # 5 × 6 + 3 giradas na sobra
    ((100, 200, 120, 10), 10),           # só cabe girada
    ((100, 200, 120, 250), 0),           # não cabe
])
def test_pecas_por_folha(args, pecas):
    assert pecas_por_folha(*args).pecas == pecas


def test_aproveitamento_do_exemplo():
    e = pecas_por_folha(100, 200, 15, 15)
    assert e.aproveitamento_pct == pytest.approx(87.75)
    assert e.disposicao == "6 × 13"


# ------------------------------------------------------------ custo do recorte
def test_custo_recorte_15x15_calculado_a_mao(repo):
    li = linhas(repo, "P101")
    assert li.loc["PAP01", "pecas_folha"] == 78
    assert li.loc["PAP01", "custo"] == pytest.approx(18.00 / 78 * 1.05)      # papel
    assert li.loc["IMP01", "custo"] == pytest.approx(60.00 / 78 * 1.05)      # impressão por folha
    assert li.loc["CRT01", "custo"] == pytest.approx(0.60 * 0.15)            # corte: perímetro 0,6 m
    assert li.loc["EMB01", "custo"] == pytest.approx(0.12 * 1.02)            # embalagem
    assert (li["origem"] == "subgrupo").all()
    mo = motor(repo).detalhar("P101")["mao_de_obra"].iloc[0]
    assert mo["custo"] == pytest.approx(0.005 * 1900 * 1.7 / 160)


def test_mesma_ficha_tamanhos_diferentes(repo):
    t = motor(repo).tabela_precos().set_index("codigo")
    li = linhas(repo, "P103")                                                 # 20 × 30
    assert li.loc["PAP01", "pecas_folha"] == 33
    assert li.loc["CRT01", "consumo"] == pytest.approx(1.0)                   # 2·(0,2+0,3)
    assert t.loc["P102", "custo_mp"] < t.loc["P101", "custo_mp"] < t.loc["P103", "custo_mp"]


def test_produto_substitui_e_exclui_item_do_subgrupo(repo):
    repo.mesclar("composicao", pd.DataFrame([
        {"produto_codigo": "P101", "mp_codigo": "PAP01", "base": "aproveitamento", "quantidade": 1,
         "perda_pct": 10.0, "espacamento_cm": 1.0},                           # substitui: perda e espaço próprios
        {"produto_codigo": "P101", "mp_codigo": "EMB01", "quantidade": 0},    # exclui a embalagem herdada
    ]))
    li = linhas(repo, "P101")
    assert li.loc["PAP01", "origem"] == "produto"
    assert li.loc["PAP01", "pecas_folha"] == 72
    assert li.loc["PAP01", "custo"] == pytest.approx(18.00 / 72 * 1.10)
    assert "EMB01" not in li.index
    assert li.loc["IMP01", "origem"] == "subgrupo"
    assert "PAP01" in linhas(repo, "P102").index and linhas(repo, "P102").loc["PAP01", "origem"] == "subgrupo"


def test_base_area_e_mo_por_area(repo):
    repo.mesclar("materias_primas", pd.DataFrame([{"codigo": "IMP02", "descricao": "Impressão m²",
                                                   "unidade": "m²", "custo_unitario": 40.0}]))
    repo.mesclar("composicao", pd.DataFrame([{"produto_codigo": "P101", "mp_codigo": "IMP02",
                                              "base": "m²", "quantidade": 2}]))          # frente e verso
    repo.mesclar("produto_mao_de_obra", pd.DataFrame([{"produto_codigo": "P101", "mo_codigo": "MO03",
                                                      "base": "area", "horas": 0.4}]))  # 0,4 h por m²
    li = linhas(repo, "P101")
    assert li.loc["IMP02", "custo"] == pytest.approx(0.0225 * 2 * 40.0)
    mo = motor(repo).detalhar("P101")["mao_de_obra"].set_index("mo_codigo")
    assert mo.loc["MO03", "horas_efetivas"] == pytest.approx(0.4 * 0.0225)
    assert mo.loc["MO03", "origem"] == "produto"


def test_produto_sem_dimensoes_gera_alerta(repo):
    repo.mesclar("produtos", pd.DataFrame([{"codigo": "P199", "descricao": "Recorte sem medida",
                                            "grupo_codigo": "04", "subgrupo_codigo": "01"}]))
    t = motor(repo).tabela_precos().set_index("codigo")
    assert "produto sem dimensões" in t.loc["P199", "alertas"]
    assert t.loc["P199", "custo_mp"] == pytest.approx(0.12 * 1.02)            # só a embalagem (unidade)


def test_peca_maior_que_folha_alerta(repo):
    repo.mesclar("produtos", pd.DataFrame([{"codigo": "P198", "descricao": "Painel", "grupo_codigo": "04",
                                            "subgrupo_codigo": "01", "largura_cm": 120, "altura_cm": 250}]))
    assert "não cabe na folha" in motor(repo).tabela_precos().set_index("codigo").loc["P198", "alertas"]


def test_base_invalida_rejeitada(repo):
    erros = repo.mesclar("mo_subgrupo", pd.DataFrame([{"grupo_codigo": "04", "subgrupo_codigo": "01",
                                                       "mo_codigo": "MO01", "base": "aproveitamento",
                                                       "horas": 1}]))
    assert any("inválida" in e for e in erros)


def test_alterar_codigo_leva_a_ficha_do_subgrupo(repo):
    repo.alterar_codigo_subgrupo("04", "01", "RC")
    repo.alterar_codigo_grupo("04", "PAPEL")
    f = repo.carregar("composicao_subgrupo")
    assert set(zip(f["grupo_codigo"], f["subgrupo_codigo"])) == {("PAPEL", "RC")}
    assert linhas(repo, "P101").loc["PAP01", "pecas_folha"] == 78


def test_xlsx_com_fichas_de_subgrupo(repo, tmp_path):
    conteudo = exportar_xlsx(repo.carregar_tudo(), repo.parametros())
    novo = Repositorio(tmp_path / "n.db")
    assert novo.importar(ler_xlsx(io.BytesIO(conteudo)), "substituir") == []
    assert len(novo.carregar("composicao_subgrupo")) == 4
    assert linhas(novo, "P101").loc["IMP01", "custo"] == pytest.approx(60 / 78 * 1.05)


def test_migracao_ficha_antiga_vira_base_unidade(tmp_path):
    db = tmp_path / "v.db"
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE composicao ("produto_codigo" TEXT, "mp_codigo" TEXT, "quantidade" REAL, '
                '"perda_pct" REAL, PRIMARY KEY ("produto_codigo", "mp_codigo"))')
    con.commit()
    con.close()
    r = Repositorio(db)
    r.mesclar("materias_primas", pd.DataFrame([{"codigo": "M", "descricao": "m", "custo_unitario": 2}]))
    r.mesclar("produtos", pd.DataFrame([{"codigo": "A", "descricao": "a"}]))
    r.mesclar("composicao", pd.DataFrame([{"produto_codigo": "A", "mp_codigo": "M", "quantidade": 3}]))
    assert r.carregar("composicao").loc[0, "base"] == "unidade"
    assert motor(r).tabela_precos().loc[0, "custo_mp"] == pytest.approx(6)
