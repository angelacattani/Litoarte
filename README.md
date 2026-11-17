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

## Funcionalidades

| Módulo | Conteúdo |
|---|---|
| Matérias-primas | código, descrição, unidade, custo unitário, fornecedor |
| Mão de obra direta | salário, encargos %, horas produtivas/mês, nº de funcionários → custo-hora |
| Custos fixos | valores mensais por categoria |
| Custos variáveis | **percentual** sobre o preço (impostos, comissão, cartão) ou **unitário** em R$/un (frete, embalagem avulsa) |
| Grupos e subgrupos | cadastro hierárquico (grupo › subgrupo), contagem de produtos, renomear/unificar |
| Produtos | grupo › subgrupo, margem desejada (ou padrão), volume mensal previsto, preço atual praticado |
| Ficha técnica | consumo de MP por unidade com % de perda; horas de MO por função |
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
  `custos_fixos`, `custos_variaveis`, `grupos`, `produtos`, `composicao`,
  `produto_mao_de_obra`, `concorrentes` (baixe a planilha-modelo no app; a
  aba `instrucoes` descreve cada coluna). O arquivo exportado pelo sistema
  pode ser reimportado diretamente.
- **CSV**: uma tabela por arquivo; separador `;` ou `,`; números `1.234,56`
  ou `1234.56`; UTF-8 ou Latin-1. Nomes de coluna comuns são reconhecidos
  (`SKU`, `Produto`, `Nome`, `Preço Venda`, `Custo (R$)`...).
- **Grupo e subgrupo do produto**: colunas `grupo` e `subgrupo` (também
  aceitas: *Família*, *Linha*, *Categoria*, *Departamento* / *Sub-grupo*,
  *Subcategoria*, *Subfamília*). Grupos inexistentes são criados
  automaticamente; grafias equivalentes (`cozinha`, ` COZINHA `) são
  unificadas na já cadastrada. Produto sem grupo recebe *Sem grupo › Geral*.
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
