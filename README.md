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
2. Dados públicos USDⓈ-M: candles fechados, filtros reais, armazenamento e validação temporal.
3. Adaptador Kronos com revisão fixa de código/pesos; comparação com baseline sem IA.
4. Backtest temporal: taxas, funding, slippage, margem e liquidação; prevenção de vazamento.
5. Demo Binance: reconciliação persistente, ordens idempotentes, stops na corretora,
   recuperação após reinício, perda diária persistente e parada de emergência.
6. Operação real limitada após validação e definição final dos parâmetros.

BTCUSDT, candles de 15 minutos e USDⓈ-M são propostas iniciais, não requisitos confirmados.
Não há conector Binance, credenciais, download de modelos, HMM ou estratégia lucrativa validada nesta versão.

## Segurança e limites

Nunca versionar chaves, tokens, `.env`, dados de conta ou modelos baixados.
O simulador não representa funding, liquidação, marcação a mercado, execução parcial ou gaps.
`PaperBroker` recebe planos do motor de risco; não substitui uma fronteira de execução validada.

## Referências

- https://github.com/shiyu-coder/Kronos
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info

Kronos não está copiado nem instalado neste repositório.
