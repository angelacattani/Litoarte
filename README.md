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

O banco `custos.db` é criado na própria pasta (ou no caminho da variável
`CUSTOS_DB`). Em **⚙ Parâmetros → Carregar base de exemplo** há uma
marcenaria fictícia para explorar o sistema.

Testes (com o `.venv` ativo): `pytest -q`

## Funcionalidades

| Módulo | Conteúdo |
|---|---|
| Matérias-primas | código, descrição, unidade, custo unitário, fornecedor |
| Mão de obra direta | salário, encargos %, horas produtivas/mês, nº de funcionários → custo-hora |
| Custos fixos | valores mensais por categoria |
| Custos variáveis | **percentual** sobre o preço (impostos, comissão, cartão) ou **unitário** em R$/un (frete, embalagem avulsa) |
| Produtos | margem desejada (ou padrão), volume mensal previsto, preço atual praticado |
| Ficha técnica | consumo de MP por unidade com % de perda; horas de MO por função |
| Concorrentes | preço por produto e concorrente, com data de coleta |
| Painel | preço sugerido, mínimo, cobertura, markup, MC, posição vs. concorrência, alertas, DRE projetada, ponto de equilíbrio, ocupação da MO |
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
  `custos_fixos`, `custos_variaveis`, `produtos`, `composicao`,
  `produto_mao_de_obra`, `concorrentes` (baixe a planilha-modelo no app; a
  aba `instrucoes` descreve cada coluna). O arquivo exportado pelo sistema
  pode ser reimportado diretamente.
- **CSV**: uma tabela por arquivo; separador `;` ou `,`; números `1.234,56`
  ou `1234.56`; UTF-8 ou Latin-1. Nomes de coluna comuns são reconhecidos
  (`SKU`, `Produto`, `Nome`, `Preço Venda`, `Custo (R$)`...).
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
│   ├── repositorio.py     persistência SQLite (salvar, mesclar, importar)
│   ├── calculo.py         MotorCustos: preço, margens, concorrência, resumo
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
