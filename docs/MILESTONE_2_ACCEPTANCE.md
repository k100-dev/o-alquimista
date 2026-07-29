# Milestone 2 — Termo de Aceite Técnico

## Status

Aprovado com validações reais complementares pendentes.

## Escopo entregue

- identidade conservadora de campanhas;
- deduplicação SHA-256;
- snapshots;
- timeline determinística;
- comparações;
- evidências rastreáveis;
- marcos históricos;
- recomendações;
- disponibilidade explícita;
- precisão monetária com `Decimal`;
- SQLite v3;
- migrações v1/v2/v3;
- tratamento seguro de ZIP;
- CLI expandida;
- compatibilidade com `schedule-intel`.

## Validação automatizada

- unittest: 109/109;
- pytest: 109/109;
- subtests: 106/106;
- Milestone 1 isolado: 20/20;
- `compileall` aprovado;
- `git diff --check` aprovado.

## Validação com exports reais

A validação local utilizou dois ZIPs reais sem registrar nomes, hashes
completos, valores monetários, identificadores internos, caminhos absolutos,
dados `raw` ou `unknown_fields`.

- deduplicação aprovada;
- identidade `candidate` aprovada;
- nenhuma consolidação automática;
- campanhas provisórias isoladas;
- precisão `Decimal` aprovada;
- evidências aprovadas;
- migrações aprovadas;
- CLI aprovada;
- ZIPs preservados byte a byte.

## Validações complementares pendentes

- mesma campanha com identidade forte;
- importação real em ordem inversa;
- seção real ausente versus presente-vazia.

Essas validações possuem cobertura automatizada e permanecem como dívida de
validação com exports reais.

## Riscos conhecidos

- campanhas `candidate` ainda não possuem consolidação explícita;
- `raw` e `unknown_fields` devem permanecer locais;
- o parser JSON ainda não é streaming;
- ZIP criptografado é rejeitado;
- GUI não faz parte do Milestone 2.

## Decisão

O Milestone 2 está apto para integração após revisão do Pull Request.
