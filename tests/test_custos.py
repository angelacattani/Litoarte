"""Testes do motor de preço, validação, repositório e import/export."""

import io

import pandas as pd
import pytest

from custos import MotorCustos, Repositorio
from custos.exemplo import dados_exemplo
from custos.importexport import exportar_csv, exportar_xlsx, ler_csv, ler_parametros_xlsx, ler_xlsx, planilha_modelo
from custos.validacao import para_numero, validar


@pytest.fixture
def base():
    dados, params = dados_exemplo()
    return {t: validar(df, t)[0] for t, df in dados.items()}, params


@pytest.fixture
def repo(tmp_path, base):
    r = Repositorio(tmp_path / "t.db")
    r.importar(base[0], modo="substituir")
    r.salvar_parametros(base[1])
    return r


# ---------------------------------------------------------------- cálculo
def test_preco_markup_divisor_calculado_a_mao(base):
    dados, p = base
    linha = MotorCustos(dados, p).tabela_precos().set_index("codigo").loc["P001"]
    mp = 2.4 * 1.12 * 62 + 4 * 4.5 + 9 * 1.10 * 0.90 + 2 * 12 + 8
    mo = 2.0 * (3200 * 1.7 / 160) + 0.5 * (2200 * 1.7 / 160)
    cd = mp + mo + 15
    pct_fix = 100 * 10600 / 75000
    preco = cd / (1 - (16 + pct_fix + 15) / 100)
    assert linha["custo_mp"] == pytest.approx(mp)
    assert linha["custo_mo"] == pytest.approx(mo)
    assert linha["preco_sugerido"] == pytest.approx(preco)
    # no preço sugerido, a margem obtida deve ser exatamente a desejada
    m = MotorCustos(dados, p)
    assert m.simular("P001", preco)["margem_liquida_pct"] == pytest.approx(15.0)


def test_margem_padrao_aplicada_quando_vazia(base):
    dados, p = base
    t = MotorCustos(dados, p).tabela_precos().set_index("codigo")
    assert t.loc["P002", "margem_pct"] == p["margem_padrao_pct"]


@pytest.mark.parametrize("metodo", ["por_hora_mo", "por_unidade"])
def test_rateio_absorve_todos_os_fixos(base, metodo):
    dados, p = base
    t = MotorCustos(dados, {**p, "metodo_rateio": metodo}).tabela_precos()
    assert (t["custo_fixo_unit"] * t["volume_mensal"]).sum() == pytest.approx(10600)
    assert (t["pct_fixos"] == 0).all()


def test_preco_minimo_tem_lucro_zero(base):
    dados, p = base
    m = MotorCustos(dados, p)
    t = m.tabela_precos().set_index("codigo")
    for cod in t.index:
        assert m.simular(cod, t.loc[cod, "preco_minimo"])["margem_liquida_pct"] == pytest.approx(0, abs=1e-9)


def test_soma_de_percentuais_acima_de_100_gera_alerta(base):
    dados, p = base
    dados = {**dados, "produtos": dados["produtos"].assign(margem_desejada_pct=80.0)}
    t = MotorCustos(dados, p).tabela_precos()
    assert t["preco_sugerido"].isna().all()
    assert t["alertas"].str.contains("preço indefinido").all()


def test_concorrencia(base):
    dados, p = base
    t = MotorCustos(dados, p).tabela_precos().set_index("codigo")
    assert t.loc["P001", "conc_media"] == pytest.approx(567.0)
    assert t.loc["P001", "conc_n"] == 2
    assert t.loc["P003", "posicao_mercado"] == "acima"


def test_resumo_lucro_consistente(base):
    dados, p = base
    m = MotorCustos(dados, {**p, "metodo_rateio": "por_hora_mo"})
    r = m.resumo()
    t = m.tabela_precos()
    lucro_unitario = (t["lucro_unit"] * t["volume_mensal"]).sum()
    # com rateio por hora prevista, lucro = Σ lucro unitário − ociosidade de MO
    assert r.lucro_projetado == pytest.approx(lucro_unitario - r.ociosidade_mo)


def test_sem_faturamento_previsto_alerta(base):
    dados, p = base
    m = MotorCustos(dados, {**p, "faturamento_mensal_previsto": 0})
    assert m.pct_fix == 0
    assert any("Faturamento" in a for a in m.alertas_gerais)


# ---------------------------------------------------------------- validação
@pytest.mark.parametrize("entrada,esperado", [
    ("1.234,56", 1234.56), ("R$ 12,90", 12.9), ("18%", 18.0), ("3.5", 3.5), (7, 7.0)])
