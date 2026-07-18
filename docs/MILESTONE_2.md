# Milestone 2 — A Memória do Alquimista

## Entregas

- fingerprint SHA-256 integral e determinístico;
- deduplicação idempotente garantida pelo banco;
- identidade de campanha com estratégia, confiança e evidência;
- timeline ordenada por tempo interno, progressão e fallback de importação;
- comparação financeira e operacional;
- marcos determinísticos;
- recomendações locais baseadas em regras identificadas;
- CLI e relatórios JSON/Markdown;
- migração SQLite v1 para v2.

## Marcos implementados

- primeira propriedade possuída;
- primeiro veículo;
- primeiro funcionário;
- primeiro produto descoberto;
- aumento de patrimônio de pelo menos 1.000 e 25% entre snapshots.

IDs de marcos “primeiro” dependem de campanha e tipo, evitando duplicação.

## Identidade de campanha

| Estratégia | Confiança | Limitação |
|---|---|---|
| `CampaignId` nativo em `Game.json` | alta | depende de campo realmente presente |
| `GameId`/`SaveId` em `Game.json` | média | nome do campo ainda pode ser ambíguo |
| organização + player protegidos | média | campanhas distintas podem compartilhar sinais |
| sinal interno parcial | baixa | maior risco de falso positivo |
| fallback pelo arquivo | baixa | não agrupa exports diferentes |

O valor bruto de um ID usado na resolução não é incluído na evidência de
identidade.

## Linha do tempo

A ordenação usa, nesta ordem: dia interno, horário interno, playtime,
progressão total, data de importação e `snapshot_id`. Os primeiros campos
disponíveis prevalecem; o ID resolve empates deterministicamente.

## Comparação

Campos monetários usam decimal exato. Percentual só existe quando a base
anterior é numérica e diferente de zero. Seções ausentes permanecem
`unknown`; valores não numéricos são `not_comparable`.
