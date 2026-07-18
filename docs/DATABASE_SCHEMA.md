# Schema SQLite v2

## Tabelas

- `campaigns`: ID lógico, estratégia, confiança, evidência e explicação;
- `archive_fingerprints`: SHA-256 único, tamanho e quantidade de membros;
- `imports`: vínculo campanha/fingerprint e instante local;
- `snapshots`: JSON normalizado determinístico;
- `timeline_entries`: momento interno, ordem e resumos;
- `evidence`: payloads categorizados, com chave composta `(id, snapshot_id)`;
- `milestones`: marcos por snapshot;
- `recommendations`: recomendações por snapshot;
- `snapshot_relationships`: sucessão cronológica.

## Integridade

- foreign keys são ativadas em toda conexão;
- `archive_fingerprints.digest` é `UNIQUE`;
- uma importação/snapshot é derivada de um digest;
- timeline tem um registro por snapshot e ordem indexada por campanha;
- relações cronológicas são reconstruídas quando um snapshot antigo é
  importado depois;
- persistência de importação usa `BEGIN IMMEDIATE`, commit atômico e rollback
  em qualquer falha;
- conexões fecham em `finally`, inclusive em erro de configuração.

## Migração

`initialize()` é idempotente. Bancos do Milestone 1 recebem colunas novas,
tabelas v2 e fingerprints retroativos para hashes já existentes, sem remoção
de campanhas, imports ou snapshots. `PRAGMA user_version` passa a `2`.

Registros legados podem conservar texto histórico criado por versões
anteriores; novas importações nunca persistem caminho absoluto.
