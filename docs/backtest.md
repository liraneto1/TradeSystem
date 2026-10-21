# Backtest SMC exploratório

O motor roda localmente, sem conta ou chave Binance. Usa os candles históricos para sinais
e execução, mark-price OHLC para marcação a mercado e histórico real de funding.
O modelo ainda não é uma réplica da execução e da liquidação da Binance.

## Executar

```powershell
.\.venv\Scripts\python.exe -m tradesystem.market --symbol BTCUSDT --interval 15m --count 10000 --output data/btc-smc-novo
.\.venv\Scripts\python.exe -m tradesystem.futures_data --dataset data/btc-smc-novo
.\.venv\Scripts\python.exe -m tradesystem.backtest --dataset data/btc-smc-novo --output reports/smc-novo-2x
.\.venv\Scripts\python.exe -m tradesystem.backtest --dataset data/btc-smc-novo --config config/backtest-5x.json --output reports/smc-novo-5x
```

Use diretórios novos. A coleta falha em vez de contornar restrições HTTP da corretora.
O suplemento `futures.json` fica junto dos dados, com hash do CSV original. Os relatórios
registram também o hash do suplemento e todos os parâmetros.

## Dimensionamento e ordens

- Capital inicial 100 USDT, 0,5% de risco estimado por operação, teto de alavancagem 10x.
- O cenário principal usa 2x; o cenário adicional usa 5x, com os mesmos limites de risco.
  O cenário 5x foi definido antes da execução ampliada como diagnóstico de lotes mínimos,
  não como escolha da alavancagem mais lucrativa. Nenhuma mudança é aplicada à conta real.
- Uma posição ou uma ordem pendente por vez. Sinais surgidos enquanto ocupado são descartados.
- Quantidade fixada no fechamento do sinal e revalidada no preenchimento, sem aumento.
- Entrada limite, stop e alvo arredondados ao tick. Quantidade respeita LOT_SIZE,
  MIN_NOTIONAL e limite máximo de LOT_SIZE do snapshot. Não aumenta o risco para caber no lote.
- Custos por lado: taxa de 0,05% e slippage de 0,02%, debitados no caixa sobre o notional.
  São hipóteses, não as tarifas verificadas da conta. Não há melhoria de preço na entrada.
- Ordens começam somente depois do candle do sinal. A entrada exige toque no limite
  dentro da validade. Uma abertura além do extremo da varredura cancela a ordem.
- Expiração/invalidação sem execução não paga taxas. Ordens remanescentes são canceladas
  ao fim da amostra; posições remanescentes fecham a preço de fechamento, com custos.

## Convenções intrabar

OHLC não revela a ordem dos eventos dentro do candle. O motor usa escolhas conservadoras:

1. Se a liquidação modelada e o stop aparecem no mesmo candle, prioriza a liquidação.
2. Se stop e alvo são tocados, prioriza o stop.
3. No candle de entrada não reconhece alvo favorável, pois pode ter ocorrido antes do fill.
4. Stop com gap executa ao preço de abertura mais desfavorável. Alvo limita-se ao valor proposto.
5. Horários de entrada e saída nos CSVs identificam as barras, não timestamps exatos dos fills.

Funding é calculado por quantidade × mark price do evento × taxa, com sinal de long/short.
O coletor não presume frequência fixa. Eventos que ocorrem dentro do candle têm sequência
incerta em relação a fills e saídas: débitos possíveis são cobrados; créditos são reconhecidos
somente para posições carregadas e sem saída possível naquele intervalo. Para um evento
exatamente na abertura, a posição anterior participa; uma nova entrada nessa barra não participa.
Cada aplicação registra o valor bruto e se a convenção conservadora foi necessária.

## Margem, liquidação e perda diária

O notional/alavancagem é reservado como margem isolada, sem aporte automático.
Funding altera o colateral isolado. A taxa de manutenção fixa de 0,5% é uma **hipótese**;
não foi obtida das faixas históricas da conta. O gatilho usa preços de marcação, com:

- Long: `(entrada - margem/quantidade) / (1 - taxa_de_manutenção)`.
- Short: `(entrada + margem/quantidade) / (1 + taxa_de_manutenção)`.

Quando o mark OHLC cruza esse nível, o modelo baixa o colateral isolado restante e encerra
a posição. Não reproduz tiers, deduções de manutenção, taxas de liquidação, ADL ou margem
cruzada. O campo de preço na liquidação é o gatilho teórico; a liquidação financeira usa
a baixa do colateral, não uma ordem executada naquele preço.

A perda diária é observada nos fechamentos, pela diferença entre equity e equity na
abertura do dia UTC, com limite de 2 USDT (2% do capital inicial). Ao atingir o limite,
bloqueia novas entradas até o próximo dia UTC; não promete conter gaps nem força fechamento
imediato da posição existente. A rotina de risco também considera o orçamento diário
restante ao dimensionar. Mudança para horário de São Paulo exigirá configuração futura.

## Saídas

- `trades.csv`: operações, custos, funding e PnL líquido.
- `orders.csv`: pendências, preenchimentos, expirações e motivos de rejeição.
- `equity.csv`: carteira e equity marcada a mercado por fechamento.
- `funding.csv`: lançamentos e convenção intrabar.
- `summary.json`: métricas, parâmetros e procedência.

O ledger de trades deve reconciliar com a variação final da carteira. O drawdown informado
usa equity nos fechamentos; não representa o pior drawdown intrabar.

## Limitações para interpretar resultados

Os filtros coletados hoje são reaplicados a todo o passado. Faltam snapshots históricos de
regras, filtros adicionais como MARKET_LOT_SIZE/PERCENT_PRICE aplicáveis a execução real,
fila de ordens, execução parcial, latência e custos calibrados por conta. A simulação de
liquidação é aproximada. Não há validação fora da amostra em períodos reservados ou teste
Demo concluído. O backtest serve para pesquisa, não para habilitar operação real.

Referência de endpoints públicos: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data.
