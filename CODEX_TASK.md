# O Alquimista — orientação de desenvolvimento

Trabalhe neste repositório preservando a regra central: toda leitura de saves do
Schedule I é estritamente read-only. Nunca altere ZIPs importados, saves
originais ou a pasta de instalação do jogo.

## Estado do Milestone 1

A base técnica importa exports ZIP, detecta a raiz do save, valida os quatro
JSONs essenciais, gera snapshot normalizado, preserva dados desconhecidos,
mantém histórico SQLite e oferece a CLI `alquimista`.

## Próximo objetivo sugerido

Validar os modelos normalizados contra fixtures sanitizadas de diferentes
versões do jogo e implementar análise baseada em evidências entre snapshots:

1. evolução de caixa e inventário;
2. alterações em propriedades, objetos e funcionários;
3. distinção explícita entre observação e inferência;
4. milestones e recomendações gerados apenas quando houver evidência citável;
5. migração versionada do schema de snapshot e do SQLite.

## Definition of done contínua

- `python -m unittest discover -s tests -v` passa;
- `python -m pytest` passa quando pytest está disponível;
- comandos existentes permanecem compatíveis;
- nenhum código escreve no ZIP ou na raiz de um save;
- fixtures não contêm IDs pessoais, GUIDs reais ou saves completos;
- campos não compreendidos continuam em `unknown` ou `raw`, com origem.
