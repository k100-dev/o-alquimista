# Câmara do Alquimista

## Objetivo

A Câmara é a primeira interface consultiva do projeto. Ela transforma o
snapshot normalizado e a análise determinística em uma visão curta para o
jogador: situação financeira, ocupação observada, instalações, alertas,
recomendações e histórico da campanha.

O foco da interface não é expor todos os campos do save. Dados `raw`,
`unknown_fields`, caminhos locais e identificadores internos não fazem parte da
projeção pública.

## Execução local

```powershell
alquimista ui --database ".\data\alquimista.sqlite3"
```

A aplicação abre em `http://127.0.0.1:8765/`. Para escolher outra porta:

```powershell
alquimista ui --database ".\data\alquimista.sqlite3" --port 8877
```

Use `--no-browser` quando quiser iniciar apenas o servidor.

## Fluxo

1. O usuário seleciona o ZIP gerado por **Export Save**.
2. O navegador envia o arquivo somente ao servidor local.
3. O servidor grava uma cópia efêmera em diretório temporário.
4. O parser seguro lê o ZIP em modo read-only.
5. Snapshot, evidências e análise são persistidos no SQLite local.
6. A cópia temporária é removida.
7. A interface recebe apenas uma projeção curada para apresentação.

Nenhuma chamada de rede externa é necessária. O servidor rejeita endereços de
escuta que não sejam locais e aplica limite de 64 MB ao upload.

## Arquitetura

- `advisor.py`: projeção curada do domínio para a interface;
- `ui_server.py`: servidor HTTP local, importação e API;
- `ui/`: HTML, CSS e JavaScript sem dependências externas;
- `database.py` e `analysis.py`: memória, evidências e regras;
- `parser.py`: leitura segura do export.

As rotas locais são:

- `GET /api/health`;
- `GET /api/dashboard`;
- `GET /api/dashboard?campaign_id=...`;
- `POST /api/import`.

## Limites atuais

- a interface apresenta fatos e regras locais já sustentadas pelo motor;
- lucro por hora, ROI e capacidade não são exibidos sem dados suficientes;
- campanhas candidatas continuam separadas;
- o navegador é o contêiner visual desta primeira versão;
- o empacotamento `.exe` é uma etapa posterior e não altera o motor analítico.
