"""Fixtures: banco SQLite temporário migrado e o exemplo de aceite (Canvas 60×90, seção 3.9)."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text

from litoarte.db import criar_engine, fabrica_sessoes
from litoarte.domain.models import (Configuracao, CustoFixo, CustoVariavel, FichaMO, FichaMP, Grupo, MaoDeObra,
                                    MateriaPrima, PerfilVenda, Produto, Subgrupo, UnidadeMedida)
from litoarte.migracoes import atualizar_banco


@pytest.fixture
def url(tmp_path):
    """SQLite temporário; com LITOARTE_TEST_PG=<url do servidor> usa um banco PostgreSQL novo por teste."""
    servidor = os.environ.get("LITOARTE_TEST_PG")
    if not servidor:
        u = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
        atualizar_banco(u)
        yield u
        return
    nome = f"t_{uuid.uuid4().hex[:12]}"
    admin = create_engine(servidor, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{nome}"'))
    u = servidor.rsplit("/", 1)[0] + f"/{nome}" if "?" not in servidor else \
        servidor.split("?")[0].rsplit("/", 1)[0] + f"/{nome}?" + servidor.split("?")[1]
    atualizar_banco(u)
    yield u
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE "{nome}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def sessao(url):
    engine = criar_engine(url)
    s = fabrica_sessoes(engine)()
    yield s
    s.close()
    engine.dispose()


def un(sessao, sigla):
    return sessao.scalar(select(UnidadeMedida).where(UnidadeMedida.sigla == sigla))


def carregar_canvas(sessao) -> Produto:
    """Dados da seção 3.9 da especificação."""
    m2, m, ml, frasco, unid = (un(sessao, s) for s in ("m2", "m", "ml", "frasco", "un"))
    tela = MateriaPrima(sku="TELA", nome="Tela canvas", unidade_compra=m2, unidade_consumo=m2,
                        custo_compra=38.0, perda_pct=10)
    chassi = MateriaPrima(sku="CHASSI", nome="Chassi pinus", unidade_compra=m, unidade_consumo=m,
                          custo_compra=9.5, perda_pct=5)
    tinta = MateriaPrima(sku="TINTA", nome="Tinta CMYK 1 L", unidade_compra=frasco, unidade_consumo=ml,
                         fator_conversao=1000, custo_compra=280.0, perda_pct=10)
    gancho = MateriaPrima(sku="GANCHO", nome="Gancho", unidade_compra=unid, unidade_consumo=unid, custo_compra=1.2)
    caixa = MateriaPrima(sku="CAIXA", nome="Caixa", unidade_compra=unid, unidade_consumo=unid, custo_compra=6.5)
    imp = MaoDeObra(codigo="IMP", etapa="Impressão", modo_custo="informado", custo_hora_informado=0.45 * 60)
    mon = MaoDeObra(codigo="MON", etapa="Montagem", modo_custo="informado", custo_hora_informado=0.40 * 60)
    aca = MaoDeObra(codigo="ACA", etapa="Acabamento", modo_custo="informado", custo_hora_informado=0.35 * 60)
    sessao.add_all([CustoFixo(codigo="ALUG", descricao="Aluguel", valor_mensal=7000),
                    CustoFixo(codigo="PROL", descricao="Pró-labore", valor_mensal=5000)])
    perfil = sessao.scalar(select(PerfilVenda).where(PerfilVenda.padrao))
    perfil.custos = [CustoVariavel(codigo="SN", descricao="Simples", categoria="imposto", valor=6),
                     CustoVariavel(codigo="CART", descricao="Cartão", categoria="cartao", valor=3.5),
                     CustoVariavel(codigo="COM", descricao="Comissão", categoria="comissao", valor=5)]
    cfg = sessao.get(Configuracao, 1)
    cfg.faturamento_base_mensal = 80_000
    cfg.metodo_rateio = "pct_faturamento"
    cfg.margem_padrao_pct = 20
    sub = Subgrupo(codigo="01", nome="Canvas grande", grupo=Grupo(codigo="QDR", nome="Quadros"))
    p = Produto(sku="QDC-6090", nome="Quadro Canvas 60×90", subgrupo=sub, largura_cm=60, altura_cm=90)
    p.materiais = [FichaMP(materia_prima=tela, modo_qtd="area", quantidade=1, ordem=1),
                   FichaMP(materia_prima=chassi, modo_qtd="perimetro", quantidade=1, ordem=2),
                   FichaMP(materia_prima=tinta, modo_qtd="area", quantidade=12 * 0.80, ordem=3),
                   FichaMP(materia_prima=gancho, modo_qtd="fixa", quantidade=2, ordem=4),
                   FichaMP(materia_prima=caixa, modo_qtd="fixa", quantidade=1, ordem=5)]
    p.mao_de_obra = [FichaMO(mao_de_obra=imp, tempo=6, unidade_tempo="min", ordem=1),
                     FichaMO(mao_de_obra=mon, tempo=20, unidade_tempo="min", ordem=2),
                     FichaMO(mao_de_obra=aca, tempo=8, unidade_tempo="min", ordem=3)]
    sessao.add(p)
    sessao.commit()
    return p


@pytest.fixture
def canvas(sessao):
    return carregar_canvas(sessao)
