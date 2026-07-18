# O Alquimista

O Alquimista é um companion estratégico local e read-only para exports de save
do **Schedule I**. O Milestone 2, **A Memória do Alquimista**, transforma
importações isoladas em campanhas com identidade explicável, deduplicação por
conteúdo, linha do tempo, comparação, evidências, marcos e recomendações
determinísticas.

Não há interface gráfica nem chamadas de rede neste milestone.

## Segurança read-only

O ZIP original é aberto somente para leitura. Sua identidade SHA-256 é
calculada em blocos, sem extração. A leitura do save ocorre em diretório
temporário removido ao final, inclusive em falhas.

O extrator rejeita caminhos absolutos, drives e ADS do Windows, UNC, segmentos
`..`, dispositivos reservados do Windows (`CON`, `NUL`, `COM1`, `LPT1` e
equivalentes), links simbólicos, arquivos especiais, duplicatas ambíguas,
profundidade excessiva e arquivos fora da raiz lógica detectada. Também limita
tamanho do ZIP, diretório central, quantidade de entradas, tamanho individual,
total descompactado e razão de compressão.

A CLI impede que uma saída seja gravada dentro de uma pasta de save usada como
fonte, impede que o SQLite substitua o ZIP e bloqueia relatórios que tentem
sobrescrever o banco ou qualquer arquivo `.zip`. Nunca escolha uma pasta do
jogo como destino de `--database` ou `--out`.

Detalhes: [docs/SECURITY.md](docs/SECURITY.md).

## Instalação

Requer Python 3.11 ou superior e usa somente a biblioteca padrão em runtime.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Comandos

Importar de forma idempotente:

```powershell
alquimista import "export.zip" --database ".\data\alquimista.sqlite3"
```

Reimportar os mesmos bytes devolve os IDs originais e não cria novas linhas.
Nome, caminho, timestamp ou pasta interna do ZIP não participam da
deduplicação.

Gerar snapshot e relatório sem persistir:

```powershell
alquimista snapshot "export.zip" --out ".\output\current"
```

Consultar importações e campanhas:

```powershell
alquimista history --database ".\data\alquimista.sqlite3"
alquimista campaign list --database ".\data\alquimista.sqlite3"
alquimista campaign history <campaign_id> --database ".\data\alquimista.sqlite3"
alquimista campaign associations <campaign_id> --database ".\data\alquimista.sqlite3"
```

Linha do tempo, comparação e análise:

```powershell
alquimista timeline <campaign_id> --database ".\data\alquimista.sqlite3"
alquimista compare <snapshot_a> <snapshot_b> --database ".\data\alquimista.sqlite3"
alquimista analyze <campaign_id> --database ".\data\alquimista.sqlite3"
```

`campaign history`, `timeline`, `compare` e `analyze` aceitam
`--format json|markdown` e `--out <arquivo>`. Comparações entre campanhas são
bloqueadas por padrão; o override explícito é `--allow-cross-campaign`.

O comando legado continua disponível:

```powershell
schedule-intel --help
```

O diff de arquivos JSON do protótipo também permanece:

```powershell
alquimista diff before.json after.json --out diff.json
```

## Memória e confiança

O arquivo importado recebe um fingerprint SHA-256 integral, usado somente para
deduplicar a importação. A identidade da campanha possui estado explícito:

- `resolved`: `CampaignId` nativo observado e protegido por hash;
- `candidate`: `GameId`, `SaveId`, organização ou players são apenas sinais
  ambíguos; cada export permanece em uma campanha provisória independente;
- `unresolved`: não há evidência suficiente e nenhuma confiança de identidade é
  afirmada;
- `explicitly_linked`: reservado para uma vinculação explícita futura.

Associações candidatas registram sinais protegidos compartilhados, mas nunca
unem campanhas automaticamente. Nome, caminho, horário, dinheiro, dia,
inventário e o hash do ZIP não definem `campaign_id`.
Consulte [docs/MILESTONE_2.md](docs/MILESTONE_2.md).

Resultados analíticos separam `observed`, `derived`, `inferred` e
`unavailable`. Coleções opcionais também registram disponibilidade
`observed`, `missing`, `invalid` ou `unsupported`; ausência e erro nunca
equivalem a coleção vazia. Inferências e recomendações sempre carregam
confiança, justificativa, evidências, limitações e informação ausente. Consulte
[docs/EVIDENCE_MODEL.md](docs/EVIDENCE_MODEL.md).

Valores monetários são lidos e calculados com `Decimal`, sem passagem por
`float`. Inteiros do JSON permanecem `int`, inclusive contagens; quantidades
fracionárias e preços usam `Decimal` conforme sua semântica. Na persistência,
decimais são strings exatas, determinísticas e independentes de locale. Bancos
v1, v2 e v3 com números JSON antigos continuam legíveis sem migração de schema.
`NaN` e infinitos não são aceitos.

## Persistência

O SQLite v3 possui campanhas, sinais e associações candidatas, fingerprints,
importações, snapshots, timeline, evidências, marcos reconstruíveis,
recomendações e relações entre snapshots. A inicialização é transacional e
idempotente, migra schemas v1 e v2 e preserva snapshots anteriores. Consulte
[docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md).

## Testes

```powershell
python -m unittest discover -s tests -v
python -m pytest -v
```

As fixtures são sintéticas e não incluem saves reais, IDs pessoais ou caminhos
locais.

## Limitações conhecidas

- Sem `CampaignId` comprovado, exports permanecem separados. Associações
  candidatas precisam de revisão e ainda não há comando de consolidação
  explícita.
- Bancos v2 podem conter agrupamentos históricos feitos por sinais fracos; a
  migração os marca como candidatos, mas não tenta separar dados anteriores sem
  evidência suficiente.
- Despesas, fornecedores, clientes, atividades e capacidade ainda podem ficar
  indisponíveis.
- Regras de liquidez e dependência operacional são heurísticas locais,
  identificadas e testáveis; não são fatos do jogo.
- JSONs são carregados em memória depois que o ZIP passa pelos limites de
  segurança; o parser ainda não é streaming.
- Métricas não monetárias fracionárias, como tempo de jogo, continuam podendo
  usar `float`; elas não participam dos cálculos financeiros.
- Dados `raw/unknown` podem conter identificadores presentes no save. Nada é
  enviado externamente, mas snapshots e bancos devem ser tratados como dados
  locais potencialmente sensíveis.
