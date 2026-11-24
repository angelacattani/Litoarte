# Litoarte v2 — Composição de Custos e Formação de Preço de Venda

> Branch `v2` em desenvolvimento. A versão em uso (v1, Streamlit) continua na branch `main`.

Especificação completa: [docs/especificacao_v2.md](docs/especificacao_v2.md) (modelo de dados,
fluxo de telas e motor de precificação).

## Situação

| Fase | Conteúdo | Situação |
|---|---|---|
| 1 | Schema relacional + migrações (Alembic) + motor de precificação + testes | ✅ concluída |
| 2 | Cadastros base (CRUD) + importação/modelos CSV/XLSX | ⏳ |
| 3 | Tela de Composição (NiceGUI) + simulador + clonagem | ⏳ |
| 4 | Cascata/relatório de impacto, lista de produtos, exportações | ⏳ |

## Estrutura

```
litoarte/
├── config.py               URL do banco (LITOARTE_DB_URL; padrão SQLite local)
├── db.py                   engine, sessões, transação; FKs ligadas no SQLite
├── migracoes.py            atualizar_banco(): aplica as migrações por código
├── migrations/             Alembic: 0001 schema · 0002 dados de referência
└── domain/
    ├── models.py           17 tabelas, CHECK/UNIQUE/FK, histórico automático de custos
    ├── pricing/            motor puro: engine.py (seção 3) e encaixe.py (peças por folha)
    └── services/
        └── precificacao.py banco → motor; cálculo por produto/todos; produtos afetados
tests/                      motor (exemplo de aceite 3.9) + banco (integridade, cascata)
```

## Desenvolvimento

```bash
./setup.sh                      # cria .venv e instala (Windows: setup.ps1)
source .venv/bin/activate
pytest -q                       # SQLite
```

Mesmos testes em PostgreSQL (cria e apaga um banco por teste):

```bash
LITOARTE_TEST_PG="postgresql+psycopg://usuario@servidor:5432/postgres" pytest -q
```

Criar/atualizar o banco de uso:

```bash
python -c "from litoarte.migracoes import atualizar_banco; atualizar_banco()"
```

Para PostgreSQL, defina `LITOARTE_DB_URL=postgresql+psycopg://usuario:senha@servidor:5432/litoarte`
e instale o extra: `pip install -e ".[postgres]"`.

## Regras do motor (resumo)

```
P = (CD + CFu + CVfixo) / (1 − (%CV + %CF + %ML))
```

- custo de material por unidade de consumo = custo de compra ÷ fator de conversão;
- quantidade fixa, por área, por perímetro ou por aproveitamento de folha;
- perda parametrizável: `sobre_compra` q/(1−p) ou `acrescimo` q·(1+p);
- custo fixo: % do faturamento (denominador) ou por hora produtiva/unidade (numerador);
- custos de produto **não são gravados**: qualquer alteração de cadastro reflete em todos os
  produtos no próximo cálculo; reajustes de insumo e mão de obra ficam no histórico.
