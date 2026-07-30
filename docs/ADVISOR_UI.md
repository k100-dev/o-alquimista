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
8. O jogador pode consultar o mentor local sobre a decisão atual.
9. Quando a identidade é apenas candidata, o jogador pode confirmar que dois
   capítulos pertencem à mesma jornada, sem fundi-los.
10. Uma missão ativa define o experimento da próxima sessão.
11. No novo export, a Câmara compara os momentos e apresenta o retorno da
    sessão antes do próximo conselho.

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
- `POST /api/campaign-association`;
- `POST /api/mentor`;
- `POST /api/import`.

`POST /api/campaign-association` aceita somente `confirm` ou `revert`. A
operação atualiza o estado da associação candidata em uma transação local. Ela
não move snapshots, não funde campanhas, não apaga evidências e não escreve no
save.

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

- **Capítulo da campanha** transforma fatos observados em uma narrativa curta
  de progressão. É uma camada do companion, não o rank oficial do jogo.
- **Caminho da operação** organiza a evolução em Despertar, Transmutação,
  Círculo e Ascensão.
- **Quadro de missões** permite assumir um objetivo e acompanhar localmente o
  ritual “assumir, executar, reimportar”.
- **Sala de Conselho** responde perguntas sobre caixa, expansão, gargalos,
  equipe, estoque e memória usando exclusivamente a projeção curada do export.
- **Retorno à Câmara** compara o snapshot anterior ao novo, apresenta deltas e
  relaciona as mudanças à missão ativa sem alegar causalidade.
- **Ciclo de acompanhamento** torna explícito o propósito do produto:
  conversar, assumir, jogar, exportar e aprender.
- **Selos da jornada** reconhecem marcos observáveis sem se apresentar como
  achievements oficiais do jogo.
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
- **Memória da campanha** troca identificadores técnicos por dia e horário do
  jogo, permite confirmar capítulos sugeridos e libera uma leitura real de
  antes e depois para o mentor.
- **O que sabemos** torna explícita a diferença entre observado e ausente.

O modo inicial revela apenas narrativa, recursos essenciais e missões. O painel
analítico completo fica atrás de uma ação explícita de aprofundamento, evitando
que o usuário precise compreender todas as métricas antes de agir.

## Estado interativo

A missão selecionada, o checklist, a conversa e o último retorno ficam em
`localStorage`. A missão é isolada por campanha; a conversa acompanha a
jornada no dispositivo para não ser perdida quando um novo export candidato
recebe outro identificador. Esse estado:

- permanece somente no navegador local;
- não altera o save;
- não é enviado ao servidor;
- não transforma uma marcação manual em evidência analítica;
- serve apenas para orientar a sessão do jogador.

A confirmação de continuidade fica no SQLite porque deve sobreviver à próxima
abertura da Câmara. Ela continua sendo uma declaração explícita do jogador,
não um fato extraído do save. O estado pode ser revertido na própria interface
e as campanhas continuam fisicamente separadas.

O terceiro passo da missão só é concluído automaticamente depois da importação
de outro export. A Câmara então utiliza os IDs exatos dos snapshots anterior e
atual, inclusive quando ambos pertencem à mesma campanha confirmada.

## Mentor conversacional local

O mentor não é um chatbot de rede. As respostas são determinísticas, testáveis
e baseadas em tópicos reconhecidos na pergunta:

- próximo movimento;
- expansão e compras;
- dinheiro e liquidez;
- gargalos;
- equipe e delegação;
- estoque, produtos e receitas;
- valor do próximo export.

Cada resposta contém evidências curadas, uma ação, nível de confiança e a
limitação da análise. O texto nunca recebe `raw`, `unknown_fields`, caminhos
locais ou identificadores internos.

## Identidade visual

O retrato original do personagem está em
`ui/assets/alchemist-portrait-v1.png`. Ele foi produzido para esta interface,
sem texto, logotipo ou semelhança intencional com personagem existente.

## Limites atuais

- a interface apresenta fatos e regras locais já sustentadas pelo motor;
- lucro por hora, ROI e capacidade não são exibidos sem dados suficientes;
- campanhas candidatas continuam separadas, mesmo quando o jogador confirma a
  continuidade entre capítulos;
- comparações candidatas mostram correlação, não causalidade;
- progresso manual de missão não substitui validação por novo snapshot;
- a conversa compreende um conjunto explícito de intenções e não substitui um
  modelo generativo externo;
- o retorno compara mudanças observadas, mas não prova que a missão as causou;
- o navegador é o contêiner visual desta primeira versão;
- o empacotamento `.exe` é uma etapa posterior e não altera o motor analítico.
