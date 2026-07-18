# Segurança

## Origem read-only

- ZIP aberto em `r`/`rb`;
- hash em blocos, sem extração;
- fingerprint conferida novamente ao fim para detectar alteração concorrente;
- extração somente em `TemporaryDirectory`;
- cópia com `xb` no temporário;
- ZIP, save e arquivos do jogo nunca são destinos;
- saída dentro de uma pasta de save fonte é bloqueada.
- relatórios analíticos não podem sobrescrever o SQLite nem usar destino `.zip`.

## Entradas bloqueadas

- caminhos absolutos, UNC e drives Windows;
- segmentos `..` e ADS;
- links simbólicos e arquivos especiais;
- duplicatas e colisões de caixa;
- destinos resolvidos fora do temporário;
- arquivos fora da raiz lógica do save;
- profundidade maior que 16.

## Limites

- ZIP: 128 MiB;
- diretório central: 16 MiB;
- entradas: 5.000;
- nome: 1.024 caracteres;
- entrada descompactada: 32 MiB;
- total descompactado: 256 MiB;
- razão de compressão: 200:1 a partir de 1 MiB;
- ZIP64 e ZIP multipartes: rejeitados.

Os limites são verificados antes e durante a extração. A raiz temporária é
limpa em sucesso ou falha.

## Privacidade

Não há rede. Caminhos absolutos não entram em snapshots, timeline, evidências
ou novos registros. Fixtures são sintéticas. Dados brutos do save podem conter
identificadores e devem permanecer locais.
