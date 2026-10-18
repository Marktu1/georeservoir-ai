# ADR-0001 — Arquitetura do núcleo numérico

- Estado: aceite · Data: 2026-10-18

## Contexto
O produto precisa de cálculos de engenharia rastreáveis, reutilizáveis por uma futura API, UI e por scripts, sem acoplamento a infraestrutura.

## Decisão
- Pacote Python puro `georeservoir` (layout `src/`), dependências de runtime apenas NumPy e SciPy.
- Camadas: `common/` (exceções, unidades, validação, `CalculationRecord`) e `engineering/` (um módulo por domínio).
- Funções puras, sem estado global; todas as funções públicas devolvem um `CalculationRecord` imutável cujo hash depende só do método, versão e entradas.
- Parâmetros físicos sempre explícitos e só por palavra-chave (sem valores por omissão escondidos).
- O núcleo não importa nada de HTTP, UI, base de dados ou rede.

## Alternativas consideradas
- Devolver arrays/dicionários simples: mais leve, mas perde proveniência (o diferencial do produto).
- Pydantic para o registo: validação rica, mas dependência extra no núcleo (spec §7.2).
- Pint para unidades: robusto, mas dependência extra e custo de desempenho; conversões explícitas bastam nesta fase.

## Consequências
- Qualquer resultado é serializável para JSON e persistível sem alterações (Fase 3+).
- Custo: um pouco de verbosidade em cada função (construção do registo).
