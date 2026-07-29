# Milestone 3 — Os Olhos do Alquimista

## Objetivo

Transformar objetos genéricos de propriedades em um modelo operacional
explicável. O milestone deve permitir que o sistema reconheça instalações,
recipientes e estados presentes no save antes de estimar gargalos, capacidade
ou retorno financeiro.

## Evidência inicial

O corpus local da versão `0.4.5f2` confirmou que objetos de propriedade possuem
um envelope com `DataType` e `BaseData`. Dentro de `BaseData` foram observados:

- `ItemString.ID`, que identifica o item instalado;
- recipientes `Contents`, `MixerContents`, `OutputContents` e
  `ProductContents`;
- estado de cultivo em `PlantData`;
- operação de mistura em `CurrentMixOperation` e `CurrentMixTime`;
- estado de objetos alternáveis em `IsOn`.

Os exports reais permanecem ignorados pelo Git. Fixtures do repositório são
sintéticas e sanitizadas.

## Entregas

### 3.1 — Objetos operacionais

- decodificar `BaseData` e `ItemString`;
- gerar identificador pseudonimizado e determinístico por instância;
- classificar categorias estruturais observáveis;
- preservar tipo, origem, estado e dados desconhecidos;
- contabilizar slots e ocupação dos recipientes;
- incluir inventários internos das instalações no inventário da propriedade.

### 3.2 — Estados produtivos

- diferenciar estação ativa, ociosa e desconhecida;
- normalizar cultivo, mistura e embalagem sem inventar unidades;
- preservar produto, ingrediente, qualidade, quantidade e marcador temporal da
  operação de mistura quando observados;
- comparar instalação, remoção e mudança de estado entre snapshots;
- gerar evidências específicas para cada mudança operacional.

### 3.3 — Perfil da propriedade

- consolidar instalações por categoria e item;
- separar objetos produtivos, armazenamento, utilidades e decoração;
- calcular somente métricas comprováveis, como slots observados e ocupados;
- emitir alertas de dados insuficientes quando throughput ou tempo de ciclo não
  estiverem disponíveis.

### 3.4 — Inteligência operacional inicial

- detectar estações sem insumos observáveis;
- detectar recipientes totalmente ocupados;
- detectar vasos com e sem planta;
- detectar mudanças de mixagem e embalagem;
- criar recomendações com `rule_id`, evidências, limitações e confiança.

## Não objetivos

- não calcular lucro por hora sem janela temporal suficiente;
- não afirmar capacidade produtiva apenas pela quantidade de estações;
- não atribuir função a item desconhecido por semelhança de nome;
- não criar GUI neste milestone;
- não ler memória do processo do jogo;
- não modificar save, ZIP ou diretório do jogo;
- não enviar dados para serviços externos.

## Primeira entrega vertical

A primeira entrega adiciona `OperationalObject` e `OperationalContainer`,
decodifica os envelopes reais observados, corrige a leitura de inventário
interno das propriedades e amplia o relatório de snapshot com:

- item instalado;
- categoria estrutural;
- estado observável;
- slots ocupados;
- slots totais observados.

Comparações passam a correlacionar instâncias pelo identificador estável e a
timeline inclui totais observados de equipamentos e slots. Snapshots legados
sem a nova coleção retornam estado `unknown`, nunca remoção presumida.

Slots não equivalem a throughput nem a capacidade por hora.

## Validação controlada

Dois exports reais consecutivos validaram a substituição de uma operação de
mistura na mesma instância de estação. Produto, ingrediente, qualidade,
quantidade, marcador temporal e ocupação foram diferenciados, enquanto os
ZIPs permaneceram byte a byte inalterados.

A coleta também registrou mudanças paralelas em outras instalações. Por isso,
uma recomendação futura não poderá atribuir causalidade a toda diferença entre
exports; ela deverá selecionar evidências da instância e da atividade
correspondentes.

## Critérios de aceite

- fixtures sintéticas reproduzem o envelope `BaseData`;
- IDs internos não aparecem no identificador público da instância;
- leitura do mesmo ZIP é determinística;
- inventários internos não são perdidos;
- ausência continua diferente de vazio;
- dados desconhecidos continuam preservados;
- todos os testes anteriores permanecem aprovados;
- exports reais permanecem byte a byte inalterados;
- nenhuma fixture contém dados reais.
