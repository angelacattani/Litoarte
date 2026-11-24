"""Serviço de cadastros: validação, gravação, exclusão/inativação e listagem."""

import pytest
from sqlalchemy import select

from litoarte.domain.models import CustoVariavel, Fornecedor, MaoDeObra, MateriaPrima, PerfilVenda, Produto
from litoarte.domain.services import valores as V
from litoarte.domain.services.cadastros import (MODULOS, ErroValidacao, definir_ativo, excluir, gravar, listar,
                                                validar_registro)
from litoarte.domain.services.precificacao import calcular_produto

MP, MO, CV, SUB, PROD = (MODULOS[k] for k in ("materias_primas", "mao_de_obra", "custos_variaveis", "subgrupos",
                                              "produtos"))


@pytest.mark.parametrize("entrada,esperado", [("1.234,56", 1234.56), ("R$ 12,90", 12.9), ("18%", 18.0),
                                              ("3.5", 3.5), (7, 7.0), ("", None), ("12,5", 12.5)])
def test_numero(entrada, esperado):
    assert V.numero(entrada) == (pytest.approx(esperado) if esperado is not None else None)


def test_numero_invalido_e_opcoes():
    with pytest.raises(V.ValorInvalido):
        V.numero("doze")
    assert V.booleano("Não") is False and V.booleano("SIM") is True
    assert V.opcao("Área", ("fixa", "area")) == "area"
    assert V.texto(1001.0) == "1001"


def test_insumo_inclusao_e_atualizacao_parcial(sessao):
    mp = gravar(sessao, MP, {"sku": "TINTA", "nome": "Tinta 1 L", "unidade_compra": "frasco",
                             "unidade_consumo": "ml", "fator_conversao": "1000", "custo_compra": "280,00",
                             "perda_pct": "10", "fornecedor": "Insumos Gráficos"})
    sessao.commit()
    assert mp.custo_consumo == pytest.approx(0.28)
    assert sessao.scalar(select(Fornecedor)).nome == "Insumos Gráficos"     # criado automaticamente
    # atualização: só o preço; campos vazios não apagam nada
    gravar(sessao, MP, {"sku": "TINTA", "custo_compra": "300", "perda_pct": ""})
    sessao.commit()
    mp = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TINTA"))
    assert (mp.custo_compra, mp.perda_pct, mp.fator_conversao) == (300.0, 10.0, 1000.0)
    assert len(mp.historico) == 1


def test_insumo_unidade_consumo_padrao_e_erros(sessao):
    gravar(sessao, MP, {"sku": "CX", "nome": "Caixa", "unidade_compra": "un", "custo_compra": 6.5})
    assert sessao.scalar(select(MateriaPrima)).unidade_consumo.sigla == "un"
    with pytest.raises(ErroValidacao) as e:
        gravar(sessao, MP, {"sku": "X", "nome": "x", "unidade_compra": "litros?", "custo_compra": "-1",
                            "perda_pct": 100, "largura_m": 1})
    campos = {c for c, _ in e.value.erros}
    assert {"unidade_compra", "custo_compra", "perda_pct"} <= campos


def test_insumo_folha_exige_as_duas_dimensoes(sessao):
    with pytest.raises(ErroValidacao, match="juntos"):
        gravar(sessao, MP, {"sku": "PAP", "nome": "Papel", "unidade_compra": "folha", "custo_compra": 18,
                            "largura_m": 1})


def test_inclusao_exige_obrigatorios(sessao):
    _, _, erros = validar_registro(sessao, MP, {"sku": "NOVO"})
    assert {"nome", "unidade_compra", "custo_compra"} <= {c for c, _ in erros}


def test_mao_de_obra_por_minuto_e_calculada(sessao):
    gravar(sessao, MO, {"codigo": "CORTE", "etapa": "Corte", "custo_minuto": "0,45"})
    gravar(sessao, MO, {"codigo": "MONT", "etapa": "Montagem", "salario_mensal": "2.000",
                        "encargos_pct": 70, "horas_produtivas_mes": 160})
    sessao.commit()
    corte, mont = sessao.scalars(select(MaoDeObra).order_by(MaoDeObra.codigo)).all()
    assert (corte.modo_custo, corte.custo_hora) == ("informado", pytest.approx(27.0))
    assert (mont.modo_custo, mont.custo_hora) == ("calculado", pytest.approx(21.25))
    with pytest.raises(ErroValidacao, match="OU"):
        gravar(sessao, MO, {"codigo": "X", "etapa": "x", "custo_hora": 1, "custo_minuto": 1})
    with pytest.raises(ErroValidacao):
        gravar(sessao, MO, {"codigo": "Y", "etapa": "y", "modo_custo": "calculado", "salario_mensal": 1000})


