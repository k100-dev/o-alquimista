# Schema SQLite v3

## Tabelas

- `campaigns`: ID lógico, estado de resolução, estratégia, confiança, evidência
  e explicação;
- `campaign_identity_signals`: sinais protegidos por campanha, sem poder de
  consolidação;
- `campaign_associations`: pares candidatos e a evidência compartilhada;
- `archive_fingerprints`: SHA-256 único, tamanho e quantidade de membros;
- `imports`: vínculo campanha/fingerprint e instante local;
- `snapshots`: JSON normalizado determinístico;
- `timeline_entries`: momento interno, ordem e resumos;
- `evidence`: payloads categorizados, com chave composta `(id, snapshot_id)`;
- `milestones`: marcos manuais do Milestone 1;
- `campaign_milestones`: marcos derivados reconstruídos por campanha e
  vinculados ao primeiro snapshot correto;
- `recommendations`: recomendações por snapshot;
- `snapshot_relationships`: sucessão cronológica.

## Integridade

- foreign keys são ativadas em toda conexão;
- `archive_fingerprints.digest` é `UNIQUE`;
- uma importação/snapshot é derivada de um digest;
- timeline tem um registro por snapshot e ordem indexada por campanha;
- relações cronológicas são reconstruídas quando um snapshot antigo é
  importado depois;
- associações candidatas relacionam campanhas distintas e nunca alteram suas
  chaves;
- marcos derivados são apagados e reinseridos para a campanha dentro da mesma
  transação que reordena a timeline;
- persistência de importação usa `BEGIN IMMEDIATE`, commit atômico e rollback
  em qualquer falha;
- conexões fecham em `finally`, inclusive em erro de configuração.

## Migração

`initialize()` é transacional e idempotente. Bancos v1 recebem fingerprints e
estruturas de memória. Bancos v2 recebem `resolution_state`, sinais,
associações e marcos reconstruíveis. Snapshots, imports e campanhas existentes
são preservados; `PRAGMA user_version` passa a `3`.

Identidades v2 antes derivadas de organização/players são marcadas como
`candidate`. Seus sinais protegidos são migrados quando a evidência legada
permite, mas agrupamentos históricos não são desfeitos automaticamente, pois
não há evidência segura para repartir seus snapshots.

Registros legados podem conservar texto histórico criado por versões
anteriores; novas importações nunca persistem caminho absoluto.
