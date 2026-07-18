# O Alquimista — orientação de desenvolvimento

Preserve a regra central: ZIPs, saves e arquivos do jogo são sempre read-only.

## Estado

O Milestone 2 adiciona fingerprint SHA-256, deduplicação idempotente, identidade
de campanha com confiança, evidências explícitas, timeline, comparação segura,
marcos, recomendações e SQLite versionado.

## Próximo objetivo sugerido

Validar os normalizadores opcionais com fixtures sanitizadas de mais versões do
jogo e ampliar métricas comprováveis de capacidade, despesas, fornecedores,
clientes e atividades. Toda nova regra deve ter `rule_id`, evidência,
informação contraditória, limitações e teste.

## Definition of done contínua

- unittest e pytest passam;
- CLIs principal e legada funcionam;
- nenhum caminho absoluto ou dado real entra em fixture/documentação;
- importações iguais permanecem idempotentes;
- comparação entre campanhas exige override;
- ausência nunca é convertida silenciosamente em zero;
- nenhuma operação escreve no ZIP ou no save.
