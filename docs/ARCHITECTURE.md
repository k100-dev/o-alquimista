# Arquitetura do O Alquimista

## Princípios

1. **Read-only na origem:** ZIPs e diretórios de save são apenas lidos.
2. **Extração efêmera:** conteúdo de ZIP existe somente dentro de
   `TemporaryDirectory`.
3. **Observação antes de interpretação:** campos conhecidos são normalizados;
   os demais são preservados como `unknown` ou `raw`.
4. **Rastreabilidade:** valores normalizados registram arquivo e campo de origem.
5. **Biblioteca padrão primeiro:** ZIP, JSON, SQLite, CLI e modelos usam apenas
   módulos da biblioteca padrão do Python 3.11+.

## Fluxo

```text
Export Save ZIP (somente leitura)
        |
        v
validação do arquivo e das entradas
        |
        v
extração em diretório temporário
        |
        v
detecção da raiz pelos JSONs essenciais
        |
        v
modelos de domínio tipados
        |
        +----> snapshot.json + report.md
        |
        +----> campanhas/importações/snapshots no SQLite
                     |
                     +----> milestones/recomendações
```

## Módulos

### `o_alquimista.archive`

Valida existência e assinatura ZIP. Antes de escrever qualquer membro no
diretório temporário, normaliza separadores e rejeita caminhos absolutos,
componentes `..`, drives, links simbólicos e destinos fora da raiz temporária.
Não usa `extractall`.

Antes da extração, também limita quantidade de entradas, tamanho individual,
tamanho total descompactado, comprimento de nomes e razão de compressão. A
cópia é feita em blocos e revalida os limites durante a descompressão.

A raiz do save é a pasta mais rasa que contém simultaneamente:
`Money.json`, `Products.json`, `Time.json` e `Rank.json`. Seu nome não participa
da decisão. Empates na mesma profundidade são rejeitados como ambíguos.

### `o_alquimista.parser`

Decodifica JSON e strings que contêm JSON, reproduz o escopo analítico do
protótipo e agrega inventários de players, armazenamento mundial e
propriedades. `read_save_model` mantém suporte read-only a diretórios para
compatibilidade; `snapshot_from_zip` é a API principal.

Arquivos JSON não consumidos pelo normalizador são preservados integralmente no
campo `unknown` do snapshot. Campos não mapeados de arquivos consumidos são
preservados no modelo correspondente.

### `o_alquimista.models`

Dataclasses imutáveis e com `slots` representam metadata, financeiro, tempo,
progressão, produtos, inventários, propriedades, NPCs, funcionários, veículos,
campos desconhecidos, milestones e recomendações.

`DataOrigin` aponta para o caminho relativo do arquivo e para o campo observado.
`NormalizedSnapshot.to_dict()` gera uma estrutura JSON e mantém a chave `game`
necessária ao diff e ao relatório legados.

### `o_alquimista.database`

O schema SQLite possui chaves estrangeiras e transações curtas:

- `campaigns`: agrupamento local pela origem do ZIP;
- `imports`: hash SHA-256, raiz detectada e instante da importação;
- `snapshots`: JSON normalizado versionado;
- `milestones`: payload do modelo associado ao snapshot;
- `recommendations`: payload do modelo associado ao snapshot.

Conexões são fechadas explicitamente, inclusive no Windows.

O instante real da operação pertence às tabelas de importação. Ele não integra
o snapshot normalizado, para que o mesmo ZIP produza JSON idêntico. O snapshot
registra somente o nome do ZIP, nunca seu caminho absoluto local.

### `o_alquimista.cli`

Expõe `import`, `snapshot`, `history` e o `diff` preservado. Erros esperados
retornam status 2 sem traceback. O alias `schedule-intel` e os módulos
`schedule_intelligence` existem somente como ponte de migração.

No modo legado de leitura de diretório, a CLI bloqueia qualquer saída igual ou
interna à raiz do save. O banco também não pode compartilhar o caminho do ZIP.

## Limites de confiança

Nomes como `OnlineBalance`, `ElapsedDays` e `DiscoveredProducts` são
normalizados porque a própria chave fornece evidência direta. Estruturas sem
documentação ou evidência suficiente não recebem rótulos estratégicos. O
snapshot pode conter dados redundantes de propósito: preservar evidência é mais
importante do que compactar prematuramente.

## Evolução

Mudanças futuras devem versionar `metadata.schema_version`, adicionar migrações
SQLite e manter leitores para snapshots anteriores. Uma interface gráfica deve
consumir as APIs do domínio, nunca acessar o ZIP ou o save diretamente.
