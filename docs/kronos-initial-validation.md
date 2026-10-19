# Validação inicial do adaptador Kronos

Executada localmente em CPU em 19/10/2026. O objetivo foi verificar integração e avaliação
cronológica, sem negociação ou ajuste fino.

## Experimento

- Dataset: 400 candles fechados BTCUSDT USDⓈ-M de 15 minutos, coletados da API pública Binance.
- SHA-256 do CSV: `572c8f1deb5c969dbc6647ddda9fe1e49590023009730ff63423b49b5c6a31fd`.
- Modelo: Kronos-small; revisões de código, pesos e tokenizer em `config/kronos.lock.json`.
- Contexto: 128 candles; horizonte: 4 candles; 5 janelas com alvos sem sobreposição.
- Total: 20 preços-alvo. Seed 42, temperatura 1, top-p 0,9, uma trajetória, CPU.
- Referência: último fechamento observado repetido para os quatro passos futuros.
- Apenas o histórico anterior e timestamps futuros são fornecidos ao modelo em cada janela.

| Métrica de erro de preço | Kronos-small | Persistência |
|---|---:|---:|
| MAE em USDT | 150,61 | 84,30 |

Nesta amostra o modelo não superou a referência. Não há base para ativar uma estratégia
real a partir desse resultado. MAE de preço não é lucro ou perda financeira da estratégia.
Uma amostra tão pequena serve apenas como verificação inicial da integração.

## Limitações e continuidade

A avaliação não inclui custos de negociação, funding, margem, liquidação ou ordens.
Possível sobreposição com o pré-treino não foi auditada; não se afirma que os alvos sejam
inteiramente posteriores ao treinamento do modelo. O próximo experimento deve usar
mais períodos e regimes, configurações predefinidas e um conjunto final reservado.
Repetir configurações até melhorar essa mesma amostra introduziria viés de seleção.

Previsões completas e metadados do ambiente são gerados localmente em `reports/`.
Código original e pesos continuam fora do versionamento. Nenhuma alteração foi enviada
aos repositórios de referência.
