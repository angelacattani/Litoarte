# Litoarte v2 — Composição de Custos e Formação de Preço de Venda

> Branch `v2` em desenvolvimento. A versão em uso (v1, Streamlit) continua na branch `main`.

Especificação completa: [docs/especificacao_v2.md](docs/especificacao_v2.md) (modelo de dados,
fluxo de telas e motor de precificação).

## Situação

| Fase | Conteúdo | Situação |
|---|---|---|
| 1 | Schema relacional + migrações (Alembic) + motor de precificação + testes | ✅ concluída |
| 2 | Cadastros base (CRUD) + importação/modelos CSV/XLSX + interface NiceGUI | ✅ concluída |
| 3 | Tela de Composição (NiceGUI) + simulador + clonagem | ✅ concluída |
| 4 | Cascata/relatório de impacto, lista de produtos, exportações | ⏳ |

## Como usar (Windows)

Dê **duplo clique em `iniciar.bat`**. Na primeira vez ele cria o ambiente e instala as dependências
(alguns minutos); depois abre o sistema no navegador em `http://localhost:8503`. Para encerrar,
feche a janela preta. O banco `litoarte.db` fica na pasta do sistema (ou em `LITOARTE_DB_URL`).

Linux/macOS: `./setup.sh && .venv/bin/python -m litoarte`.

### Telas disponíveis (fase 2)

| Tela | Conteúdo |
|---|---|
| Início | totais e checklist de implantação |
| Matérias-primas | SKU, unidade de compra e de consumo, conversão, custo, perda, fornecedor, dimensões de folha |
| Mão de obra | etapa, custo por hora **ou** por minuto (sincronizados) ou salário + encargos ÷ horas |
| Custos fixos | itens mensais + **custo fixo total** e absorção (%CF, R$/h ou R$/un) |
| Custos variáveis | impostos, cartão, comissões, marketplace, frete (% ou R$) + **perfis de venda** por canal |
| Grupos e subgrupos | dois níveis, código do subgrupo único dentro do grupo |
| Unidades, Fornecedores | cadastros de apoio |
| Configuração | método de rateio, faturamento base, capacidades, margem padrão, modo de perda |
| **Produtos** | lista com filtros (grupo, subgrupo, margem abaixo), custo direto, preço sugerido, preço praticado, margem real; abrir, **duplicar**, excluir; planilhas de produtos e fichas |
| **Composição de preço** | ficha técnica (materiais e mão de obra) com custo por linha; formação do preço, simulador e comparativo por canal **em tempo real**, antes de salvar |

### Composição de preço

- Cabeçalho: SKU, nome, grupo › subgrupo, largura/altura, perfil de venda, margem desejada
  (vazio = padrão) e preço praticado.
- **Materiais**: insumo (busca por SKU/nome), modo (fixa, por área, por perímetro, aproveitamento de
  folha), quantidade na unidade de consumo, perda própria (vazio = perda do insumo), espaçamento no
  aproveitamento; mostra o custo de cada linha e, nas folhas, peças por folha e aproveitamento.
- **Mão de obra**: etapa, tempo em minutos ou horas, custo de cada linha.
- **Formação do preço**: materiais, mão de obra, custo direto, custo fixo, custos variáveis, lucro,
  preço sugerido, markup, preço mínimo e de cobertura, margem no preço praticado e alertas.
- **Simulador**: margem por controle deslizante (preço, lucro, margem de contribuição, ponto de
  equilíbrio) com "aplicar ao produto"; ou preço manual com o resultado e "usar como preço praticado".
- **Comparativo por canal**: preço sugerido e margem no preço praticado em cada perfil de venda.
- **Duplicar**: cria um produto com o mesmo subgrupo, ficha técnica, perfil e margem; permite trocar
  SKU, nome, subgrupo e medidas antes de abrir a cópia.

Campos numéricos aceitam o formato brasileiro (`139,90`, `1.234,56`) e também `139.90`.

Em toda tela de cadastro: busca, inativar/ativar, excluir (bloqueado se o item estiver em uso),
**Importar** (assistente), **Modelo** (planilha com instruções e listas de valores) e **Exportar**
(no mesmo formato do modelo: exporte, edite no Excel e reimporte).

### Importação

1. *Modelo* baixa a planilha com a aba `dados` (cabeçalhos) e `instrucoes`.
2. *Importar* → escolha o modo: incluir novos, atualizar existentes ou ambos.
3. Envie o .xlsx/.csv: a pré-visualização mostra cada linha como incluir / atualizar / ignorar /
   erro, com a coluna e o motivo do erro. **Nada é gravado** enquanto houver erro.
4. Confirme: gravação única (tudo-ou-nada), registro em log, histórico de custos e lista dos
   reajustes com os produtos afetados.

Cabeçalhos usuais são reconhecidos (`Código`, `Descrição`, `Custo (R$)`, `Perda (%)`...), números
em formato brasileiro (`1.234,56`) e CSV com `;` ou `,`. Na atualização, célula vazia não apaga o
valor cadastrado — para **reajustar preços** basta uma planilha com `sku` e `custo_compra`.

## Estrutura

```
litoarte/
├── config.py               URL do banco (LITOARTE_DB_URL; padrão SQLite local)
├── db.py                   engine, sessões, transação; FKs ligadas no SQLite
├── migracoes.py            atualizar_banco(): aplica as migrações por código
├── migrations/             Alembic: 0001 schema · 0002 dados de referência
├── app/                    interface NiceGUI: layout, telas, cadastro genérico, importação, composição
├── planilhas/              leitura XLSX/CSV, modelos/exportação, importação (analisar → aplicar)
└── domain/
    ├── models.py           17 tabelas, CHECK/UNIQUE/FK, histórico automático de custos
    ├── pricing/            motor puro: engine.py (seção 3) e encaixe.py (peças por folha)
    └── services/
        ├── cadastros.py    definição declarativa dos módulos + validação/gravação únicas
        ├── valores.py      números BR, sim/não, opções
        ├── perfis.py       perfis de venda (canais)
        ├── configuracao.py rateio, margem, perda
        ├── composicao.py   rascunho, cálculo em tempo real, gravação, clonagem, canais, lista
        └── precificacao.py banco → motor; cálculo por produto/todos; produtos afetados
tests/                      motor, banco, cadastros, importação e interface (simulação NiceGUI)
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
