"""Grupos e subgrupos com código: cadastro, vínculo do produto, importação e migração."""

import io
import sqlite3

import pandas as pd
import pytest

from custos import MotorCustos, Repositorio
from custos.exemplo import dados_exemplo
from custos.importexport import exportar_xlsx, ler_csv, ler_xlsx
from custos.validacao import proximo_codigo


@pytest.fixture
def repo(tmp_path):
    r = Repositorio(tmp_path / "g.db")
    d, p = dados_exemplo()
    r.importar(d, "substituir")
    r.salvar_parametros(p)
    return r


def _prod(repo):
    return repo.carregar("produtos").set_index("codigo")


def test_vinculo_por_codigo_e_descricoes_no_calculo(repo):
    t = MotorCustos(repo.carregar_tudo(), repo.parametros()).tabela_precos().set_index("codigo")
    assert tuple(t.loc["P001", ["grupo_codigo", "grupo", "subgrupo_codigo", "subgrupo"]]) == \
        ("01", "Cozinha", "01", "Armários aéreos")
    # mesmo código de subgrupo (01) em grupos diferentes
    assert tuple(t.loc["P002", ["grupo_codigo", "subgrupo_codigo", "subgrupo"]]) == ("02", "01", "Gaveteiros")


def test_renomear_descricao_nao_mexe_no_produto(repo):
    g = repo.carregar("grupos")
    g.loc[g["codigo"] == "01", "descricao"] = "Cozinhas planejadas"
    repo.salvar("grupos", g)
    assert _prod(repo).loc["P001", "grupo_codigo"] == "01"
    t = MotorCustos(repo.carregar_tudo(), repo.parametros()).tabela_precos().set_index("codigo")
    assert t.loc["P001", "grupo"] == "Cozinhas planejadas"


def test_produto_sem_grupo_recebe_padrao(repo):
    repo.mesclar("produtos", pd.DataFrame([{"codigo": "N1", "descricao": "Novo"}]))
    assert tuple(_prod(repo).loc["N1", ["grupo_codigo", "subgrupo_codigo"]]) == ("00", "00")


def test_importa_por_codigo_inclusive_numerico_do_excel(repo):
    # Excel entrega códigos como número: 1001.0 -> "1001" e 1 -> casa com o "01" cadastrado
    df = pd.DataFrame([{"Código": "X1", "Produto": "Mesa", "Cód. Grupo": "02", "Cód. Subgrupo": "01"},
                       {"Código": 1001.0, "Produto": "Banco", "Cód. Grupo": 1.0, "Cód. Subgrupo": 2}])
    avisos = repo.mesclar("produtos", df)
    p = _prod(repo)
    assert tuple(p.loc["X1", ["grupo_codigo", "subgrupo_codigo"]]) == ("02", "01")
    assert tuple(p.loc["1001", ["grupo_codigo", "subgrupo_codigo"]]) == ("01", "02")
    assert not any("criados" in a for a in avisos)


def test_importa_por_nome_encontra_ou_cria(repo):
    csv = ("SKU;Produto;Família;Subcategoria;Preço Venda\n"
           "X1;Balcão pia; COZINHA ;balcões;899,00\n"      # existentes, grafia diferente
           "X2;Torre forno;Cozinha;Torres;1.290,00\n"       # subgrupo novo no grupo 01
           "X3;Cadeira;Cadeiras;Giratórias;350\n").encode("latin-1")  # grupo e subgrupo novos
    avisos = repo.mesclar("produtos", ler_csv(io.BytesIO(csv), "produtos"))
    p = _prod(repo)
    assert tuple(p.loc["X1", ["grupo_codigo", "subgrupo_codigo"]]) == ("01", "02")
    assert tuple(p.loc["X2", ["grupo_codigo", "subgrupo_codigo"]]) == ("01", "03")
    assert tuple(p.loc["X3", ["grupo_codigo", "subgrupo_codigo"]]) == ("04", "01")
    g = repo.carregar("grupos").set_index("codigo")["descricao"]
    assert g["04"] == "Cadeiras"
    assert any("Grupos criados: 04 Cadeiras" in a for a in avisos)


def test_codigo_inexistente_cria_com_nome_da_planilha(repo):
    df = pd.DataFrame([{"codigo": "Z1", "descricao": "Z", "grupo_codigo": "90", "grupo": "Jardim",
                        "subgrupo_codigo": "05", "subgrupo": "Vasos"}])
    repo.mesclar("produtos", df)
    assert repo.carregar("grupos").set_index("codigo").loc["90", "descricao"] == "Jardim"
    sg = repo.carregar("subgrupos").set_index(["grupo_codigo", "codigo"])
    assert sg.loc[("90", "05"), "descricao"] == "Vasos"


def test_grupo_em_uso_nao_e_excluido(repo):
    repo.salvar("grupos", repo.carregar("grupos").iloc[0:0])
    g = repo.carregar("grupos").set_index("codigo")["descricao"]
    assert g["01"] == "Cozinha"                  # restaurado com a descrição anterior
    assert len(repo.carregar("produtos")) == 3   # nenhum produto perdido
    # subgrupo sem produto (01/02 Balcões) cai junto com o grupo? Não: o grupo 01 voltou,
    # mas a exclusão em massa removeu os subgrupos órfãos que não estavam em uso
    sg = set(map(tuple, repo.carregar("subgrupos")[["grupo_codigo", "codigo"]].values))
    assert ("01", "01") in sg


