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
