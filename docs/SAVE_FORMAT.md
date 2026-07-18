# Formato de save observado

Este documento registra apenas estruturas que o normalizador observa. Ele não é
uma especificação oficial do Schedule I e não atribui significado a campos sem
evidência.

## Envelope ZIP

O comando **Export Save** produz um ZIP. A raiz lógica pode ser:

```text
save.zip
├── Money.json
├── Products.json
├── Time.json
└── Rank.json
```

ou estar sob uma ou mais pastas intermediárias:

```text
save.zip
└── export/
    └── nome-arbitrario/
        ├── Money.json
        ├── Products.json
        ├── Time.json
        └── Rank.json
```

O detector procura a pasta que contém os quatro arquivos e não depende de
`SaveGame_1` ou de qualquer outro nome fixo.

## Arquivos essenciais

| Arquivo | Campos inicialmente observados |
|---|---|
| `Money.json` | `GameVersion`, `OnlineBalance`, `Networth`, `LifetimeEarnings`, `WeeklyDepositSum` |
| `Products.json` | `DiscoveredProducts`, `ListedProducts`, `ProductPrices`, `MixRecipes`, `ActiveMixOperation` |
| `Time.json` | `GameVersion`, `ElapsedDays`, `TimeOfDay`, `Playtime` |
| `Rank.json` | `Rank`, `Tier`, `XP`, `TotalXP`, `UnlockedRegions` |

A ausência de qualquer arquivo essencial invalida a importação. Um JSON
essencial malformado ou cuja raiz não seja um objeto também é rejeitado.

## Arquivos opcionais observados

- `Game.json`: `OrganisationName`;
- `Players/*/Inventory.json`: lista `Items`;
- `WorldStorageEntities.json`: `Entities[].Contents.Items`;
- `Properties/*.json` e `Businesses/*.json`: propriedade, posse, funcionários,
  objetos e alguns contêineres de inventário;
- `NPCs.json`: lista de NPCs e estado explicitamente armazenado em uma estrutura
  de relacionamento;
- `Vehicles.json`: lista de registros de veículos.

Esses caminhos descrevem o parser atual, não garantem que todas as versões do
jogo usem o mesmo schema.

## JSON incorporado

Alguns valores podem ser strings cujo conteúdo é outro objeto ou array JSON. O
parser tenta decodificá-los recursivamente apenas quando a string começa com
`{` ou `[`. Se a decodificação falhar, a string original é preservada.

## Origem e campos desconhecidos

Cada modelo contém origens na forma:

```json
{
  "file": "Money.json",
  "field": "OnlineBalance"
}
```

Um campo não compreendido é mantido sem interpretação:

```json
{
  "name": "CampoAindaNaoMapeado",
  "raw": {"valor": "preservado"},
  "origin": {
    "file": "Money.json",
    "field": "CampoAindaNaoMapeado"
  }
}
```

Arquivos JSON inteiros ainda não mapeados aparecem em `snapshot.unknown`, com o
caminho relativo e o conteúdo bruto decodificado.

## Segurança e integridade

- O ZIP é aberto em modo `r`.
- O hash SHA-256 registra os bytes observados na importação.
- O caminho absoluto do ZIP não é incluído no snapshot; apenas seu nome é
  mantido como referência local.
- Extração ocorre apenas em diretório temporário.
- Path traversal, caminhos absolutos, drives e links simbólicos são bloqueados.
- ADS do Windows e destinos resolvidos fora do temporário são bloqueados.
- Limites de entradas, tamanhos e razão de compressão reduzem o risco de Zip
  Bomb e exaustão de recursos.
- A extração temporária é apagada ao final, inclusive em caso de erro.
- Nenhum dado é escrito no save ou no ZIP original.