def test_alterar_codigo_em_cascata(repo):
    assert repo.alterar_codigo_grupo("01", "10") == 1
    assert _prod(repo).loc["P001", "grupo_codigo"] == "10"
    assert set(repo.carregar("subgrupos").query("grupo_codigo == '10'")["codigo"]) == {"01", "02"}
    assert repo.alterar_codigo_subgrupo("10", "01", "07") == 1
    assert _prod(repo).loc["P001", "subgrupo_codigo"] == "07"
    with pytest.raises(ValueError):
        repo.alterar_codigo_grupo("02", "03")
    with pytest.raises(ValueError, match="padrão"):
        repo.alterar_codigo_grupo("00", "99")


def test_proximo_codigo():
    assert proximo_codigo([]) == "01"
    assert proximo_codigo(["00", "01", "07"]) == "08"
    assert proximo_codigo(["001", "abc"]) == "002"


def test_resumo_por_grupo_fecha_com_total(repo):
    m = MotorCustos(repo.carregar_tudo(), repo.parametros())
    rg = m.resumo_por_grupo("grupo")
    assert rg["faturamento"].sum() == pytest.approx(m.resumo().faturamento_projetado)
    assert set(rg["grupo_codigo"]) == {"01", "02", "03"}
    assert "subgrupo_codigo" in m.resumo_por_grupo("subgrupo")


def test_xlsx_exporta_e_reimporta(repo, tmp_path):
    conteudo = exportar_xlsx(repo.carregar_tudo(), repo.parametros())
    abas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, dtype=str)
    assert {"grupos", "subgrupos", "resumo_grupos"} <= set(abas)
    assert {"Cód. grupo", "Grupo", "Cód. subgrupo", "Subgrupo"} <= set(abas["precos"].columns)
    novo = Repositorio(tmp_path / "n.db")
    assert novo.importar(ler_xlsx(io.BytesIO(conteudo)), "substituir") == []
    cols = ["grupo_codigo", "subgrupo_codigo"]
    assert novo.carregar("produtos")[cols].equals(repo.carregar("produtos")[cols])


def test_migracao_da_versao_por_nome(tmp_path):
    """Banco da versão anterior (grupos por nome) ganha códigos e mantém os vínculos."""
    db = tmp_path / "v1.db"
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE grupos ("grupo" TEXT, "subgrupo" TEXT, "descricao" TEXT, PRIMARY KEY ("grupo","subgrupo"))')
    con.execute('CREATE TABLE produtos ("codigo" TEXT, "descricao" TEXT, "grupo" TEXT, "subgrupo" TEXT, '
                '"unidade" TEXT, "margem_desejada_pct" REAL, "volume_mensal" REAL, "preco_atual" REAL, '
                'PRIMARY KEY ("codigo"))')
    con.executemany("INSERT INTO grupos VALUES (?, ?, NULL)",
                    [("Cozinha", "Armários"), ("Cozinha", "Balcões"), ("Sem grupo", "Geral")])
    con.executemany("INSERT INTO produtos VALUES (?, ?, ?, ?, 'un', NULL, 5, 100)",
                    [("A", "a", "Cozinha", "Balcões"), ("B", "b", "Sem grupo", "Geral"),
                     ("C", "c", "Quarto", "Camas")])  # 'Quarto' só existia no produto
    con.commit()
    con.close()

    r = Repositorio(db)
    g = r.carregar("grupos").set_index("descricao")["codigo"]
    assert g["Sem grupo"] == "00" and g["Cozinha"] == "01" and g["Quarto"] == "02"
    p = r.carregar("produtos").set_index("codigo")
    assert tuple(p.loc["A", ["grupo_codigo", "subgrupo_codigo"]]) == ("01", "02")   # Armários=01, Balcões=02
    assert tuple(p.loc["B", ["grupo_codigo", "subgrupo_codigo"]]) == ("00", "00")
    assert tuple(p.loc["C", ["grupo_codigo", "subgrupo_codigo"]]) == ("02", "01")
    # reabrir não migra de novo e continua gravando
    r2 = Repositorio(db)
    r2.mesclar("produtos", pd.DataFrame([{"codigo": "D", "descricao": "d", "grupo_codigo": "01",
                                          "subgrupo_codigo": "01"}]))
    assert len(r2.carregar("produtos")) == 4 and len(r2.carregar("grupos")) == 3


def test_migracao_de_banco_sem_grupos(tmp_path):
    db = tmp_path / "v0.db"
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE produtos ("codigo" TEXT, "descricao" TEXT, "unidade" TEXT, '
                '"margem_desejada_pct" REAL, "volume_mensal" REAL, "preco_atual" REAL, PRIMARY KEY ("codigo"))')
    con.execute("INSERT INTO produtos VALUES ('A1', 'Antigo', 'un', NULL, 10, 99.9)")
    con.commit()
    con.close()
    r = Repositorio(db)
    p = r.carregar("produtos")
    assert tuple(p.loc[0, ["grupo_codigo", "subgrupo_codigo"]]) == ("00", "00")
    assert p.loc[0, "preco_atual"] == pytest.approx(99.9)