def test_custo_variavel_e_perfis(sessao):
    gravar(sessao, CV, {"codigo": "SN", "descricao": "Simples", "tipo": "%", "valor": "6",
                        "perfis": "Venda direta; Marketplace"})
    gravar(sessao, CV, {"codigo": "FRETE", "descricao": "Frete", "tipo": "R$", "valor": "12,00",
                        "perfis": "Marketplace"})
    sessao.commit()
    mkt = sessao.scalar(select(PerfilVenda).where(PerfilVenda.nome == "Marketplace"))
    assert {c.codigo for c in mkt.custos} == {"SN", "FRETE"}
    assert sessao.scalar(select(CustoVariavel).where(CustoVariavel.codigo == "FRETE")).tipo == "valor_fixo"
    gravar(sessao, CV, {"codigo": "SN", "perfis": "Venda direta"})     # tira do Marketplace
    sessao.commit()
    assert {c.codigo for c in mkt.custos} == {"FRETE"}
    linha = next(r for r in listar(sessao, CV) if r["codigo"] == "SN")
    assert linha["perfis"] == "Venda direta"


def test_subgrupo_chave_composta_e_produto(sessao):
    gravar(sessao, MODULOS["grupos"], {"codigo": "QDR", "nome": "Quadros"})
    gravar(sessao, MODULOS["grupos"], {"codigo": "PAP", "nome": "Papelaria"})
    gravar(sessao, SUB, {"grupo": "QDR", "codigo": "01", "nome": "Canvas"})
    gravar(sessao, SUB, {"grupo": "PAP", "codigo": "01", "nome": "Recortes"})      # mesmo código, outro grupo
    p = gravar(sessao, PROD, {"sku": "QDC", "nome": "Quadro", "grupo": "QDR", "subgrupo": "01", "largura_cm": 60})
    sessao.commit()
    assert p.subgrupo.nome == "Canvas"
    with pytest.raises(ErroValidacao, match="não cadastrado"):
        gravar(sessao, PROD, {"sku": "X", "nome": "x", "grupo": "QDR", "subgrupo": "99"})
    with pytest.raises(ErroValidacao, match="obrigatório"):
        gravar(sessao, PROD, {"sku": "Y", "nome": "y"})
    assert listar(sessao, PROD)[0]["grupo"] == "QDR"


def test_edicao_nao_pode_assumir_chave_de_outro(sessao):
    a = gravar(sessao, MODULOS["custos_fixos"], {"codigo": "A", "descricao": "a", "valor_mensal": 1})
    gravar(sessao, MODULOS["custos_fixos"], {"codigo": "B", "descricao": "b", "valor_mensal": 2})
    with pytest.raises(ErroValidacao, match="já existe"):
        gravar(sessao, MODULOS["custos_fixos"], {"codigo": "B", "descricao": "a"}, id_edicao=a.id)


def test_excluir_em_uso_sugere_inativar(sessao, canvas):
    tela = sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA"))
    with pytest.raises(ErroValidacao, match="Inative"):
        excluir(sessao, MP, tela.id)
    definir_ativo(sessao, MP, tela.id, False)
    sessao.commit()
    assert not sessao.get(MateriaPrima, tela.id).ativo
    assert all(r["sku"] != "TELA" for r in listar(sessao, MP, incluir_inativos=False))


def test_excluir_livre(sessao):
    cf = gravar(sessao, MODULOS["custos_fixos"], {"codigo": "A", "descricao": "a", "valor_mensal": 1})
    sessao.commit()
    excluir(sessao, MODULOS["custos_fixos"], cf.id)
    sessao.commit()
    assert listar(sessao, MODULOS["custos_fixos"]) == []


def test_alterar_preco_pelo_cadastro_recalcula_produto(sessao, canvas):
    antes = calcular_produto(sessao, canvas.id).preco
    gravar(sessao, MP, {"sku": "CAIXA", "custo_compra": "8,50"})
    sessao.commit()
    assert calcular_produto(sessao, canvas.id).preco == pytest.approx(antes + 2.0 / 0.505)


def test_ficha_por_servico(sessao, canvas):
    FM = MODULOS["ficha_materiais"]
    gravar(sessao, FM, {"produto": "QDC-6090", "insumo": "GANCHO", "quantidade": 4})      # atualiza linha
    gravar(sessao, FM, {"produto": "qdc-6090", "insumo": "caixa", "modo_qtd": "un", "quantidade": 2})
    sessao.commit()
    p = sessao.get(Produto, canvas.id)
    qtd = {f.materia_prima.sku: f.quantidade for f in p.materiais}
    assert qtd["GANCHO"] == 4 and qtd["CAIXA"] == 2 and len(qtd) == 5


def test_formulario_apaga_opcional_vazio(sessao):
    gravar(sessao, MP, {"sku": "A", "nome": "a", "unidade_compra": "un", "custo_compra": 1, "fornecedor": "F1",
                        "perda_pct": 5})
    sessao.commit()
    mp = gravar(sessao, MP, {"sku": "A", "fornecedor": "", "perda_pct": None}, vazios_apagam=True)
    sessao.commit()
    assert mp.fornecedor_id is None
    assert mp.perda_pct == 0          # campo com padrão volta ao padrão
    # na importação, vazio mantém o valor
    gravar(sessao, MP, {"sku": "A", "perda_pct": 7})
    gravar(sessao, MP, {"sku": "A", "perda_pct": ""})
    assert mp.perda_pct == 7
