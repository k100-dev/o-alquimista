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
`..`, links simbólicos, arquivos especiais, duplicatas ambíguas, profundidade
excessiva e arquivos fora da raiz lógica detectada. Também limita tamanho do
ZIP, diretório central, quantidade de entradas, tamanho individual, total
descompactado e razão de compressão.

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

O arquivo importado recebe um fingerprint SHA-256 integral. A campanha é
resolvida nesta ordem:

1. identificador nativo observado, protegido por hash — confiança alta;
2. combinação protegida de sinais internos estáveis — confiança média;
3. sinal interno parcial — confiança baixa;
4. fallback limitado ao arquivo — confiança baixa e sem promessa de agrupar
   exports futuros.

Dinheiro, dia e inventário nunca são usados isoladamente como identidade.
Consulte [docs/MILESTONE_2.md](docs/MILESTONE_2.md).

Resultados analíticos separam `observed`, `derived`, `inferred` e
`unavailable`. Inferências e recomendações sempre carregam confiança,
justificativa, evidências, limitações e informação ausente. Consulte
[docs/EVIDENCE_MODEL.md](docs/EVIDENCE_MODEL.md).

## Persistência

O SQLite v2 possui campanhas, fingerprints, importações, snapshots, timeline,
evidências, marcos, recomendações e relações entre snapshots. A inicialização é
idempotente e migra o schema do Milestone 1 sem apagar registros. Consulte
[docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md).

## Testes

```powershell
python -m unittest discover -s tests -v
python -m pytest -v
```

As fixtures são sintéticas e não incluem saves reais, IDs pessoais ou caminhos
locais.

## Limitações conhecidas

- A ausência de um ID nativo pode causar falso agrupamento ou separação de
  campanhas; a confiança e a estratégia ficam explícitas.
- Despesas, fornecedores, clientes, atividades e capacidade ainda podem ficar
  indisponíveis.
- Regras de liquidez e dependência operacional são heurísticas locais,
  identificadas e testáveis; não são fatos do jogo.
- JSONs são carregados em memória depois que o ZIP passa pelos limites de
  segurança; o parser ainda não é streaming.
- Dados `raw/unknown` podem conter identificadores presentes no save. Nada é
  enviado externamente, mas snapshots e bancos devem ser tratados como dados
  locais potencialmente sensíveis.
