# O Alquimista

O Alquimista é um companion desktop estratégico, local e read-only para o
**Schedule I**. Este milestone entrega a base técnica: importa diretamente o
ZIP produzido por **Export Save**, normaliza dados observados, preserva campos
ainda desconhecidos e mantém um histórico SQLite. Interface gráfica não faz
parte deste milestone.

## Regra de segurança

O Alquimista nunca escreve no ZIP importado, na pasta de instalação do jogo ou
em um save original. O ZIP é aberto somente para leitura, validado contra path
traversal e links simbólicos, extraído em um diretório temporário exclusivo e
removido ao final da operação. Snapshots, relatórios e bancos são criados apenas
nos caminhos de saída escolhidos pelo usuário.

Mantenha Steam Cloud e backups normais ativos. Não use um diretório de save do
jogo como `--database`. A CLI rejeita `--out` dentro de uma pasta de save usada
como fonte e rejeita um banco com o mesmo caminho do ZIP original.

## Arquitetura

O pacote Python principal é `o_alquimista`:

- `archive.py`: valida ZIP, bloqueia entradas inseguras, extrai temporariamente
  e detecta a raiz real do save;
- `parser.py`: lê os JSONs sem escrita e produz modelos normalizados;
- `models.py`: modelos tipados, origens, campos `unknown`/`raw`, milestones e
  recomendações;
- `database.py`: schema e repositório SQLite;
- `cli.py`: comandos `alquimista`;
- `diff.py` e `report.py`: comparação e relatório preservados do protótipo.

O namespace `schedule_intelligence` e o comando `schedule-intel` permanecem
como compatibilidade temporária. Código novo deve usar `o_alquimista` e
`alquimista`.

Detalhes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e
[docs/SAVE_FORMAT.md](docs/SAVE_FORMAT.md).

## Requisitos e instalação

- Python 3.11 ou superior;
- nenhuma dependência de runtime fora da biblioteca padrão.

No PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Comandos

Importar um Export Save e persistir o snapshot:

```powershell
alquimista import "C:\exports\save.zip" --database ".\data\alquimista.sqlite3"
```

Gerar `snapshot.json` e `report.md` sem persistir:

```powershell
alquimista snapshot "C:\exports\save.zip" --out ".\output\current"
```

Consultar o histórico:

```powershell
alquimista history --database ".\data\alquimista.sqlite3"
```

Comparar dois snapshots (recurso preservado do protótipo):

```powershell
alquimista diff ".\output\before\snapshot.json" `
  ".\output\after\snapshot.json" --out ".\output\diff.json"
```

Para executar os testes sem dependências externas:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
python -m unittest discover -s tests -v
```

As classes `unittest` também são descobertas pelo `pytest`, quando ele estiver
instalado:

```powershell
python -m pytest
```

## Dados normalizados

O snapshot inclui metadata, financeiro, tempo, progressão, produtos,
inventários, propriedades, NPCs, funcionários, veículos e arquivos/campos não
mapeados. Valores normalizados carregam referências ao arquivo e campo de
origem. Dados sem interpretação comprovada são preservados como `unknown` ou
`raw`; o programa não inventa semântica.

Para o mesmo ZIP, `snapshot.json` é determinístico: não contém o horário da
operação, não guarda caminhos absolutos locais e ordena chaves JSON. O horário
real de importação é registrado somente no SQLite.

O SQLite mantém as entidades `campaigns`, `imports`, `snapshots`,
`milestones` e `recommendations`. Neste milestone, milestones e recomendações
possuem modelos e persistência, mas não são gerados automaticamente.

## Limitações conhecidas

- São essenciais `Money.json`, `Products.json`, `Time.json` e `Rank.json`.
- Por segurança, cada ZIP aceita no máximo 5.000 entradas, 32 MiB por entrada,
  256 MiB descompactados no total e razão de compressão 200:1 para entradas a
  partir de 1 MiB.
- ZIPs com duas raízes de save igualmente prováveis são rejeitados como
  ambíguos.
- Schemas internos do jogo podem mudar entre versões.
- Contagens e valores são observações dos campos presentes; significado
  estratégico, custo real, lucro, ROI e causalidade ainda não são inferidos.
- A identidade de campanha é agrupada pelo nome do ZIP, sem armazenar seu
  caminho local; arquivos de mesmo nome podem ser agrupados juntos.
- Conteúdo `raw/unknown` pode incluir identificadores existentes no save. Os
  artefatos são locais, mas devem ser tratados como dados potencialmente
  sensíveis.
- Não há interface gráfica, monitoramento de pastas, chamadas de rede ou
  integração com arquivos da instalação do jogo.
