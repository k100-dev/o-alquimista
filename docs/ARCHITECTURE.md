# Arquitetura do O Alquimista

## Princípios

1. origem read-only e extração efêmera;
2. identidade por conteúdo, nunca por caminho;
3. observação separada de cálculo e inferência;
4. resultados determinísticos;
5. confiança e limitações explícitas;
6. transações atômicas e schema migrável;
7. biblioteca padrão primeiro.

## Fluxo de importação

```text
ZIP read-only
  -> preflight e limites
  -> SHA-256 em blocos
  -> extração temporária segura
  -> detecção/validação da raiz
  -> snapshot normalizado
  -> identidade de campanha + evidências
  -> transação SQLite
       -> deduplicação
       -> campanha/import/snapshot
       -> timeline/evidências/relações
```

## Módulos

- `archive.py`: limites, validação de entradas, extração e escopo lógico;
- `identity.py`: `ArchiveFingerprint` e `CampaignIdentity`;
- `parser.py`: normalização read-only e preservação `raw/unknown`;
- `memory_models.py`: evidência, timeline, comparação, marco e recomendação;
- `evidence.py`: fábricas determinísticas das quatro categorias;
- `analysis.py`: comparação, ordenação, marcos e regras de recomendação;
- `database.py`: schema v2, migração, deduplicação e consultas;
- `memory_reports.py`: Markdown com seções epistemológicas separadas;
- `cli.py`: adaptação de argumentos e apresentação;
- `schedule_intelligence`: delegação de compatibilidade, sem lógica duplicada.

## Identidade e determinismo

O fingerprint é SHA-256 dos bytes integrais do ZIP. O snapshot não contém
timestamp da operação nem caminho absoluto. IDs de import/snapshot são
derivados do digest; IDs de campanha, evidência, marco, comparação e
recomendação são hashes de entradas canônicas.

Listas oriundas do filesystem e artefatos analíticos possuem ordenação
explícita. JSON usa chaves ordenadas. A data de importação fica no banco e só é
fallback da timeline quando tempo interno e progressão não resolvem a ordem.

## Comparação

O comparador recebe dois snapshots e suas campanhas. Campanhas diferentes
geram erro, salvo override explícito. Dinheiro usa `Decimal` e é serializado
como texto decimal. Campo ausente vira `unknown` ou `not_comparable`, nunca
zero. Coleções distinguem adição, remoção, alteração e invariância.

## Recomendações

`RECOMMENDATION_RULES` centraliza regras identificadas:

- `liquidity.minimum-buffer.v1`;
- `operations.owner-dependency.v1`;
- `memory.collect-baseline.v1`.

As regras produzem recomendação, não fato, e incluem evidências, confiança,
informações ausentes e limitações.
