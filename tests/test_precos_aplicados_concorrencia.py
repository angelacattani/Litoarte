"""Custo atual × calculado, 5 preços aplicados, concorrentes por grupo e busca de preços na web."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from litoarte.busca import (ErroBusca, GoogleShopping, MercadoLivre, estatisticas, obter_token_ml,
                            remover_extremos)
from litoarte.busca.provedores import _ErroHTTP
from litoarte.domain.models import Concorrente, Configuracao, PrecoConcorrente
from litoarte.domain.services import composicao as C, concorrencia, faixas
from litoarte.domain.services.cadastros import MODULOS, gravar, listar
from litoarte.planilhas import relatorios as R
from litoarte.planilhas.importacao import aplicar, analisar


# --------------------------------------------------------------- custo atual e preços aplicados
def test_custo_atual_comparado_ao_calculado(sessao, canvas):
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.custo_atual = 70.0
    C.salvar(sessao, r)
    sessao.commit()
    r = C.rascunho_de_produto(sessao, canvas.id)
    comp = C.comparar_custo(r, C.calcular_rascunho(C.carregar_catalogo(sessao), r))
    assert comp.custo_atual == 70 and round(comp.custo_calculado, 2) == 76.81
    assert round(comp.diferenca, 2) == 6.81 and round(comp.diferenca_pct, 2) == 9.73


def test_precos_aplicados_e_margem_real(sessao, canvas):
    fs = faixas.listar(sessao)
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.precos_aplicados = {fs[0].id: 119.90, fs[4].id: 199.90}
    r.margens_faixas = {fs[4].id: 32.0}
    C.salvar(sessao, r)
    sessao.commit()
    r = C.rascunho_de_produto(sessao, canvas.id)
    assert r.precos_aplicados == {fs[0].id: 119.90, fs[4].id: 199.90} and r.margens_faixas == {fs[4].id: 32.0}
    pfs = C.precos_faixas(C.carregar_catalogo(sessao), r)
    p1 = pfs[0]
    assert p1.preco_aplicado == 119.90
    assert round(p1.margem_aplicada, 2) == round(100 * (1 - 0.295 - 76.8128 / 119.90), 2)
    assert p1.abaixo                                  # 119,90 rende menos que 10 %
    assert pfs[1].preco_aplicado is None and pfs[1].margem_aplicada is None


def test_substituir_precos_pelos_calculados(sessao, canvas):
    fs = faixas.listar(sessao)
    r = C.rascunho_de_produto(sessao, canvas.id)
    r.precos_aplicados = {fs[0].id: 119.90}
    C.salvar(sessao, r)
    sessao.commit()
    previa = C.substituir_precos(sessao, [canvas.id], [fs[0].id, fs[2].id], "90", simular=True)
    assert [(m.faixa, m.antes, m.depois) for m in previa] == [("Preço 1", 119.90, 126.90 + 1.0),
                                                                ("Preço 3", None, 152.90)]
    assert C.rascunho_de_produto(sessao, canvas.id).precos_aplicados == {fs[0].id: 119.90}   # prévia não grava
    C.substituir_precos(sessao, [canvas.id], [fs[0].id, fs[2].id], "90")
    sessao.commit()
    assert C.rascunho_de_produto(sessao, canvas.id).precos_aplicados == {fs[0].id: 127.90, fs[2].id: 152.90}
    assert C.substituir_precos(sessao, [canvas.id], [fs[0].id], "90") == []          # nada a mudar


def test_importar_custo_atual_e_cinco_precos(sessao, canvas):
    csv = ("sku;custo_atual;preco_faixa_1;preco_faixa_2;preco_faixa_3;preco_faixa_4;preco_faixa_5\n"
           "QDC-6090;70,00;119,90;134,90;149,90;169,90;189,90\n").encode()
    a = analisar(sessao, "produtos", csv, "precos.csv", "atualizar")
    assert a.pode_gravar, [l.erros for l in a.linhas]
    aplicar(sessao, a)
    sessao.commit()
    r = C.rascunho_de_produto(sessao, canvas.id)
    assert r.custo_atual == 70 and sorted(r.precos_aplicados.values()) == [119.9, 134.9, 149.9, 169.9, 189.9]
    linha = listar(sessao, MODULOS["produtos"])[0]
    assert linha["preco_faixa_3"] == 149.9 and linha["custo_atual"] == 70
    gravar(sessao, MODULOS["produtos"], {"sku": "QDC-6090", "preco_faixa_3": "remover"})
    sessao.commit()
    assert len(C.rascunho_de_produto(sessao, canvas.id).precos_aplicados) == 4
    df = R.tabela_precos(sessao)
    assert df.loc[0, "Preço 1 — preço aplicado"] == 119.9
    assert round(df.loc[0, "Diferença custo calculado × atual (%)"], 2) == 9.73


# --------------------------------------------------------------- concorrentes por grupo
def test_concorrentes_por_grupo_e_precos(sessao, canvas):
    gravar(sessao, MODULOS["concorrentes"], {"nome": "Loja A", "site": "https://a.exemplo", "grupos": "QDR"})
    sessao.commit()
    assert [g.codigo for g in sessao.scalar(select(Concorrente)).grupos] == ["QDR"]
    gid, sid = concorrencia.grupo_do_produto(sessao, canvas.id)
    concorrencia.registrar(sessao, grupo_id=gid, concorrente="Loja A", descricao="Quadro canvas 60x90", preco=159.9)
    concorrencia.registrar(sessao, grupo_id=gid, subgrupo_id=sid, concorrente="Loja B", descricao="Canvas 60x90",
                           preco=139.9)
    concorrencia.registrar(sessao, grupo_id=gid, produto_id=canvas.id, concorrente="loja a",
                           descricao="Canvas igual ao meu", preco=149.9)
    sessao.commit()
    res = concorrencia.resumo(sessao, gid, sid, canvas.id)
    assert res.base == "produto" and res.n == 1 and res.mediana == 149.9
    assert [p.nivel for p in res.precos] == ["produto", "subgrupo", "grupo"]
    assert len(sessao.scalars(select(Concorrente)).all()) == 2          # 'loja a' = 'Loja A'
    res_sub = concorrencia.resumo(sessao, gid, sid)
    assert res_sub.base == "subgrupo" and res_sub.n == 1 and res_sub.minimo == 139.9
    assert concorrencia.resumo(sessao, gid).n == 3
    b = sessao.scalar(select(Concorrente).where(Concorrente.nome == "Loja B"))
    assert [g.codigo for g in b.grupos] == ["QDR"]                       # associado ao grupo automaticamente


def test_importar_precos_de_concorrentes(sessao, canvas):
    csv = ("grupo;subgrupo;concorrente;descricao;preco;url\n"
           "QDR;01;Loja C;Quadro 60x90;179,90;https://c.exemplo/q\n").encode()
    a = analisar(sessao, "precos_concorrentes", csv, "c.csv")
    assert a.pode_gravar, [l.erros for l in a.linhas]
    aplicar(sessao, a)
    sessao.commit()
    pc = sessao.scalar(select(PrecoConcorrente))
    assert (pc.concorrente.nome, pc.preco, pc.subgrupo.codigo) == ("Loja C", 179.9, "01")
    assert [g.codigo for g in pc.concorrente.grupos] == ["QDR"]


# --------------------------------------------------------------- busca na web (HTTP simulado)
ML_RESPOSTA = {"results": [
    {"title": "Quadro Canvas 60x90 Paisagem", "price": 159.9, "currency_id": "BRL",
     "permalink": "https://produto.mercadolivre.com.br/MLB-1", "thumbnail": "https://img/1.jpg",
     "condition": "new", "seller": {"id": 1, "nickname": "LOJAQUADROS"}},
    {"title": "Quadro Canvas 60x90 Abstrato", "price": 129.0, "currency_id": "BRL",
     "permalink": "https://produto.mercadolivre.com.br/MLB-2", "official_store_name": "Arte Decor"},
    {"title": "Item em dólar", "price": 30, "currency_id": "USD"},
]}


def test_mercado_livre_busca_e_converte():
    chamadas = []

    def get(url, headers):
        chamadas.append((url, headers))
        return ML_RESPOSTA
    res = MercadoLivre("TOKEN", http_get=get).buscar("quadro canvas 60x90")
    assert "q=quadro+canvas+60x90" in chamadas[0][0] and chamadas[0][1] == {"Authorization": "Bearer TOKEN"}
    assert [(r.titulo, r.preco, r.loja, r.condicao) for r in res] == [
        ("Quadro Canvas 60x90 Paisagem", 159.9, "LOJAQUADROS (Mercado Livre)", "novo"),
        ("Quadro Canvas 60x90 Abstrato", 129.0, "Arte Decor (Mercado Livre)", None)]


def test_mercado_livre_exige_credencial():
    def get(url, headers):
        raise _ErroHTTP(403, {"message": "forbidden"})
    with pytest.raises(ErroBusca, match="exige credencial"):
        MercadoLivre(None, http_get=get).buscar("x")


def test_token_ml_client_credentials():
    def post(url, dados):
        assert dados["grant_type"] == "client_credentials" and dados["client_id"] == "ID"
        return {"access_token": "APP_USR-123", "expires_in": 21600}
    token, expira = obter_token_ml("ID", "SEGREDO", post)
    assert token == "APP_USR-123" and expira > datetime.now() + timedelta(hours=5)

    def recusa(url, dados):
        raise _ErroHTTP(400, {"message": "invalid client"})
    with pytest.raises(ErroBusca, match="recusou as credenciais"):
        obter_token_ml("ID", "X", recusa)


def test_google_shopping_serpapi():
    resposta = {"shopping_results": [
        {"title": "Quadro Canvas 60x90", "price": "R$ 149,90", "extracted_price": 149.9, "source": "Magazine Luiza",
         "product_link": "https://www.google.com/shopping/product/1"},
        {"title": "Quadro sem preço numérico", "price": "R$ 1.299,00", "source": "Elo7", "link": "https://elo7/x"},
        {"title": "Sem preço"}]}
    res = GoogleShopping("CHAVE", http_get=lambda url, h: resposta).buscar("quadro canvas 60x90")
    assert [(r.preco, r.loja) for r in res] == [(149.9, "Magazine Luiza"), (1299.0, "Elo7")]
    with pytest.raises(ErroBusca, match="chave da SerpApi"):
        GoogleShopping(None)
    with pytest.raises(ErroBusca, match="SerpApi: Invalid API key"):
        GoogleShopping("X", http_get=lambda u, h: {"error": "Invalid API key"}).buscar("q")


def test_estatisticas_e_extremos():
    from litoarte.busca import ResultadoBusca as RB
    rs = [RB("q", p, "l", None, "mercadolivre") for p in (120, 130, 135, 140, 150, 9.9, 2000)]
    assert [r.preco for r in remover_extremos(rs)] == [120, 130, 135, 140, 150]
    e = estatisticas([120, 130, 140])
    assert e["mediana"] == 130 and e["n"] == 3


def test_provedor_renova_token_e_grava_resultados(sessao, canvas):
    concorrencia.salvar_credenciais(sessao, ml_client_id="ID", ml_client_secret="S", ml_access_token=None,
                                    serpapi_chave="K")
    posts = []

    def post(url, dados):
        posts.append(dados)
        return {"access_token": "NOVO", "expires_in": 21600}
    prov = concorrencia.provedor(sessao, "mercadolivre", http_get=lambda u, h: ML_RESPOSTA, http_post=post)
    assert prov.token == "NOVO" and len(posts) == 1
    concorrencia.provedor(sessao, "mercadolivre", http_get=lambda u, h: ML_RESPOSTA, http_post=post)
    assert len(posts) == 1                                   # token em cache até expirar
    cfg = sessao.get(Configuracao, 1)
    cfg.ml_token_expira_em = datetime.now() - timedelta(minutes=1)
    concorrencia.provedor(sessao, "mercadolivre", http_get=lambda u, h: ML_RESPOSTA, http_post=post)
    assert len(posts) == 2                                   # expirado: renova
    resultados = prov.buscar("quadro canvas 60x90")
    gid, sid = concorrencia.grupo_do_produto(sessao, canvas.id)
    n = concorrencia.registrar_resultados(sessao, resultados[:1], grupo_id=gid, subgrupo_id=sid,
                                          produto_id=canvas.id)
    sessao.commit()
    pc = sessao.scalar(select(PrecoConcorrente))
    assert n == 1 and (pc.fonte, pc.preco, pc.concorrente.nome) == ("mercadolivre", 159.9, "LOJAQUADROS (Mercado Livre)")
    assert isinstance(concorrencia.provedor(sessao, "google_shopping"), GoogleShopping)


def test_buscar_web_sem_banco(sessao):
    concorrencia.salvar_credenciais(sessao, ml_client_id="ID", ml_client_secret="S", ml_access_token=None,
                                    serpapi_chave=None)
    cred = concorrencia.credenciais(sessao)
    res, novo = concorrencia.buscar_web(cred, "mercadolivre", "quadro", http_get=lambda u, h: ML_RESPOSTA,
                                        http_post=lambda u, d: {"access_token": "T", "expires_in": 600})
    assert len(res) == 2 and novo[0] == "T"
    concorrencia.guardar_token(sessao, *novo)
    res, novo = concorrencia.buscar_web(concorrencia.credenciais(sessao), "mercadolivre", "quadro",
                                        http_get=lambda u, h: ML_RESPOSTA)
    assert novo is None
    with pytest.raises(ErroBusca, match="chave da SerpApi"):
        concorrencia.buscar_web(cred, "google_shopping", "quadro")