def test_para_numero(entrada, esperado):
    assert para_numero(entrada) == pytest.approx(esperado)


def test_validacao_aliases_e_erros():
    bruto = pd.DataFrame({"Código": ["A", "B", "", "A"], "Nome": ["x", "y", "z", "x2"],
                          "Custo (R$)": ["10,50", "-1", "3", "11"]})
    df, erros = validar(bruto, "materias_primas")
    assert list(df["codigo"]) == ["A"]
    assert df.loc[0, "custo_unitario"] == 11.0  # duplicata: mantém a última
    assert any("menor que 0" in e for e in erros)
    assert any("obrigatório" in e for e in erros)
    assert any("duplicadas" in e for e in erros)


# ---------------------------------------------------------------- repositório
def test_repositorio_roundtrip(repo, base):
    dados, p = base
    assert len(repo.carregar("produtos")) == 3
    assert repo.parametros()["faturamento_mensal_previsto"] == 75000.0
    t1 = MotorCustos(dados, p).tabela_precos()["preco_sugerido"]
    t2 = MotorCustos(repo.carregar_tudo(), repo.parametros()).tabela_precos()["preco_sugerido"]
    assert t1.tolist() == pytest.approx(t2.tolist())


def test_mesclar_faz_upsert(repo):
    novos = pd.DataFrame([{"codigo": "P001", "descricao": "Armário NOVO", "volume_mensal": 5},
                          {"codigo": "P900", "descricao": "Produto novo"}])
    repo.mesclar("produtos", novos)
    prod = repo.carregar("produtos").set_index("codigo")
    assert len(prod) == 4
    assert prod.loc["P001", "descricao"] == "Armário NOVO"
    assert len(repo.carregar("composicao")) == 11  # ficha técnica preservada


def test_referencia_orfa_e_descartada(repo):
    erros = repo.salvar("composicao", pd.DataFrame([{"produto_codigo": "P001", "mp_codigo": "XXX", "quantidade": 1}]))
    assert repo.carregar("composicao").empty
    assert any("XXX" in e for e in erros)


def test_excluir_produto_remove_ficha(repo):
    prod = repo.carregar("produtos")
    repo.salvar("produtos", prod[prod["codigo"] != "P003"])
    repo.importar({}, modo="mesclar")  # revalida integridade
    assert "P003" not in set(repo.carregar("composicao")["produto_codigo"])


# ---------------------------------------------------------------- import/export
def test_xlsx_roundtrip(tmp_path, repo):
    dados, params = repo.carregar_tudo(), repo.parametros()
    conteudo = exportar_xlsx(dados, params)
    lidos = ler_xlsx(io.BytesIO(conteudo))
    assert set(lidos) == set(dados)  # abas 'precos'/'resumo' ignoradas
    r2 = Repositorio(tmp_path / "novo.db")
    assert r2.importar(lidos, modo="substituir") == []
    r2.salvar_parametros(ler_parametros_xlsx(io.BytesIO(conteudo)))
    a = MotorCustos(dados, params).tabela_precos()["preco_sugerido"]
    b = MotorCustos(r2.carregar_tudo(), r2.parametros()).tabela_precos()["preco_sugerido"]
    assert a.tolist() == pytest.approx(b.tolist())


def test_csv_formato_brasileiro(repo):
    csv = exportar_csv(repo.carregar("materias_primas"))
    assert csv.startswith(b"\xef\xbb\xbf") and b";" in csv and b"62,0000" in csv
    df, erros = validar(ler_csv(io.BytesIO(csv), "materias_primas"), "materias_primas")
    assert not erros and df["custo_unitario"].iloc[0] == 62.0


def test_importa_csv_de_produtos_legado():
    csv = "SKU;Produto;Preço Venda;Vendas mês\nX1;Mesa;1.299,90;12\nX2;Cadeira;349,00;40\n".encode("latin-1")
    df, erros = validar(ler_csv(io.BytesIO(csv), "produtos"), "produtos")
    assert not erros
    assert df.set_index("codigo").loc["X1", "preco_atual"] == pytest.approx(1299.90)
    assert df.set_index("codigo").loc["X2", "volume_mensal"] == 40


def test_planilha_modelo():
    abas = pd.read_excel(io.BytesIO(planilha_modelo()), sheet_name=None)
    assert "instrucoes" in abas and "produtos" in abas
