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

Strings que contêm objeto/array JSON são decodificadas recursivamente. Falhas
preservam a string original. Campos e arquivos não compreendidos permanecem em
`unknown` ou `raw`, com origem lógica relativa.

## Sinais de campanha

Campos desconhecidos com nomes compatíveis com IDs nativos de campanha são
considerados somente como sinal observável e têm o valor protegido por SHA-256.
Na ausência deles, nome de organização e diretórios de player podem compor um
fingerprint protegido. Valores financeiros, dia e inventário não definem
campanha.

## Privacidade

O snapshot registra nome relativo do arquivo e caminhos internos do ZIP, nunca
o caminho absoluto do computador. Conteúdo bruto preservado pode conter dados
do próprio save; mantenha snapshots e SQLite localmente.
