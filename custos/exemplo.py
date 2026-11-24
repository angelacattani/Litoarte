"""Base de exemplo (marcenaria fictícia) para testes e demonstração."""

import pandas as pd


def dados_exemplo() -> tuple[dict[str, pd.DataFrame], dict]:
    df = pd.DataFrame
    dados = {
        "materias_primas": df([
            {"codigo": "MP01", "descricao": "Chapa MDF 15mm", "unidade": "m2", "custo_unitario": 62.00, "fornecedor": "Fornecedor A"},
            {"codigo": "MP02", "descricao": "Dobradiça 35mm", "unidade": "un", "custo_unitario": 4.50, "fornecedor": "Fornecedor B"},
            {"codigo": "MP03", "descricao": "Fita de borda", "unidade": "m", "custo_unitario": 0.90, "fornecedor": "Fornecedor A"},
            {"codigo": "MP04", "descricao": "Puxador alumínio", "unidade": "un", "custo_unitario": 12.00, "fornecedor": "Fornecedor C"},
            {"codigo": "MP05", "descricao": "Embalagem", "unidade": "un", "custo_unitario": 8.00, "fornecedor": "Fornecedor D"},
            # papelaria: folha 1 × 2 m comprada inteira; impressão cobrada por folha impressa
            {"codigo": "PAP01", "descricao": "Papel couché 300g — folha 1×2 m", "unidade": "folha", "custo_unitario": 18.00,
             "largura_m": 1.0, "comprimento_m": 2.0, "margem_cm": 0.0, "fornecedor": "Papelaria E"},
            {"codigo": "IMP01", "descricao": "Impressão digital colorida — folha 1×2 m", "unidade": "folha",
             "custo_unitario": 60.00, "largura_m": 1.0, "comprimento_m": 2.0, "margem_cm": 0.0, "fornecedor": "Gráfica F"},
            {"codigo": "CRT01", "descricao": "Corte em plotter (metro linear)", "unidade": "m", "custo_unitario": 0.15,
             "fornecedor": "Gráfica F"},
            {"codigo": "FRT01", "descricao": "Frete de entrega (móveis)", "unidade": "un", "custo_unitario": 15.00,
             "fornecedor": "Transportadora G"},
            {"codigo": "EMB01", "descricao": "Saquinho celofane individual", "unidade": "un", "custo_unitario": 0.12,
             "fornecedor": "Fornecedor D"},
        ]),
        "mao_de_obra": df([
            {"codigo": "MO01", "funcao": "Marceneiro", "salario_mensal": 3200.0, "encargos_pct": 70.0, "horas_produtivas_mes": 160.0, "quantidade": 2},
            {"codigo": "MO03", "funcao": "Acabamento / embalagem", "salario_mensal": 1900.0, "encargos_pct": 70.0, "horas_produtivas_mes": 160.0, "quantidade": 1},
            {"codigo": "MO02", "funcao": "Montador", "salario_mensal": 2200.0, "encargos_pct": 70.0, "horas_produtivas_mes": 160.0, "quantidade": 1},
        ]),
        "custos_fixos": df([
            {"codigo": "CF01", "descricao": "Aluguel", "categoria": "Ocupação", "valor_mensal": 3500.0},
            {"codigo": "CF02", "descricao": "Energia (parcela fixa)", "categoria": "Utilidades", "valor_mensal": 600.0},
            {"codigo": "CF03", "descricao": "Pró-labore", "categoria": "Pessoal adm.", "valor_mensal": 5000.0},
            {"codigo": "CF04", "descricao": "Contador", "categoria": "Serviços", "valor_mensal": 800.0},
            {"codigo": "CF05", "descricao": "Depreciação de máquinas", "categoria": "Depreciação", "valor_mensal": 700.0},
        ]),
        "custos_variaveis": df([
            {"codigo": "CV01", "descricao": "Simples Nacional", "tipo": "percentual", "valor": 8.0},
            {"codigo": "CV02", "descricao": "Comissão de vendas", "tipo": "percentual", "valor": 5.0},
            {"codigo": "CV03", "descricao": "Taxa de cartão", "tipo": "percentual", "valor": 3.0},
        ]),
        "grupos": df([
            {"codigo": "01", "descricao": "Cozinha"},
            {"codigo": "02", "descricao": "Escritório"},
            {"codigo": "03", "descricao": "Decoração"},
            {"codigo": "04", "descricao": "Papelaria"},
        ]),
        "subgrupos": df([
            {"grupo_codigo": "01", "codigo": "01", "descricao": "Armários aéreos"},
            {"grupo_codigo": "01", "codigo": "02", "descricao": "Balcões"},
            {"grupo_codigo": "02", "codigo": "01", "descricao": "Gaveteiros"},
            {"grupo_codigo": "03", "codigo": "01", "descricao": "Nichos e prateleiras"},
            {"grupo_codigo": "04", "codigo": "01", "descricao": "Recortes impressos"},
        ]),
        # Ficha padrão do subgrupo 04/01: vale para todos os recortes, o tamanho vem do produto
        "composicao_subgrupo": df([
            {"grupo_codigo": "04", "subgrupo_codigo": "01", "mp_codigo": "PAP01", "base": "aproveitamento",
             "quantidade": 1, "perda_pct": 5.0, "espacamento_cm": 0.0},
            {"grupo_codigo": "04", "subgrupo_codigo": "01", "mp_codigo": "IMP01", "base": "aproveitamento",
             "quantidade": 1, "perda_pct": 5.0, "espacamento_cm": 0.0},
            {"grupo_codigo": "04", "subgrupo_codigo": "01", "mp_codigo": "CRT01", "base": "perimetro",
             "quantidade": 1, "perda_pct": 0.0},
            {"grupo_codigo": "04", "subgrupo_codigo": "01", "mp_codigo": "EMB01", "base": "unidade",
             "quantidade": 1, "perda_pct": 2.0},
        ]),
        "mo_subgrupo": df([
            {"grupo_codigo": "04", "subgrupo_codigo": "01", "mo_codigo": "MO03", "base": "unidade", "horas": 0.005},
        ]),
        "produtos": df([
            {"codigo": "P001", "descricao": "Armário aéreo 80cm", "grupo_codigo": "01", "subgrupo_codigo": "01", "unidade": "un", "margem_desejada_pct": 15.0, "volume_mensal": 60, "preco_atual": 520.0},
            {"codigo": "P002", "descricao": "Gaveteiro 3 gavetas", "grupo_codigo": "02", "subgrupo_codigo": "01", "unidade": "un", "margem_desejada_pct": None, "volume_mensal": 40, "preco_atual": 450.0},
            {"codigo": "P101", "descricao": "Recorte impresso 15×15 cm", "grupo_codigo": "04", "subgrupo_codigo": "01",
             "largura_cm": 15, "altura_cm": 15, "unidade": "un", "margem_desejada_pct": 20.0, "volume_mensal": 2000, "preco_atual": None},
            {"codigo": "P102", "descricao": "Recorte impresso 10×10 cm", "grupo_codigo": "04", "subgrupo_codigo": "01",
             "largura_cm": 10, "altura_cm": 10, "unidade": "un", "margem_desejada_pct": 20.0, "volume_mensal": 3000, "preco_atual": None},
            {"codigo": "P103", "descricao": "Recorte impresso 20×30 cm", "grupo_codigo": "04", "subgrupo_codigo": "01",
             "largura_cm": 20, "altura_cm": 30, "unidade": "un", "margem_desejada_pct": 20.0, "volume_mensal": 800, "preco_atual": None},
            {"codigo": "P003", "descricao": "Nicho decorativo", "grupo_codigo": "03", "subgrupo_codigo": "01", "unidade": "un", "margem_desejada_pct": 25.0, "volume_mensal": 120, "preco_atual": 95.0},
        ]),
        "composicao": df([
            {"produto_codigo": "P001", "mp_codigo": "FRT01", "quantidade": 1, "perda_pct": 0.0},
            {"produto_codigo": "P001", "mp_codigo": "MP01", "quantidade": 2.4, "perda_pct": 12.0},
            {"produto_codigo": "P001", "mp_codigo": "MP02", "quantidade": 4, "perda_pct": 0.0},
            {"produto_codigo": "P001", "mp_codigo": "MP03", "quantidade": 9, "perda_pct": 10.0},
            {"produto_codigo": "P001", "mp_codigo": "MP04", "quantidade": 2, "perda_pct": 0.0},
            {"produto_codigo": "P001", "mp_codigo": "MP05", "quantidade": 1, "perda_pct": 0.0},
            {"produto_codigo": "P002", "mp_codigo": "FRT01", "quantidade": 1, "perda_pct": 0.0},
            {"produto_codigo": "P002", "mp_codigo": "MP01", "quantidade": 2.0, "perda_pct": 12.0},
            {"produto_codigo": "P002", "mp_codigo": "MP03", "quantidade": 8, "perda_pct": 10.0},
            {"produto_codigo": "P002", "mp_codigo": "MP04", "quantidade": 3, "perda_pct": 0.0},
            {"produto_codigo": "P002", "mp_codigo": "MP05", "quantidade": 1, "perda_pct": 0.0},
            {"produto_codigo": "P003", "mp_codigo": "FRT01", "quantidade": 1, "perda_pct": 0.0},
            {"produto_codigo": "P003", "mp_codigo": "MP01", "quantidade": 0.35, "perda_pct": 15.0},
            {"produto_codigo": "P003", "mp_codigo": "MP03", "quantidade": 2, "perda_pct": 10.0},
        ]),
        "produto_mao_de_obra": df([
            {"produto_codigo": "P001", "mo_codigo": "MO01", "horas": 2.0},
            {"produto_codigo": "P001", "mo_codigo": "MO02", "horas": 0.5},
            {"produto_codigo": "P002", "mo_codigo": "MO01", "horas": 2.5},
            {"produto_codigo": "P002", "mo_codigo": "MO02", "horas": 1.0},
            {"produto_codigo": "P003", "mo_codigo": "MO01", "horas": 0.5},
        ]),
        "concorrentes": df([
            {"produto_codigo": "P001", "concorrente": "Concorrente X", "preco": 589.0, "data_coleta": "2026-11-01"},
            {"produto_codigo": "P001", "concorrente": "Concorrente Y", "preco": 545.0, "data_coleta": "2026-11-03"},
            {"produto_codigo": "P002", "concorrente": "Concorrente X", "preco": 479.0, "data_coleta": "2026-11-01"},
            {"produto_codigo": "P002", "concorrente": "Concorrente Z", "preco": 510.0, "data_coleta": "2026-11-05"},
            {"produto_codigo": "P003", "concorrente": "Concorrente Y", "preco": 89.9, "data_coleta": "2026-11-03"},
            {"produto_codigo": "P101", "concorrente": "Gráfica concorrente", "preco": 3.50, "data_coleta": "2026-11-20"},
        ]),
    }
    parametros = {
        "margem_padrao_pct": 12.0,
        "metodo_rateio": "percentual_faturamento",
        "faturamento_mensal_previsto": 75000.0,
        "tolerancia_concorrencia_pct": 5.0,
    }
    return dados, parametros
