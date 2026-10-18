# ADR-0002 — Licença (decisão pendente do fundador)

- Estado: **proposto — a decidir por Marcos Zola Daniel João** · Data: 2026-10-18

Até à decisão: "todos os direitos reservados" (ver `LICENSE`).

## Opções
| Opção | Efeito | Referência de mercado |
|---|---|---|
| Proprietária | Controlo total; dificulta adoção académica e a tese de "validação pública". | Suites comerciais de QI/petrofísica. |
| Open-core GPL-3.0 + edição comercial | Núcleo aberto gera comunidade e confiança; extensões comerciais financiam. GPL impede terceiros de fechar derivados. | OpendTect (núcleo GPL, OpendTect Pro e pacote ML comerciais; licença Pro permite plugins fechados de parceiros). |
| Open-core Apache-2.0 / MIT + comercial | Adoção máxima (inclui empresas); concorrentes podem reutilizar sem devolver. | — |
| Fonte disponível (BSL/FSL) | Código visível para auditoria; uso comercial restrito por um período. | — |

Sugestão de análise (não decisão): o "dossiê de validação público" combina naturalmente com um núcleo aberto; avaliar com um jurista angolano antes de publicar.

## Licenças das dependências
| Dependência | Uso | Licença |
|---|---|---|
| NumPy | runtime | BSD-3-Clause |
| SciPy | runtime | BSD-3-Clause |
| pytest, pytest-cov | dev | MIT |
| Hypothesis | dev | MPL-2.0 |
| Ruff | dev | MIT |
| mypy | dev | MIT |
| hatchling | build | MIT |
