# Formato de save observado

Este documento descreve somente estruturas observadas pelo normalizador; não é
uma especificação oficial do jogo.

## Envelope e raiz

O ZIP pode conter os JSONs na raiz ou sob pastas intermediárias. A raiz lógica
é a pasta mais rasa que contém simultaneamente:

- `Money.json`;
- `Products.json`;
- `Time.json`;
- `Rank.json`.

O nome da pasta não participa da detecção ou da identidade. Arquivos fora da
raiz lógica detectada são rejeitados.

## Campos essenciais normalizados

| Arquivo | Campos |
|---|---|
| `Money.json` | `GameVersion`, `OnlineBalance`, `Networth`, `LifetimeEarnings`, `WeeklyDepositSum` |
| `Products.json` | `DiscoveredProducts`, `ListedProducts`, `ProductPrices`, `MixRecipes`, `ActiveMixOperation` |
| `Time.json` | `GameVersion`, `ElapsedDays`, `TimeOfDay`, `Playtime` |
| `Rank.json` | `Rank`, `Tier`, `XP`, `TotalXP`, `UnlockedRegions` |

Arquivos opcionais observados incluem `Game.json`,
`Players/*/Inventory.json`, `WorldStorageEntities.json`,
`Properties/*.json`, `Businesses/*.json`, `NPCs.json` e `Vehicles.json`.

Para players, inventário, armazenamento mundial, propriedades, negócios, NPCs,
funcionários e veículos, o snapshot registra `availability`: `observed`,
`missing`, `invalid` ou `unsupported`. Um diretório/arquivo presente e válido
com lista vazia é `observed`; ausência e conteúdo inválido não são convertidos
em zero.

Strings que contêm objeto/array JSON são decodificadas recursivamente. Falhas
preservam a string original. Campos e arquivos não compreendidos permanecem em
`unknown` ou `raw`, com origem lógica relativa.

## Números

- inteiros JSON são lidos como `int`, preservando contagens, índices e
  identificadores numéricos;
- frações JSON são lidas como `Decimal`;
- dinheiro, preços e saldos permanecem `Decimal` durante normalização e
  cálculos;
- quantidades são `Decimal` por poderem ser fracionárias, mas não são tratadas
  semanticamente como dinheiro;
- métricas não monetárias podem ser convertidas para `float` quando
  fracionárias;
- `NaN`, `Infinity` e `-Infinity` são rejeitados como JSON inválido.

Essa estratégia preserva exatamente valores como `9007199254740993`, `0.10` e
`12345678901234567890.99`.

## Sinais de campanha

`CampaignId` observado em `Game.json` é a única identidade forte atualmente.
`GameId`, `SaveId`, nome de organização e diretórios de player são sinais
protegidos por SHA-256 para associações candidatas; não consolidam campanhas.
Na ausência de identidade forte, cada export recebe uma campanha provisória
independente. O fingerprint do ZIP, valores financeiros, dia, inventário, nome,
caminho e horário do arquivo não definem campanha.

## Privacidade

O snapshot registra nome relativo do arquivo e caminhos internos do ZIP, nunca
o caminho absoluto do computador. Conteúdo bruto preservado pode conter dados
do próprio save; mantenha snapshots e SQLite localmente.
