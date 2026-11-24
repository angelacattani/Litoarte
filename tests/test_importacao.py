"""Importação/exportação: modelo, análise prévia, tudo-ou-nada, atualização por SKU, ida e volta."""

import io

import pandas as pd
import pytest
from sqlalchemy import func, select

from litoarte.domain.models import HistoricoCustoMP, ImportacaoLog, MateriaPrima, Produto
from litoarte.domain.services.cadastros import MODULOS, ORDEM_IMPORTACAO, ErroValidacao
from litoarte.domain.services.precificacao import calcular_produto
from litoarte.planilhas.importacao import aplicar, analisar
from litoarte.planilhas.leitura import mapear_colunas
from litoarte.planilhas.modelos import exportar, gerar_modelo


def xlsx(linhas: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(linhas).to_excel(buf, sheet_name="dados", index=False)
    return buf.getvalue()


def csv(texto: str, enc="utf-8") -> bytes:
    return texto.encode(enc)


# --------------------------------------------------------------- modelos
@pytest.mark.parametrize("modulo", ORDEM_IMPORTACAO)
def test_modelo_de_cada_modulo(modulo):
    abas = pd.read_excel(io.BytesIO(gerar_modelo(MODULOS[modulo])), sheet_name=None)
    assert list(abas["dados"].columns) == [c.nome for c in MODULOS[modulo].campos]
    assert abas["dados"].empty                                   # sem linhas de exemplo para não importar sujeira
    assert len(abas["instrucoes"]) == len(MODULOS[modulo].campos)


def test_cabecalhos_usuais_sao_reconhecidos():
    mapa, ignoradas = mapear_colunas(MODULOS["materias_primas"],
                                     ["Código", "Descrição", "Custo (R$)", "Unidade", "Perda (%)", "Observação"])
    assert mapa == {"Código": "sku", "Descrição": "nome", "Custo (R$)": "custo_compra",
                    "Unidade": "unidade_compra", "Perda (%)": "perda_pct"}
    assert ignoradas == ["Observação"]


# --------------------------------------------------------------- análise e gravação
def test_importar_insumos_csv_brasileiro(sessao):
    arq = csv("Código;Descrição;Unidade;Custo (R$);Perda (%);Fornecedor\n"
              "TELA;Tela canvas;m2;38,00;10;Têxtil Sul\n"
              "CHASSI;Chassi pinus;m;9,50;5;\n", "cp1252")
    a = analisar(sessao, "materias_primas", arq, "insumos.csv")
    assert a.pode_gravar and a.contagem() == {"inserir": 2, "atualizar": 0, "ignorar": 0, "erro": 0}
    assert sessao.scalar(select(func.count()).select_from(MateriaPrima)) == 0     # análise não grava
    r = aplicar(sessao, a, usuario="teste")
    sessao.commit()
    assert (r.inseridas, r.atualizadas) == (2, 0)
    assert sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA")).fornecedor.nome == "Têxtil Sul"
    log = sessao.scalar(select(ImportacaoLog))
    assert (log.modulo, log.inseridas, log.usuario) == ("materias_primas", 2, "teste")


def test_arquivo_com_erro_mostra_relatorio_e_nao_grava_nada(sessao):
    """Critério de aceite da fase 2."""
    arq = xlsx([{"sku": "A", "nome": "ok", "unidade_compra": "un", "custo_compra": "10"},
                {"sku": "B", "nome": "unidade errada", "unidade_compra": "caixote", "custo_compra": "5"},
                {"sku": "C", "nome": "preço inválido", "unidade_compra": "un", "custo_compra": "dez"},
                {"sku": "A", "nome": "duplicado", "unidade_compra": "un", "custo_compra": "1"}])
    a = analisar(sessao, "materias_primas", arq, "insumos.xlsx")
    assert not a.pode_gravar
    erros = {l.linha: l.erros for l in a.linhas if l.acao == "erro"}
    assert erros[3] == [("unidade_compra", "'caixote' não cadastrado")]
    assert erros[4][0][0] == "custo_compra" and "número inválido" in erros[4][0][1]
    assert "repetida" in erros[5][0][1] and "linha 2" in erros[5][0][1]
    with pytest.raises(ErroValidacao):
        aplicar(sessao, a)
    assert sessao.scalar(select(func.count()).select_from(MateriaPrima)) == 0


def test_colunas_faltando(sessao):
    a = analisar(sessao, "materias_primas", xlsx([{"nome": "sem sku", "custo_compra": 1}]), "x.xlsx")
    assert any("sku" in e for e in a.erros_arquivo) and not a.pode_gravar
    a = analisar(sessao, "materias_primas", xlsx([{"sku": "A", "custo_compra": 1}]), "x.xlsx", "inserir")
    assert any("nome" in e and "unidade_compra" in e for e in a.erros_arquivo)


def test_atualizar_precos_por_sku_com_relatorio_de_impacto(sessao, canvas):
    antes = calcular_produto(sessao, canvas.id).preco
    arq = csv("sku,custo_compra\nTELA,45.00\nCAIXA,6.50\nNAOEXISTE,1\n")
    a = analisar(sessao, "materias_primas", arq, "precos.csv", "atualizar")
    assert a.contagem() == {"inserir": 0, "atualizar": 2, "ignorar": 1, "erro": 0}   # só preço: nome não exigido
    r = aplicar(sessao, a)
    sessao.commit()
    assert r.reajustes == [("TELA", 38.0, 45.0)]          # CAIXA não mudou de preço
    assert r.produtos_afetados == ["QDC-6090"]
    assert calcular_produto(sessao, canvas.id).preco > antes
    h = sessao.scalar(select(HistoricoCustoMP))
    assert (h.custo_anterior, h.custo_novo, h.origem) == (38.0, 45.0, "importacao")


def test_modo_inserir_ignora_existentes(sessao, canvas):
    arq = xlsx([{"sku": "TELA", "nome": "Tela", "unidade_compra": "m2", "custo_compra": 99},
                {"sku": "NOVO", "nome": "Novo", "unidade_compra": "un", "custo_compra": 1}])
    a = analisar(sessao, "materias_primas", arq, "x.xlsx", "inserir")
    assert a.contagem()["ignorar"] == 1 and a.contagem()["inserir"] == 1
    aplicar(sessao, a)
    sessao.commit()
    assert sessao.scalar(select(MateriaPrima).where(MateriaPrima.sku == "TELA")).custo_compra == 38.0


def test_carga_completa_em_ordem(sessao):
    planilhas = {
        "mao_de_obra": [{"codigo": "CORTE", "etapa": "Corte", "custo_minuto": "0,45"}],
        "materias_primas": [{"sku": "PAP", "nome": "Papel 1x2", "unidade_compra": "folha", "custo_compra": 18,
                             "largura_m": 1, "comprimento_m": 2}],
        "custos_fixos": [{"codigo": "ALUG", "descricao": "Aluguel", "valor_mensal": "3.500,00"}],
        "custos_variaveis": [{"codigo": "SN", "descricao": "Simples", "tipo": "percentual", "valor": 6,
                              "perfis": "Venda direta"}],
        "grupos": [{"codigo": "PAP", "nome": "Papelaria"}],
        "subgrupos": [{"grupo": "PAP", "codigo": "REC", "nome": "Recortes"}],
        "produtos": [{"sku": "REC-15", "nome": "Recorte 15x15", "grupo": "PAP", "subgrupo": "REC",
                      "largura_cm": 15, "altura_cm": 15}],
        "ficha_materiais": [{"produto": "REC-15", "insumo": "PAP", "modo_qtd": "folha", "quantidade": 1}],
        "ficha_mao_de_obra": [{"produto": "REC-15", "etapa": "CORTE", "tempo": 1, "unidade_tempo": "minutos"}],
    }
    for modulo in ORDEM_IMPORTACAO:
        if modulo in planilhas:
            a = analisar(sessao, modulo, xlsx(planilhas[modulo]), f"{modulo}.xlsx")
            assert a.pode_gravar, (modulo, [(l.linha, l.erros) for l in a.linhas], a.erros_arquivo)
            aplicar(sessao, a)
            sessao.commit()
    p = sessao.scalar(select(Produto))
    r = calcular_produto(sessao, p.id)
    assert r.materiais[0].pecas_folha == 78
    assert r.mo == pytest.approx(0.45)


def test_exportar_e_reimportar_sem_alteracoes(sessao, canvas):
    for modulo in ORDEM_IMPORTACAO:
        conteudo = exportar(sessao, MODULOS[modulo])
        a = analisar(sessao, modulo, conteudo, f"{modulo}.xlsx", "atualizar")
        assert not a.erros_arquivo or a.erros_arquivo == ["o arquivo não tem linhas de dados"], (modulo, a.erros_arquivo)
        assert all(l.acao == "atualizar" for l in a.linhas), (modulo, [(l.linha, l.erros) for l in a.linhas])
    antes = calcular_produto(sessao, canvas.id).preco
    for modulo in ORDEM_IMPORTACAO:
        a = analisar(sessao, modulo, exportar(sessao, MODULOS[modulo]), "x.xlsx", "atualizar")
        if a.pode_gravar:
            aplicar(sessao, a)
    sessao.commit()
    assert calcular_produto(sessao, canvas.id).preco == pytest.approx(antes)
    assert sessao.scalar(select(func.count()).select_from(HistoricoCustoMP)) == 0   # nada mudou de preço


def test_arquivo_ilegivel(sessao):
    a = analisar(sessao, "grupos", b"isto nao e planilha", "x.pdf")
    assert a.erros_arquivo and "não foi possível ler" in a.erros_arquivo[0]
