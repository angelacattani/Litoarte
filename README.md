# Litoarte v2 — Composição de Custos e Formação de Preço de Venda

> Versão 2. A versão anterior (v1, Streamlit) está preservada no histórico, no commit
> [`70b05b7`](https://github.com/angelacattani/Litoarte/tree/70b05b7) (Code → Download ZIP nessa página).

Especificação completa: [docs/especificacao_v2.md](docs/especificacao_v2.md) (modelo de dados,
fluxo de telas e motor de precificação).

## Situação

| Fase | Conteúdo | Situação |
|---|---|---|
| 1 | Schema relacional + migrações (Alembic) + motor de precificação + testes | ✅ concluída |
| 2 | Cadastros base (CRUD) + importação/modelos CSV/XLSX + interface NiceGUI | ✅ concluída |
| 3 | Tela de Composição (NiceGUI) + simulador + clonagem | ✅ concluída |
| 4 | Relatório de impacto, histórico de custos, exportações, revisão final | ✅ concluída |

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
- **5 preços**: cada produto tem cinco faixas de preço (nomes e margens gerais em *Configuração*, ex.:
  Atacado 10 %, Revenda 15 %, Loja 20 %, Varejo 25 %, Premium 30 %). Para cada faixa: **preço aplicado**
  (o que você pratica hoje, editável para substituir) e a **margem real** que ele rende sobre o custo
  calculado, em vermelho quando abaixo da margem da faixa. Os preços calculados ficam ocultos e aparecem
  com a chave "mostrar preços calculados", com botão para usar o calculado como aplicado. Margem própria
  do produto por faixa é opcional.
- **Custo atual × calculado**: o custo que você usa hoje (campo *custo atual*) comparado ao custo da
  ficha técnica (materiais + mão de obra), com a diferença em R$ e %.
- **Concorrência**: preços de concorrentes do grupo do produto (nível produto → subgrupo → grupo), com
  mínimo, mediana e máximo; **Buscar na web** (Mercado Livre ou Google Shopping) e registro manual.

Campos numéricos aceitam o formato brasileiro (`139,90`, `1.234,56`) e também `139.90`.
Ao sair da composição com alterações não salvas, o navegador pede confirmação.

### Substituir preços em massa

*Produtos → Substituir preços*: escolha as faixas e o arredondamento (centavos, terminar em ,90 ou real
inteiro); a prévia mostra preço aplicado hoje → novo para os produtos da lista (respeita os filtros).
Também pela planilha de produtos: `custo_atual` e `preco_faixa_1` … `preco_faixa_5` (`remover` apaga).

### Concorrentes e busca de preços na web

*Concorrentes* (menu): cadastro de concorrentes associados aos grupos em que concorrem e preços de
produtos similares (grupo, opcionalmente subgrupo ou produto equivalente), com importação/exportação.
**Buscar na web** consulta o Mercado Livre (API oficial) ou o Google Shopping (via SerpApi), mostra
os resultados com mínimo/mediana/máximo (opção de ocultar extremos) e grava **só os itens marcados**.
Credenciais em *Configuração → Busca de preços na web*: Client ID/Secret de uma aplicação gratuita do
Mercado Livre (o token é obtido e renovado automaticamente; também aceita um access token colado) e a
chave da SerpApi. As credenciais ficam apenas no banco local.

### Reajustes e relatórios

- **Relatório de impacto**: ao salvar um novo custo de matéria-prima ou de mão de obra (na tela ou
  por importação), o sistema lista os produtos afetados com preço sugerido antes → depois, variação,
  e margem real no preço praticado antes → depois, destacando os que ficam abaixo da margem
  desejada. O preço praticado nunca é alterado automaticamente. Exportável em XLSX.
- **Histórico de custos** (menu): todos os reajustes de insumos e mão de obra, com data, valor
  anterior, novo, variação e origem (manual/importação).
- **Exportações** (Produtos → Planilhas): *tabela de preços* (custos, parcelas do preço, preço
  sugerido, mínimo, praticado, margem real e **preço sugerido em cada perfil de venda**) e
  *composição detalhada* (cada linha da ficha técnica de cada produto com quantidade efetiva,
  perda, custo unitário e custo).
- **Início**: total de produtos ativos e quantos estão com margem abaixo da desejada.

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
├── planilhas/              leitura XLSX/CSV, modelos/exportação, importação, relatórios XLSX
├── busca/                  provedores de preço na web: Mercado Livre, Google Shopping (SerpApi)
└── domain/
    ├── models.py           17 tabelas, CHECK/UNIQUE/FK, histórico automático de custos
    ├── pricing/            motor puro: engine.py (seção 3) e encaixe.py (peças por folha)
    └── services/
        ├── cadastros.py    definição declarativa dos módulos + validação/gravação únicas
        ├── valores.py      números BR, sim/não, opções
        ├── perfis.py       perfis de venda (canais)
        ├── configuracao.py rateio, margem, perda
        ├── composicao.py   rascunho, cálculo em tempo real, gravação, clonagem, canais, lista
        ├── impacto.py      preços antes/depois de um reajuste (atualização em cascata)
        ├── faixas.py       5 preços: margens, preços aplicados, margem real, arredondamento
        ├── concorrencia.py concorrentes por grupo, preços coletados, busca web (sem banco)
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
