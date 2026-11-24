"""Perfis de venda e configuração."""

import pytest
from sqlalchemy import select

from litoarte.domain.models import Configuracao, CustoVariavel, PerfilVenda, Produto
from litoarte.domain.services import configuracao as cfgsvc, perfis
from litoarte.domain.services.cadastros import ErroValidacao
from litoarte.domain.services.precificacao import calcular_produto


def test_perfis_ciclo_completo(sessao, canvas):
    direta = sessao.scalar(select(PerfilVenda).where(PerfilVenda.padrao))
    mkt = perfis.criar(sessao, "Marketplace", copiar_de=direta.id)
    frete = CustoVariavel(codigo="MKT", descricao="Comissão marketplace", categoria="marketplace", valor=16)
    sessao.add(frete)
    sessao.flush()
    perfis.definir_custo(sessao, mkt.id, frete.id, True)
    sessao.commit()
    assert perfis.resumo(mkt) == (pytest.approx(30.5), 0)
    assert perfis.resumo(direta) == (pytest.approx(14.5), 0)
    # produto passa a usar o marketplace: preço sobe
    antes = calcular_produto(sessao, canvas.id).preco
    sessao.get(Produto, canvas.id).perfil_venda_id = mkt.id
    sessao.commit()
    assert calcular_produto(sessao, canvas.id).preco > antes
    with pytest.raises(ErroValidacao, match="usado por 1"):
        perfis.excluir(sessao, mkt.id)
    with pytest.raises(ErroValidacao, match="já existe"):
        perfis.criar(sessao, "marketplace")
    perfis.definir_padrao(sessao, mkt.id)
    sessao.commit()
    assert [p.nome for p in perfis.listar(sessao)][0] == "Marketplace"
    with pytest.raises(ErroValidacao, match="padrão"):
        perfis.excluir(sessao, mkt.id)
    perfis.renomear(sessao, direta.id, "Loja física")
    perfis.excluir(sessao, direta.id)
    sessao.commit()
    assert [p.nome for p in perfis.listar(sessao)] == ["Marketplace"]


def test_configuracao_validada(sessao):
    with pytest.raises(ErroValidacao) as e:
        cfgsvc.salvar(sessao, {"metodo_rateio": "pct_faturamento", "modo_perda": "acrescimo",
                               "faturamento_base_mensal": None, "margem_padrao_pct": 120})
    assert {c for c, _ in e.value.erros} == {"faturamento_base_mensal", "margem_padrao_pct"}
    cfgsvc.salvar(sessao, {"metodo_rateio": "hora_produtiva", "modo_perda": "acrescimo",
                           "capacidade_horas_mes": "408", "margem_padrao_pct": "25,5"})
    sessao.commit()
    c = sessao.get(Configuracao, 1)
    assert (c.metodo_rateio, c.modo_perda, c.capacidade_horas_mes, c.margem_padrao_pct) == \
        ("hora_produtiva", "acrescimo", 408, 25.5)
