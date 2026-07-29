# Caminho para aplicativo Windows

## Decisão

A interface foi construída como aplicação web local porque isso permite iterar
rapidamente no painel sem acoplar o motor analítico a uma tecnologia de janela.
O parser, o SQLite e as regras continuam em Python; a camada visual usa somente
HTML, CSS e JavaScript locais.

## Primeira distribuição `.exe`

Depois que o fluxo da Câmara estiver estável, a primeira opção recomendada é
empacotar a CLI e os arquivos visuais com PyInstaller:

1. incluir `o_alquimista/ui` como dados do pacote;
2. gerar inicialmente uma distribuição `onedir`, mais fácil de diagnosticar;
3. validar Windows 10 e 11;
4. gerar uma versão `onefile` somente depois;
5. manter o SQLite e os imports fora do executável, em pasta de dados do
   usuário.

Essa etapa adicionará uma dependência apenas no ambiente de build, não no
runtime do projeto fonte.

## Janela nativa futura

Quando a experiência visual estiver validada, o mesmo servidor poderá ser
aberto dentro de uma janela WebView2. As opções são:

- `pywebview`, com integração direta ao processo Python;
- Tauri, se o projeto precisar de instalador, atualização e integração de
  desktop mais avançadas.

Não é necessário reescrever o parser ou o motor analítico para adotar qualquer
uma dessas opções.

## Segurança da distribuição

O aplicativo final deve:

- escutar somente em loopback;
- usar uma porta local escolhida dinamicamente ou validada;
- não incluir saves de teste;
- não enviar telemetria;
- manter ZIPs e bancos fora do pacote;
- preservar as proteções contra Zip Slip, Zip Bomb e caminhos inseguros;
- exibir claramente que a análise é local e read-only.
