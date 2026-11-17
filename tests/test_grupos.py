"""Grupos e subgrupos de produtos: cadastro, importação, migração e análise."""

import io
import sqlite3

import pandas as pd
import pytest

from custos import MotorCustos, Repositorio
from custos.exemplo import dados_exemplo
from custos.importexport import exportar_xlsx, ler_csv, ler_xlsx


@pytest.fixture
def repo(tmp_path):
    r = Repositorio(tmp_path / "g.db")
    d, p = dados_exemplo()
    r.importar(d, "substituir")
    r.salvar_parametros(p)
    return r


def test_produto_sem_grupo_recebe_padrao(repo):
    repo.mesclar("produtos", pd.DataFrame([{"codigo": "N1", "descricao": "Novo"}]))
    p = repo.carregar("produtos").set_index("codigo")
    assert (p.loc["N1", "grupo"], p.loc["N1", "subgrupo"]) == ("Sem grupo", "Geral")
    assert (repo.carregar("grupos")[["grupo", "subgrupo"]] == ["Sem grupo", "Geral"]).all(axis=1).any()


def test_importacao_csv_cria_grupos_e_unifica_grafia(repo):
    csv = ("SKU;Produto;Família;Subcategoria;Preço Venda\n"
           "X1;Balcão pia;cozinha;Balcões;899,00\n"
           "X2;Torre forno; COZINHA ;balcões;1.290,00\n"
           "X3;Cadeira;Escritório;Cadeiras;350\n").encode("latin-1")
    avisos = repo.mesclar("produtos", ler_csv(io.BytesIO(csv), "produtos"))
    p = repo.carregar("produtos").set_index("codigo")
    # 'cozinha' e ' COZINHA ' -> grafia já cadastrada 'Cozinha'; 'balcões' -> primeira grafia 'Balcões'
    assert p.loc["X1", "grupo"] == p.loc["X2", "grupo"] == "Cozinha"
    assert p.loc["X1", "subgrupo"] == p.loc["X2", "subgrupo"] == "Balcões"
    g = set(map(tuple, repo.carregar("grupos")[["grupo", "subgrupo"]].values))
    assert {("Cozinha", "Balcões"), ("Escritório", "Cadeiras")} <= g
    assert any("incluídos no cadastro" in a for a in avisos)


def test_grupo_em_uso_nao_e_excluido(repo):
    repo.salvar("grupos", repo.carregar("grupos").iloc[0:0])
    assert len(repo.carregar("grupos")) == 3          # recriados a partir dos produtos
    assert len(repo.carregar("produtos")) == 3        # nenhum produto perdido


def test_renomear_grupo_e_subgrupo(repo):
    assert repo.renomear_grupo("Cozinha", "Cozinhas planejadas") == 1
    assert repo.carregar("produtos").set_index("codigo").loc["P001", "grupo"] == "Cozinhas planejadas"
    assert "Cozinha" not in set(repo.carregar("grupos")["grupo"])
    repo.renomear_grupo("Escritório", "Escritório", "Gaveteiros", "Arquivos")
    assert repo.carregar("produtos").set_index("codigo").loc["P002", "subgrupo"] == "Arquivos"


def test_resumo_por_grupo_fecha_com_total(repo):
    m = MotorCustos(repo.carregar_tudo(), repo.parametros())
    rg = m.resumo_por_grupo("grupo")
    r = m.resumo()
    assert rg["faturamento"].sum() == pytest.approx(r.faturamento_projetado)
    assert rg["margem_contribuicao"].sum() == pytest.approx(r.margem_contribuicao_total)
    assert rg["participacao_pct"].sum() == pytest.approx(100)
    assert set(rg["grupo"]) == {"Cozinha", "Escritório", "Decoração"}


def test_xlsx_exporta_e_reimporta_grupos(repo, tmp_path):
    conteudo = exportar_xlsx(repo.carregar_tudo(), repo.parametros())
    abas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None)
    assert {"grupos", "resumo_grupos"} <= set(abas)
    assert {"Grupo", "Subgrupo"} <= set(abas["precos"].columns)
    novo = Repositorio(tmp_path / "n.db")
    novo.importar(ler_xlsx(io.BytesIO(conteudo)), "substituir")
    assert novo.carregar("produtos")[["grupo", "subgrupo"]].equals(repo.carregar("produtos")[["grupo", "subgrupo"]])


def test_migracao_de_banco_antigo(tmp_path):
    """Banco da versão anterior (produtos sem grupo) abre, migra e continua gravando."""
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE produtos ("codigo" TEXT, "descricao" TEXT, "unidade" TEXT, '
                '"margem_desejada_pct" REAL, "volume_mensal" REAL, "preco_atual" REAL, PRIMARY KEY ("codigo"))')
    con.execute("INSERT INTO produtos VALUES ('A1', 'Antigo', 'un', NULL, 10, 99.9)")
    con.commit()
    con.close()
    r = Repositorio(db)
    p = r.carregar("produtos")
    assert p.loc[0, "grupo"] == "Sem grupo" and p.loc[0, "preco_atual"] == pytest.approx(99.9)
    r.mesclar("produtos", pd.DataFrame([{"codigo": "A2", "descricao": "Novo", "grupo": "G", "subgrupo": "S"}]))
    p = r.carregar("produtos").set_index("codigo")
    assert p.loc["A1", "volume_mensal"] == 10 and p.loc["A2", "grupo"] == "G"
