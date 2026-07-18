# Modelo de evidências

## Categorias

- `observed`: valor lido diretamente de campo conhecido;
- `derived`: cálculo reproduzível sobre observações;
- `inferred`: conclusão limitada apoiada por evidências;
- `unavailable`: dado necessário ausente ou ainda não normalizado.

## Campos

Uma evidência possui ID determinístico, categoria, arquivo/caminho lógico,
campo, valor bruto quando apropriado, valor normalizado, cálculo, explicação,
confiança, entidade relacionada e campos desconhecidos relacionados.

Nenhum caminho absoluto é permitido. Identificadores usados para resolver
campanha são protegidos por hash e não aparecem como valor bruto.

## Confiança

- `high`: campo direto ou cálculo sem ambiguidade relevante;
- `medium`: combinação observável com limitação conhecida;
- `low`: sinal parcial ou heurística;
- `unavailable`: não há base suficiente.

Inferências e recomendações nunca são apresentadas como fatos. Recomendações
também carregam evidência contraditória, informação ausente, regra,
justificativa e limitações.

## Linhagem semântica

- conclusões sobre histórico apontam para uma evidência derivada de
  `snapshot_count`, nunca para saldo ou patrimônio;
- liquidez aponta para saldo online e para as origens reais dos itens agregados,
  incluindo `WorldStorageEntities.json` quando essa foi a fonte;
- patrimônio aponta para `Money.json:Networth`;
- disponibilidade observada possui evidência derivada da validação de presença
  e estrutura; estados `missing`, `invalid` e `unsupported` produzem
  `unavailable`;
- evidências derivadas enumeram seus `supporting_evidence_ids` quando dependem
  de outras evidências;
- toda evidência derivada registra o cálculo e ao menos uma limitação explícita;
- justificativas de confiança são específicas para cada regra.

IDs referenciados são determinísticos e persistidos no escopo do snapshot mais
recente da campanha analisada. Relatórios públicos usam apenas os campos
normalizados da evidência: `raw`, `unknown_fields`, identificadores pessoais e
caminhos locais não são expostos.

## Disponibilidade de seções

Cada coleção opcional normalizada informa um estado independente:

- `observed`: a fonte existe, é válida e pode conter zero elementos;
- `missing`: a fonte esperada não foi encontrada;
- `invalid`: a fonte existe, mas não pôde ser validada;
- `unsupported`: o formato foi reconhecido como não suportado, quando
  aplicável.

O estado fica no campo `availability` do snapshot. Comparações, marcos e
recomendações só usam contagens quando a seção está `observed`. `missing`,
`invalid` e `unsupported` geram resultado desconhecido ou evidência
`unavailable`, nunca zero, remoção ou coleção observada vazia.

Snapshots legados com números JSON e snapshots atuais com decimais em strings
passam pela mesma restauração tipada de campos conhecidos. Strings comuns não
são convertidas por inferência; a evidência depende do valor normalizado, não
do formato físico usado no SQLite.
