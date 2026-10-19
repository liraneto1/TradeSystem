# TradeSystem

Agente local de pesquisa para Binance Futuros. **Versão 0.1: somente simulação offline.**

## Requisitos definidos

- Capital de referência: US$ 100 (simulação usa 100 USDT; paridade não é garantida).
- Alavancagem máxima: 10x. A demonstração usa 2x.
- Execução automática como objetivo da etapa 2; execução local.
- Kronos como candidato a componente de previsão.

## Executar no Windows

Instale Python 3.11 ou superior. Na pasta do repositório:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m tradesystem
```

A base não exige pacotes externos. Os preços e filtros da demonstração são fictícios.

## Política experimental

`config/paper.json` contém valores iniciais de pesquisa, ainda sujeitos a validação:

- Risco estimado por operação: 0,5% do patrimônio, incluindo custos estimados.
- Limite de perda diária: 2% do capital inicial; o chamador fornece o PnL diário líquido.
- Margem inicial e custo estimado de entrada: até 20% do patrimônio.
- Taxa de 0,05% e slippage de 0,02% por lado: hipóteses, não tarifas verificadas da conta.
- Uma posição por vez. Se o lote mínimo exceder o orçamento, a operação é rejeitada.

O stop é usado no dimensionamento. Esta versão não monitora preços nem instala stops na corretora.
Perdas reais podem exceder estimativas por gaps, slippage e liquidação.

## Arquitetura e próximos incrementos

1. **Implementado:** configuração, dimensionamento Decimal, filtros fornecidos pelo chamador,
   simulação de abertura/fechamento e testes de risco e contabilidade.
2. **Implementado:** coleta pública USDⓈ-M, candles fechados, filtros reais, armazenamento e validação temporal.
3. **Implementado:** adaptador Kronos com revisão fixa de código/pesos e avaliação temporal contra persistência.
4. Backtest temporal: taxas, funding, slippage, margem e liquidação; prevenção de vazamento.
5. Demo Binance: reconciliação persistente, ordens idempotentes, stops na corretora,
   recuperação após reinício, perda diária persistente e parada de emergência.
6. Operação real limitada após validação e definição final dos parâmetros.

BTCUSDT, candles de 15 minutos e USDⓈ-M são propostas iniciais, não requisitos confirmados.
Não há execução Binance, credenciais, HMM ou estratégia lucrativa validada nesta versão.

## Coletar dados reais (somente leitura)

```powershell
.\.venv\Scripts\python.exe -m tradesystem.market --symbol BTCUSDT --interval 15m --count 400 --output data/btc-15m-001
```

Requer internet e disponibilidade regional da API pública. Não requer chave de API.
Usa o relógio do servidor para excluir o candle em formação, pagina até 10.000 candles e rejeita
lacunas, duplicatas, OHLC inválido e respostas incompletas. Intervalos: 1m, 5m, 15m e 1h.
O diretório de saída deve ser novo; contém `candles.csv` e `metadata.json`, com procedência,
horário e snapshot das regras do contrato. Timestamps são Unix em milissegundos UTC.
`amount` representa volume cotado da Binance. Os dados ficam ignorados pelo Git.
Em erros HTTP/restrições/limites a coleta para, sem tentar contornar restrições da Binance.
Os filtros LOT_SIZE e MIN_NOTIONAL são para pesquisa; execução exigirá também PRICE_FILTER,
MARKET_LOT_SIZE, quantidades máximas e demais regras aplicáveis ao tipo de ordem.

## Kronos local e avaliação de previsões

Instalação opcional no ambiente isolado, sem alterar a instalação global do Python:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements-kronos.txt
.\.venv\Scripts\python.exe -m tradesystem.kronos_setup
.\.venv\Scripts\python.exe -m tradesystem.forecast --dataset data/btc-15m-initial --lookback 128 --horizon 4 --windows 5 --output reports/kronos-initial
```

Instale os pacotes em sequência. A preparação requer internet, Git e espaço para PyTorch e pesos.
As revisões imutáveis constam em `config/kronos.lock.json`. O código original é clonado somente
em `.vendor/Kronos`, com licença MIT preservada; não é modificado nem enviado ao repositório
original. Pesos públicos são baixados com autenticação desativada para `models/`, com registro
local SHA-256 de integridade. `.vendor/`, `models/`, `reports/` e `data/` não são publicados.
Após preparação, a inferência usa pesos locais, CPU, seed 42 e uma trajetória por previsão.
O ambiente e as dependências transitivas também podem afetar a reprodução numérica.

A avaliação usa janelas cronológicas com alvos sem sobreposição. Apenas o histórico anterior
é entregue ao modelo. O benchmark de persistência prevê o último fechamento para todo o horizonte.
`predictions.csv` e `metrics.json` registram previsões, MAE, parâmetros, procedência dos dados
e revisões utilizadas. O erro é expresso em unidades de preço USDT, não em lucro da estratégia.
Esta amostra pequena não demonstra vantagem persistente nem rentabilidade. Ainda não foi
auditada possível sobreposição com dados de pré-treino; isso não é um teste totalmente fora
da amostra de treinamento do modelo. Não há ajuste fino ou escolha automática de estratégia.

## Segurança e limites

Nunca versionar chaves, tokens, `.env`, dados de conta ou modelos baixados.
O simulador não representa funding, liquidação, marcação a mercado, execução parcial ou gaps.
`PaperBroker` recebe planos do motor de risco; não substitui uma fronteira de execução validada.

## Referências

- https://github.com/shiyu-coder/Kronos
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info

A cópia local do Kronos e os pesos não fazem parte dos arquivos versionados do TradeSystem.
