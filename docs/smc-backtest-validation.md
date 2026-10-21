# Validação inicial do motor de backtest SMC

Execução de pesquisa em 21/10/2026. Parâmetros SMC 0.1 mantidos sem otimização, sem Kronos.
Os cenários 2x e 5x foram definidos antes da avaliação ampliada para verificar viabilidade
de lotes mínimos mantendo capital e orçamento de risco iguais.

## Dados e parâmetros

- Binance BTCUSDT USDⓈ-M, 10.000 candles de 15 minutos e 10.000 mark-price candles.
- Intervalo UTC: 09/07/2026 14:45 até 21/10/2026 18:45, fim exclusivo.
- Histórico consultado: 313 eventos de funding; a posição só participa quando aplicável.
- CSV de candles SHA-256: `4134918678d723765afc9d5ece225d583bad7333376f3cb5078f254f772915bc`.
- Suplemento SHA-256: `4eea37461d6ec6a3c875c79e470c6d7dbe5f796b59f70dc9e6d666e761893cf8`.
- Capital: 100 USDT; risco estimado de 0,5% por entrada; margem inicial/custo até 20%.
- Snapshot de filtros: lote mínimo 0,001 BTC, valor mínimo 50 USDT; aplicado ao passado.
- Custo por lado: taxa 0,05% + slippage 0,02% (hipóteses).
- Manutenção isolada: taxa assumida fixa de 0,5%, não uma tabela histórica da corretora.

## Resultado de verificação

| Medida | 2x | 5x |
|---|---:|---:|
| Sinais candidatos | 37 | 37 |
| Rejeitados por dimensionamento/mínimos | 37 | 16 |
| Ordens expiradas | 0 | 11 |
| Operações fechadas | 0 | 10 |
| Alvos / stops | 0 / 0 | 3 / 7 |
| PnL líquido simulado (USDT) | 0,00 | -0,91358 |
| Saldo final simulado (USDT) | 100,00 | 99,08642 |
| Drawdown de equity nos fechamentos | 0,00% | 1,6495% |

O cenário 2x não chegou a negociar: o orçamento de margem permite menos de 40 USDT de
notional antes dos custos, inferior ao mínimo da ordem, além da restrição de lote.
Seu resultado zero representa inatividade, não uma estratégia validada sem perdas.
No cenário 5x, os lançamentos de funding somaram crédito líquido de aproximadamente
0,02290 USDT; o resultado final já inclui esse crédito e os custos de negociação.
Não ocorreram liquidações modeladas nessa amostra.

O ledger reconciliou exatamente, dentro da tolerância Decimal, com a variação da carteira.
Testes sintéticos verificam cenários de compra/venda, gaps, ordem temporal, expiração,
stop/alvo no mesmo candle, funding, liquidação por mark price e limite diário.

## Interpretação

Os dez trades são insuficientes para inferir vantagem estatística. O resultado do cenário
que negociou foi negativo sob estas premissas. Não se recomenda selecionar ou otimizar
parâmetros a partir dessa mesma amostra e apresentar isso como teste independente.
Este intervalo é de desenvolvimento, não um conjunto final reservado.

Aplicam-se as limitações de `docs/backtest.md`: filtros atuais sobre histórico, custos
hipotéticos, sequência OHLC conservadora, funding intrabar aproximado e liquidação
simplificada sem tiers históricos. O painel TradingView e a validação Demo permanecem pendentes.
