# Sistema de Custos e Formação de Preço de Venda

Projeto independente: Python + SQLite + Streamlit, com ambiente virtual
próprio (`.venv`) e porta própria (8502), isolado de outros projetos.

## Instalação (ambiente isolado)

Linux / macOS:

```bash
./setup.sh
source .venv/bin/activate
streamlit run app_custos.py
```

Windows — forma mais simples: **duplo clique em `iniciar.bat`**. Na primeira
execução ele cria o `.venv` e instala as dependências (alguns minutos); nas
seguintes, abre o sistema direto no navegador. Para encerrar, feche a janela
preta do terminal.

Windows pelo PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\Activate.ps1
streamlit run app_custos.py
```

Pré-requisitos no Windows: [Python 3.11+](https://www.python.org/downloads/)
(marque *Add python.exe to PATH* na instalação) e, para clonar,
[Git for Windows](https://git-scm.com/download/win) — ou baixe o ZIP pelo
botão *Code → Download ZIP* no GitHub.

O app abre em http://localhost:8502.

O banco `custos.db` é criado na própria pasta. Para compartilhá-lo, veja
*Banco de dados compartilhado*. Em **⚙ Parâmetros → Carregar base de exemplo** há uma
marcenaria fictícia para explorar o sistema.

Testes (com o `.venv` ativo): `pytest -q`

## Banco de dados compartilhado

Produtos, matérias-primas, custos, concorrentes e parâmetros ficam num banco
**SQLite** (arquivo `custos.db`). Por padrão ele é criado na pasta do sistema;
para que vários computadores usem os mesmos dados, coloque-o numa **pasta
compartilhada**:

1. No computador que já tem os dados, abra **🗄 Banco de dados**, informe a
   pasta (ex.: `\\SERVIDOR\Compartilhado\Litoarte`, `Z:\Litoarte` ou uma pasta
   do OneDrive) e escolha *Copiar para lá os dados deste computador*.
2. Nos demais computadores, informe a mesma pasta. Como o banco já existe,
   ele é usado sem cópia.

O caminho escolhido fica em `config_local.json`, que é de cada máquina e não
vai para o Git. A variável de ambiente `CUSTOS_DB`, se definida, tem
prioridade.

**Um editor por vez.** O SQLite não é confiável com gravações simultâneas
pela rede. Por isso, quem abre primeiro recebe a trava de edição
(`custos.db.lock`) e os demais ficam em **modo leitura**: veem preços,
relatórios e exportações, mas não gravam. A barra lateral mostra quem está
editando. A trava é liberada pelo botão *Liberar edição* ou expira após
15 minutos sem uso, e pode ser forçada se a pessoa já fechou o sistema.

**Backups.** Um backup automático por dia, feito na primeira abertura em
modo edição, vai para `backups/` ao lado do banco, mantendo os 30 mais
recentes. A mesma página permite fazer backup na hora e baixar uma cópia do
`.db`.

> Em pastas do OneDrive/Dropbox, espere a sincronização terminar depois que
> a outra pessoa liberar a edição; editar antes disso gera cópias em
> conflito do arquivo.

## Ficha técnica por subgrupo e dimensões

A ficha padrão do **subgrupo** vale para todos os produtos dele; o que muda
entre eles são as **dimensões** (largura × altura, cm). Cada item tem uma
base de cálculo:

| Base | Consumo por unidade de produto |
|---|---|
| `unidade` | quantidade |
| `area` | quantidade × área do produto (m²) |
| `perimetro` | quantidade × perímetro do produto (m) |
| `aproveitamento` | quantidade ÷ peças por folha (dimensões da matéria-prima) |

Peças por folha: `⌊(útil + e)/(peça + e)⌋` em cada direção, sendo
útil = dimensão da folha − 2 × margem e e = espaço entre peças. São testadas
as duas orientações, e a sobra é aproveitada com peças giradas.

| `area_impressa` | quantidade × área (m²) × cobertura de tinta do produto (%) |

**Compra × consumo.** Insumos comprados em embalagem têm `conteudo` e
`unidade_consumo`: tinta em frasco de 1 L (conteúdo 1000, ml), cola em pote
de 1 kg (1000, g), fita em rolo de 30 m (30, m). A ficha informa o consumo
na unidade de consumo, e o custo usado é preço ÷ conteúdo. A **cobertura de
tinta** é cadastrada por produto (% da área impressa); vazio usa o padrão
dos Parâmetros.

Exemplo (base de demonstração, subgrupo *04 Papelaria › 01 Recortes
impressos*, impressão própria), recorte 15 × 15 cm com 60 % de cobertura:

| Item | Base | Consumo | Custo |
|---|---|---|---|
| Papel couché, folha 1 × 2 m a R$ 18 | aproveitamento | 1/78 folha (6 × 13; 87,75 %) + 5 % | R$ 0,2423 |
| Tinta, frasco 1 L a R$ 280 | area_impressa, 12 ml/m² | 0,0225 × 12 × 60 % = 0,162 ml + 10 % | R$ 0,0499 |
| Desgaste da impressora, R$ 3/m² | area | 0,0225 m² | R$ 0,0675 |
| Cola PVA, pote 1 kg a R$ 32 | area, 60 g/m² | 1,35 g + 5 % | R$ 0,0454 |
| Fita dupla-face, rolo 30 m a R$ 9,90 | perimetro, 0,25 | 0,15 m + 5 % | R$ 0,0520 |
| Corte em plotter, R$ 0,15/m | perimetro | 0,6 m | R$ 0,0900 |
| Saquinho celofane, R$ 0,12 | unidade | 1 + 2 % | R$ 0,1224 |
| **Total de materiais** | | | **R$ 0,6694** |

Na ficha do produto, uma linha com o mesmo item **substitui** a do
subgrupo, e **quantidade 0 exclui** o item herdado. Abas de importação:
`composicao_subgrupo` e `mo_subgrupo` (grupo_codigo, subgrupo_codigo,
item, base, quantidade/horas...). A coluna `base` também aceita `folha`,
`chapa`, `m²`, `m`, `linear`.

## Funcionalidades

| Módulo | Conteúdo |
|---|---|
| Matérias-primas, insumos e serviços | código, descrição, unidade, custo unitário, dimensões de folha/chapa (largura × comprimento, margem), fornecedor |
| Mão de obra direta | salário, encargos %, horas produtivas/mês, nº de funcionários → custo-hora |
| Custos fixos | valores mensais por categoria |
| Custos variáveis | **percentual** sobre o preço (impostos, comissão, cartão) ou **unitário** em R$/un (frete, embalagem avulsa) |
| Grupos e subgrupos | código + descrição; subgrupo com código único dentro do grupo; contagem de produtos; troca de código em cascata |
| Produtos | vínculo por código de grupo e subgrupo, dimensões (largura × altura em cm), margem desejada (ou padrão), volume mensal previsto, preço atual praticado |
| Ficha técnica | **padrão por subgrupo** + ajustes por produto; consumo por unidade, área, perímetro ou aproveitamento de folha; % de perda; horas de MO por unidade, m² ou metro |
| Concorrentes | preço por produto e concorrente, com data de coleta |
| Painel | resultado por grupo/subgrupo (faturamento, MC, lucro, participação), filtro por grupo, preço sugerido, mínimo, cobertura, markup, MC, posição vs. concorrência, alertas, DRE projetada, ponto de equilíbrio, ocupação da MO |
| Simulador | margem líquida, lucro e MC para qualquer preço |
| Importar/Exportar | XLSX completo (todas as tabelas + parâmetros + relatório), CSV por tabela, planilha-modelo |

## Método de cálculo — markup divisor

```
CD  = Σ MP·(1+perda%)·custo  +  Σ horas·custo-hora  +  Σ variáveis R$/un
CFu = fixo rateado por unidade (métodos "por hora de MO" ou "por unidade")
MD  = 1 − (%CV + %CF + %ML)/100
P   = (CD + CFu) / MD
```

Rateio dos fixos (parâmetro):

- **% sobre faturamento previsto** — `%CF = fixos ÷ faturamento previsto`;
- **por hora de MO** — `taxa = fixos ÷ Σ(volume × horas)` previstas;
- **por unidade** — `taxa = fixos ÷ Σ volume`.

Indicadores: preço mínimo (lucro zero), preço de cobertura (MC = 0, piso de
curto prazo), margem líquida no preço atual e na média da concorrência,
ociosidade da MO (folha não absorvida pelos volumes) e ponto de equilíbrio
em faturamento.

> Não lance em *custos fixos* os salários da MO direta já cadastrada em
> *Mão de obra* — haveria dupla contagem.

## Importação de dados existentes

- **XLSX**: uma aba por tabela, com os nomes `materias_primas`, `mao_de_obra`,
  `custos_fixos`, `custos_variaveis`, `grupos`, `subgrupos`, `produtos`, `composicao`,
  `produto_mao_de_obra`, `concorrentes` (baixe a planilha-modelo no app; a
  aba `instrucoes` descreve cada coluna). O arquivo exportado pelo sistema
  pode ser reimportado diretamente.
- **CSV**: uma tabela por arquivo; separador `;` ou `,`; números `1.234,56`
  ou `1234.56`; UTF-8 ou Latin-1. Nomes de coluna comuns são reconhecidos
  (`SKU`, `Produto`, `Nome`, `Preço Venda`, `Custo (R$)`...).
- **Grupo e subgrupo do produto** — o produto guarda os códigos
  (`grupo_codigo`, `subgrupo_codigo`; também aceitos *Cód. Grupo*,
  *Cod_Subgrupo* etc.). A planilha de produtos pode trazer:
  - **códigos** — usados diretamente; código inexistente cria o grupo/subgrupo
    com o nome da planilha (ou "Grupo 05");
  - **só nomes** (*Grupo*, *Família*, *Linha*, *Categoria* / *Subgrupo*,
    *Subcategoria*...) — localizados pela descrição cadastrada, sem diferenciar
    maiúsculas e espaços; se não existirem, são criados com o próximo código;
  - **nada** — o produto vai para `00 Sem grupo › 00 Geral`.

  Códigos numéricos que o Excel converteu em número (1 em vez de 01) casam
  com o código cadastrado. Para importar a estrutura completa, use as abas
  `grupos` (codigo, descricao) e `subgrupos` (grupo_codigo, codigo, descricao).
- Modos: **mesclar** (upsert pela chave) ou **substituir**.
- Linhas inválidas (campo obrigatório vazio, número negativo, referência a
  código inexistente) são descartadas e listadas no aviso de importação.

## Estrutura

```
sistema-custos/
├── pyproject.toml         pacote + dependências
├── iniciar.bat            Windows: duplo clique para instalar e abrir
├── setup.sh / setup.ps1   criação do ambiente virtual
├── app_custos.py          interface Streamlit
├── custos/
│   ├── modelos.py         esquemas das tabelas, parâmetros, aliases de colunas
│   ├── validacao.py       normalização, conversão numérica BR, integridade referencial
│   ├── repositorio.py     persistência SQLite (salvar, mesclar, importar, backup)
│   ├── configuracao.py    local do banco por máquina (config_local.json)
│   ├── trava.py           trava de edição para banco em pasta compartilhada
│   ├── calculo.py         MotorCustos: preço, margens, concorrência, resumo
│   ├── dimensoes.py       peças por folha (encaixe) e ficha efetiva subgrupo + produto
│   ├── importexport.py    XLSX/CSV, relatório, planilha-modelo
│   └── exemplo.py         base de demonstração
└── tests/test_custos.py
```

Uso programático:

```python
from custos import Repositorio, MotorCustos
repo = Repositorio("custos.db")
motor = MotorCustos(repo.carregar_tudo(), repo.parametros())
motor.tabela_precos()          # DataFrame com todos os indicadores
motor.simular("P001", 550.0)   # what-if de preço
motor.resumo().lucro_projetado
```
