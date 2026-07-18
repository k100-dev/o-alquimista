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
- dispositivos reservados do Windows, sem distinção entre maiúsculas e
  minúsculas: `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`,
  `CONIN$` e `CONOUT$`;
- links simbólicos e arquivos especiais;
- duplicatas e colisões de caixa;
- destinos resolvidos fora do temporário;
- arquivos fora da raiz lógica do save;
- profundidade maior que 16.

A validação de dispositivos ocorre por componente antes da extração. Pontos e
espaços finais são removidos para a comparação, e o nome anterior à primeira
extensão é avaliado. Assim, variantes como `CON.txt`, `NUL.dat`,
`folder/COM1.json` e `CONOUT$.txt` são bloqueadas sem rejeitar nomes comuns como
`CONTAINER.json`, `COM10.json` ou `myCON.txt`.

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
