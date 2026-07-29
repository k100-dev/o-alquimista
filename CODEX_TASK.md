# O Alquimista — orientação de desenvolvimento

Preserve a regra central: ZIPs, saves e arquivos do jogo são sempre read-only.

## Estado

O Milestone 2 adiciona fingerprint SHA-256 para deduplicação, identidade
conservadora com estados explícitos, associações candidatas sem consolidação,
disponibilidade de seções opcionais, evidências explícitas, timeline,
comparação segura, marcos históricos reconstruíveis, recomendações e SQLite
versionado.

## Objetivo atual

Implementar o Milestone 3, **Os Olhos do Alquimista**, documentado em
`docs/MILESTONE_3.md`.

A prioridade é decodificar objetos operacionais presentes nas propriedades,
começando por `BaseData`, `ItemString`, recipientes, cultivo, mistura e
embalagem. Métricas devem permanecer estritamente observáveis ou derivadas.
Throughput, lucro por hora e capacidade não podem ser inventados.

Depois do perfil operacional, validar normalizadores opcionais com fixtures
sanitizadas de mais versões do jogo e ampliar despesas, fornecedores, clientes
e atividades. Toda nova regra deve ter `rule_id`, evidência, informação
contraditória, limitações e teste.

## Definition of done contínua

- unittest e pytest passam;
- CLIs principal e legada funcionam;
- nenhum caminho absoluto ou dado real entra em fixture/documentação;
- importações iguais permanecem idempotentes;
- comparação entre campanhas exige override;
- ausência nunca é convertida silenciosamente em zero;
- nenhuma operação escreve no ZIP ou no save.
