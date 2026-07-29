# Milestone 2 — A Memória do Alquimista

## Status

Concluído na versão 0.4.0 e aprovado tecnicamente, com validações reais
complementares documentadas no
[Termo de Aceite Técnico](MILESTONE_2_ACCEPTANCE.md).

## Entregas

- fingerprint SHA-256 integral e determinístico;
- deduplicação idempotente garantida pelo banco;
- identidade de campanha com estratégia, confiança e evidência;
- timeline ordenada por sinais internos e desempate por ID estável;
- comparação financeira e operacional;
- marcos determinísticos;
- recomendações locais baseadas em regras identificadas;
- CLI e relatórios JSON/Markdown;
- migração SQLite v1/v2 para v3.

## Marcos implementados

- primeira propriedade possuída;
- primeiro veículo;
- primeiro funcionário;
- primeiro produto descoberto;
- aumento de patrimônio de pelo menos 1.000 e 25% entre snapshots.

IDs de marcos “primeiro” dependem de campanha e tipo. A detecção consulta todo
o histórico anterior, não apenas o snapshot imediatamente anterior. Após uma
importação retroativa, a timeline e todos os marcos derivados da campanha são
recalculados atomicamente, reposicionando `first_seen_snapshot_id`.

## Identidade de campanha

| Estado | Evidência | Comportamento |
|---|---|---|
| `resolved` | `CampaignId` nativo em `Game.json` | exports com o mesmo ID protegido compartilham campanha |
| `candidate` | `GameId`, `SaveId`, organização ou player | campanha provisória própria; coincidências geram associação candidata |
| `unresolved` | nenhuma evidência de identidade | campanha provisória própria e confiança indisponível |
| `explicitly_linked` | vinculação explícita | reservado; não há consolidação automática |

O valor bruto de um ID usado na resolução não é incluído na evidência de
identidade. O SHA-256 integral do ZIP identifica somente a importação e nunca
participa do `campaign_id`. Nome, caminho e horário do arquivo também não
participam.

`alquimista campaign associations` expõe relações candidatas e seus sinais
protegidos. Essas relações são informativas: não compartilham timeline,
snapshots ou marcos entre as campanhas envolvidas.

## Linha do tempo

A ordenação usa, nesta ordem: dia interno, horário interno, playtime,
progressão total, rank, tier, XP e `snapshot_id`. Os sinais internos disponíveis
prevalecem; o ID resolve empates totais deterministicamente. `imported_at`
permanece metadado operacional e nunca participa da ordem analítica.

Assim, dois bancos que recebem os mesmos snapshots em ordens ou horários
diferentes produzem a mesma timeline, relações predecessor/sucessor, marcos,
comparações e análise. Importações retroativas continuam reconstruindo a ordem
e os marcos dentro da mesma transação.

## Comparação

Campos monetários usam decimal exato. Percentual só existe quando a base
anterior é numérica e diferente de zero. Seções ausentes permanecem
`unknown`; valores não numéricos são `not_comparable`. Seções opcionais
distinguem fonte observada vazia de `missing`, `invalid` e `unsupported`.
