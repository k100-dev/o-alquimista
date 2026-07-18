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
- a fronteira `persist_import` valida caminhos de proveniência antes de
  inicializar ou inserir registros; caminhos absolutos, drive Windows, UNC,
  `..`, ADS, `file://` e atalhos de home são rejeitados mesmo em chamadas
  diretas;
- a mesma validação cobre `source_path`, `logical_path`, sinais de identidade e
  todas as evidências antes de sua persistência;
- `imported_at` é somente metadado operacional e não participa da ordenação da
  timeline.

## Migração

`initialize()` lê `PRAGMA user_version` antes de qualquer migração. Bancos com
versão superior a `3` são rejeitados sem alteração de schema, versão ou dados;
não existe downgrade automático.

Para versões suportadas, `initialize()` é transacional e idempotente. Bancos v1 recebem fingerprints e
estruturas de memória. Bancos v2 recebem `resolution_state`, sinais,
associações e marcos reconstruíveis. Snapshots, imports e campanhas existentes
são preservados; `PRAGMA user_version` passa a `3`.

Identidades v2 antes derivadas de organização/players são marcadas como
`candidate`. Seus sinais protegidos são migrados quando a evidência legada
permite, mas agrupamentos históricos não são desfeitos automaticamente, pois
não há evidência segura para repartir seus snapshots.

Registros legados podem conservar texto histórico criado por versões
anteriores; novas importações nunca persistem caminho absoluto.

## Representação monetária

O schema permanece na versão 3. Não foi necessária migração estrutural para a
correção de precisão. Novos snapshots serializam dinheiro, preços e quantidades
decimais como strings exatas, por exemplo `"0.10"` e
`"12345678901234567890.99"`.

Na recuperação, o codec restaura os campos conhecidos para `Decimal`. Bancos
v1, v2 e v3 que armazenaram esses valores como números JSON continuam
compatíveis: o texto numérico legado é interpretado diretamente como
`Decimal`, sem passagem por `float`.
