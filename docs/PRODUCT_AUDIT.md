# Auditoria de produto e roadmap assistencial

## Decisão de produto

O Alquimista deve ser um companion de decisão, não um visualizador de JSON. O
valor recorrente nasce deste ciclo:

```text
exportar -> entender -> escolher -> jogar -> exportar novamente -> aprender
```

Cada importação precisa responder, em linguagem de jogador:

1. o que mudou;
2. por que isso importa;
3. qual decisão merece atenção agora;
4. como testar essa decisão na próxima sessão;
5. o que o próximo export deve provar.

## Auditoria do corpus local

O corpus ignorado pelo Git contém cinco exports reais da mesma versão
observada do jogo, distribuídos em três dias da campanha. Eles mostram
progressão material em propriedades, equipe, produtos descobertos e objetos
operacionais.

O campo forte de identidade não está presente nesses exports. O motor agiu
corretamente ao criar campanhas candidatas independentes, mas essa segurança
virou um problema de experiência: a interface não conseguia montar a jornada
que o jogador reconhece como uma única campanha.

A primeira entrega desta auditoria resolve esse bloqueio com uma confirmação
humana local e reversível. Ela não altera o save, não mistura proveniência e
não promove sinais fracos a fatos.

## Registro da entrega vertical

### Linha do tempo confirmada

- **Problema resolvido:** exports reconhecíveis pelo jogador apareciam como
  campanhas técnicas independentes e impediam o companion de acompanhar a
  evolução.
- **Usuário beneficiado:** jogador com dois ou mais exports da mesma campanha,
  mas sem identificador forte presente no save.
- **Dados necessários:** associação candidata já calculada, snapshot mais
  recente e tempo interno observado em cada export.
- **Regra de negócio:** somente uma associação candidata existente pode ser
  confirmada; a confirmação muda para `explicitly_linked` e pode voltar a
  `candidate`.
- **Estados:** isolado, sugerido e confirmado.
- **Componentes:** persistência transacional, projeção do advisor, rota HTTP
  local, painel de memória e revisão comparativa.
- **Eventos:** confirmar, comparar e desfazer.
- **Testes:** API end-to-end com dois ZIPs sintéticos, confirmação, revisão,
  reversão, ausência de merge e projeção sem `raw`.
- **Critério de aceite:** a UI mostra dois momentos conectados, produz o
  antes/depois, alimenta o mentor e mantém duas campanhas analíticas separadas.

## Pontos fortes atuais

- importação ZIP local, segura e read-only;
- deduplicação e memória SQLite;
- precisão monetária com `Decimal`;
- timeline e evidências determinísticas;
- leitura operacional de propriedades e recipientes;
- missões, retorno de sessão e mentor local;
- interface original, responsiva e sem dependências externas;
- linguagem epistemológica que separa observado, derivado e indisponível.

## Lacunas de valor

### Resolvida nesta entrega

- capítulos candidatos agora podem formar uma memória confirmada;
- hashes deixaram de ser o rótulo principal na seleção da campanha;
- o usuário recebe uma revisão antes/depois imediatamente após confirmar;
- o mentor passa a conhecer a quantidade real de momentos confirmados.

### Próximas

- o mentor ainda reconhece um conjunto fechado de intenções;
- recomendações ainda são majoritariamente regras gerais;
- o aplicativo não calcula lucro por hora, ROI ou demanda sem observações
  suficientes;
- o fluxo de importação ainda exige seleção manual do ZIP;
- o estado de missões e conversa vive no navegador, não em um perfil portátil;
- distribuição `.exe`, atualização e recuperação de banco ainda não estão
  empacotadas como produto.

## Arquitetura-alvo

```text
DataSourceAdapter
  -> ExportAdapter (disponível)
  -> FolderWatchAdapter (planejado)
  -> RealTimeAdapter (indisponível sem fonte oficial)
       |
       v
ImportPipeline read-only
       |
       v
Modelo canônico + proveniência
       |
       v
Memória analítica + continuidade confirmada
       |
       v
Decision Engine
       |
       +-> Mentor
       +-> Missões
       +-> Retorno da sessão
       +-> Interface
```

Todos os adaptadores futuros devem produzir a mesma entrada canônica. Assim, a
UI e o motor consultivo não dependem do modo de coleta.

## Modos de uso

### Export manual — disponível

O usuário exporta o ZIP pelo jogo e o abre na Câmara. É o modo com melhor
combinação de segurança, previsibilidade e fidelidade.

### Folder Watch — próximo experimento

O usuário escolhe uma pasta de exports. O aplicativo observa somente novos
ZIPs completos e chama o pipeline existente. O watcher não toca no processo do
jogo e deve exigir confirmação antes de importar arquivos ambíguos.

### Tempo real — indisponível

Não existe nesta base uma fonte oficial documentada para telemetria ao vivo.
Sem essa fonte, “tempo real” não deve ser prometido. Leitura de memória,
injeção, modificação do executável ou escrita no save permanecem fora do
escopo.

## Auditoria de integração oficial

A página oficial do jogo no Steam documenta Windows, Steam Cloud, conquistas,
modo individual e cooperativo, além de destacar que o título permanece em
Early Access:

<https://store.steampowered.com/app/3164500/Schedule_I/>

Na pesquisa de fontes oficiais realizada nesta auditoria, não foi localizada
uma API pública de telemetria do estado da campanha. A existência de Steam
Cloud também não transforma o save em uma interface de integração. Por isso, o
produto permanece `export-first` e trata qualquer automação de pasta como uma
conveniência em torno do mesmo ZIP, não como leitura em tempo real.

## Roadmap priorizado

### P0 — Retenção e clareza

- memória confirmada de campanha;
- onboarding em três passos;
- explicar métricas sempre no ponto de uso;
- mostrar uma decisão prioritária e um critério de sucesso;
- retorno da sessão com mudanças e limitações.

**Métrica:** percentual de usuários que importa um segundo export e abre o
retorno.

### P1 — Mentor que acompanha

- persistir conversa e missão no perfil local;
- registrar decisões declaradas pelo jogador;
- comparar decisão, resultado observado e hipótese;
- criar perguntas sugeridas por contexto;
- oferecer histórico legível de conselhos aceitos, ignorados e inconclusivos.

**Métrica:** sessões com ao menos uma pergunta e uma missão assumida.

### P2 — Economia comprovável

- mapear custos e preços observados;
- construir janelas temporais confirmadas;
- estimar fluxo apenas quando início e fim forem comparáveis;
- simulador de investimento com premissas visíveis;
- distinguir lucro, caixa, patrimônio e valor de referência.

**Métrica:** recomendações financeiras com evidência completa e nenhuma
premissa oculta.

### P3 — Operação explicável

- gargalos por estação e propriedade;
- cobertura de equipe por função;
- alertas de recipiente cheio, estação sem insumo e fluxo interrompido;
- comparação de configuração operacional;
- missões específicas por laboratório.

**Métrica:** alertas que desaparecem após uma ação e um novo export.

### P4 — Produto desktop

- Folder Watch opcional;
- empacotamento `.exe`;
- backup e migração assistidos;
- atualização segura;
- exportação de diagnóstico sanitizado para suporte;
- modo totalmente offline.

**Métrica:** instalação e primeira análise sem terminal.

## Critérios de honestidade

- quantidade de equipamentos não é eficiência;
- preço de referência não é lucro;
- correlação entre exports não prova causalidade;
- confirmação humana não vira fato nativo do save;
- ausência de campo não vira zero;
- indicador indisponível permanece indisponível;
- nenhum recurso futuro pode exigir modificar o save original.
