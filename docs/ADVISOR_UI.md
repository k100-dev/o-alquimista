# Câmara do Alquimista

## Objetivo

A Câmara é a primeira interface consultiva do projeto. Ela transforma o
snapshot normalizado e a análise determinística em uma visão curta para o
jogador: situação financeira, capacidade instalada, alertas, plano de ação,
portfólio, equipe, comparação exploratória e histórico da campanha.

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
- `GET /api/comparison?current_campaign_id=...&baseline_campaign_id=...`;
- `POST /api/import`.

## Linguagem da interface

A Câmara evita o rótulo genérico “estruturas”. Tudo que está instalado em uma
propriedade continua sendo um **objeto**, mas a experiência o separa em:

- **base produtiva**: cultivo, mistura, processamento e embalagem;
- **armazenamento**: recipientes e prateleiras reconhecidos;
- **apoio**: móveis, utilidades e resíduos;
- **não classificado**: item preservado cujo papel ainda não foi comprovado.

“Ativo” e “ocioso” só aparecem para equipamentos cujo estado é legível no
save. Um equipamento reconhecido sem estado não é presumido ocioso.

## Camadas consultivas

- **Qualidade do diagnóstico** mede a sustentação da análise, não o desempenho
  do jogador.
- **Plano de agora** converte regras em ação, motivo, impacto e sinal de
  conclusão.
- **Grimório comercial** mostra preços e valores de referência, nunca os
  apresenta como lucro ou demanda.
- **Equipe e cobertura** identifica funções e delegação sem inventar
  produtividade individual.
- **Transmutação temporal** compara exports relacionados de forma exploratória
  sem consolidar campanhas candidatas.
- **O que sabemos** torna explícita a diferença entre observado e ausente.

## Limites atuais

- a interface apresenta fatos e regras locais já sustentadas pelo motor;
- lucro por hora, ROI e capacidade não são exibidos sem dados suficientes;
- campanhas candidatas continuam separadas;
- comparações candidatas mostram correlação, não causalidade;
- o navegador é o contêiner visual desta primeira versão;
- o empacotamento `.exe` é uma etapa posterior e não altera o motor analítico.
