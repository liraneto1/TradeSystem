# Estratégia experimental SMC 0.1 — varredura, estrutura e FVG

Implementação objetiva de uma hipótese inspirada em Smart Money Concepts para pesquisa.
Candles não comprovam a atuação de instituições nem revelam a localização de stops.
Nenhuma vantagem estatística ou rentabilidade foi demonstrada.

## Mercado e risco propostos

BTCUSDT perpétuo USDⓈ-M, candles fechados de 15 minutos, sem restrição por sessão.
Capital de referência: 100 USDT. Teto autorizado: 10x. Para o primeiro backtest propõe-se
alavancagem fixa de 2x, uma posição e uma ordem de entrada pendente por vez.
A política de pesquisa existente limita o risco estimado a 0,5% por operação, perda diária
a 2% do capital inicial e orçamento de margem/custo inicial a 20% do patrimônio.
Esses valores são hipóteses de teste, não uma configuração para operar dinheiro real.

O dimensionamento deve usar `size_order` e os filtros reais. Se os mínimos da corretora
não couberem no orçamento, rejeitar a entrada; nunca ampliar a quantidade para caber no lote.
Os sinais desta versão não são ordens dimensionadas nem garantem viabilidade com 100 USDT.

## Regras causais da compra

1. Identificar o fundo e topo locais mais recentes: extremo estritamente inferior/superior
   aos dois candles à esquerda e dois à direita. Empates não são pivôs. O pivô só se torna
   conhecido no fechamento do segundo candle à direita e utilizável no candle seguinte.
2. O candle de varredura negocia abaixo do fundo confirmado e fecha acima desse fundo,
   permanecendo abaixo do topo de estrutura. Os níveis são congelados nesse momento.
3. Aguardar entre dois e seis candles após a varredura para confirmar o padrão. Se um
   candle voltar à mínima da varredura ou abaixo dela, cancelar a hipótese antes de confirmar.
4. Na confirmação, o fechamento deve superar o topo congelado: nossa definição operacional
   de possível mudança de estrutura (MSS), sem classificação completa de tendência/BOS.
5. Nos três candles A, B e C que terminam na confirmação, exigir `mínima(C) > máxima(A)`.
   Essa é a definição de FVG de alta usada no código. Seu tamanho deve ser pelo menos 0,05 ATR.
6. O candle central B deve ser de alta, com corpo de pelo menos 1 ATR. Para esta medição,
   o ATR é calculado antes de B, excluindo o próprio deslocamento.
7. Propor entrada limite no ponto médio do FVG. Ela só pode ser ativada no candle posterior
   à confirmação e expira ao fechar o quarto candle após a confirmação, caso não executada.
8. Stop proposto abaixo da mínima da varredura, com folga de 0,10 ATR medido antes da varredura.
   Alvo a duas vezes a distância entrada-stop (2R bruto, antes dos custos).

## Venda

Espelhar as condições: varrer topo e fechar abaixo dele, confirmar fechamento abaixo do
fundo de estrutura, deslocamento de baixa em B e `máxima(C) < mínima(A)`. Entrada no meio
do FVG, stop acima da máxima da varredura e alvo de 2R abaixo da entrada.

## Convenções

- ATR: média aritmética dos 14 true ranges anteriores. Não usa a suavização de Wilder.
- Níveis rompidos são consumidos uma vez, mesmo quando não ocorre recuperação suficiente.
- Candle que rompe simultaneamente os dois níveis não inicia setup por ambiguidade.
- Enquanto aguarda confirmação, mantém somente uma hipótese; não a substitui por outra.
- Um sinal pronto não impede novos candidatos futuros; a posição/ordem única será imposta
  pelo executor de backtest, que ainda será implementado.
- Sem filtro Kronos na versão 0.1. Isso permite medir o SMC isoladamente antes de avaliar
  se adicionar o modelo melhora um conjunto de teste reservado.
- Sem order blocks, equal highs/lows, premium/discount, timeframe superior ou otimização
  automática nesta versão. Esses conceitos exigiriam definições adicionais verificáveis.

## Estado da implementação

`tradesystem/smc.py` identifica candidatos, registra níveis, horários, stop, alvo e validade.
O replay de sinais usa somente pivôs e candles disponíveis até cada fechamento. Não calcula
preenchimentos, posições, taxas, funding, liquidação ou PnL. A primeira amostra de 400 candles
do projeto produziu um candidato de venda; isso não significa uma operação executada.
Os parâmetros foram definidos antes dessa execução e não foram ajustados para obter sinais.

Executar:

```powershell
.\.venv\Scripts\python.exe -m tradesystem.smc --dataset data/btc-15m-initial --output reports/smc-initial
```

O diretório de saída deve ser novo. `signals.csv` e `summary.json` guardam candidatos,
configuração e hash do dataset. Os preços são teóricos e ainda precisam de arredondamento
ao tick e validação dos filtros de preço/quantidade antes de qualquer ordem.

## Próximo passo: execução histórica

Implementar a ordem limite ativa apenas após o sinal, cancelamento por expiração/invalidação,
uma posição por vez, regras conservadoras para candle que toca entrada/stop/alvo, gaps,
fees, slippage, funding e margem/liquidação. Calcular curva de patrimônio e drawdown.
Em seguida avaliar períodos separados, reservando o conjunto final, e preparar o painel.

## Referência conceitual

A sequência varredura, confirmação estrutural e FVG é discutida na documentação educacional
da ATAS: https://atas.net/blog/what-is-liquidity-sweep-how-to-trade-it/.
As equações, parâmetros e convenções acima são decisões de implementação do TradeSystem;
não representam reprodução certificada de uma estratégia ICT nem recomendação da fonte.
