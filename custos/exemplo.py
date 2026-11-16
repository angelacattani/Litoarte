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
        ]),
        "mao_de_obra": df([
            {"codigo": "MO01", "funcao": "Marceneiro", "salario_mensal": 3200.0, "encargos_pct": 70.0, "horas_produtivas_mes": 160.0, "quantidade": 2},
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
            {"codigo": "CV04", "descricao": "Frete médio por unidade", "tipo": "unitario", "valor": 15.0},
        ]),
        "produtos": df([
            {"codigo": "P001", "descricao": "Armário aéreo 80cm", "unidade": "un", "margem_desejada_pct": 15.0, "volume_mensal": 60, "preco_atual": 520.0},
            {"codigo": "P002", "descricao": "Gaveteiro 3 gavetas", "unidade": "un", "margem_desejada_pct": None, "volume_mensal": 40, "preco_atual": 450.0},
            {"codigo": "P003", "descricao": "Nicho decorativo", "unidade": "un", "margem_desejada_pct": 25.0, "volume_mensal": 120, "preco_atual": 95.0},
        ]),
        "composicao": df([
            {"produto_codigo": "P001", "mp_codigo": "MP01", "quantidade": 2.4, "perda_pct": 12.0},
            {"produto_codigo": "P001", "mp_codigo": "MP02", "quantidade": 4, "perda_pct": 0.0},
            {"produto_codigo": "P001", "mp_codigo": "MP03", "quantidade": 9, "perda_pct": 10.0},
            {"produto_codigo": "P001", "mp_codigo": "MP04", "quantidade": 2, "perda_pct": 0.0},
            {"produto_codigo": "P001", "mp_codigo": "MP05", "quantidade": 1, "perda_pct": 0.0},
            {"produto_codigo": "P002", "mp_codigo": "MP01", "quantidade": 2.0, "perda_pct": 12.0},
            {"produto_codigo": "P002", "mp_codigo": "MP03", "quantidade": 8, "perda_pct": 10.0},
            {"produto_codigo": "P002", "mp_codigo": "MP04", "quantidade": 3, "perda_pct": 0.0},
            {"produto_codigo": "P002", "mp_codigo": "MP05", "quantidade": 1, "perda_pct": 0.0},
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
        ]),
    }
    parametros = {
        "margem_padrao_pct": 12.0,
        "metodo_rateio": "percentual_faturamento",
        "faturamento_mensal_previsto": 75000.0,
        "tolerancia_concorrencia_pct": 5.0,
    }
    return dados, parametros
