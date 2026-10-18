# Roadmap

Estado por nível de maturidade (M0 = planeado, não implementado). Portões conforme o Prompt Mestre v3.0, secção 9.

## Fase 0 — Núcleo Científico v0.1 (esta entrega)

| Item | Estado |
|---|---|
| Camada comum + `CalculationRecord` | M2 |
| Minimum Curvature | **M3** (caso Bourgoyne/Amorin); ISCWSA 3D pendente |
| Petrofísica | Archie **M3** (caso KGS); IGR, Vsh ×4, φD, φS em M2 |

**Portão da Fase 0: cumprido em 2026-10-18.** Cada módulo P0 tem uma função central em M3 com caso publicado reproduzido; relatório de validação gerado no repositório; CI verde em Python 3.11 e 3.12 (GitHub Actions, run 39086151294). Reforços recomendados na Fase 1: casos publicados para Vsh e porosidades, e o caso ISCWSA 3D.

## Fase 1 — Núcleo completo v0.2.0

| Módulo | Estado |
|---|---|
| DCA (Arps) | conversão nominal↔efetivo **M3** (SPEE REP #6); restantes M2 |
| Nodal | Vogel e IPR composta **M3** (notas de aula publicadas); restantes M2; correlações multifásicas M0 |
| Bourdet | M2 (drawdown); superposição M0 |
| Balanço material | M2 |
| Monte Carlo P10/P50/P90 | M2 (Archie Sw e Arps EUR) |

**Portão da Fase 1 (todos os módulos ≥ M2, metade ≥ M3):** 8 módulos (common, well_path, petrophysics, dca, nodal, bourdet, material_balance, uncertainty), todos ≥ M2; 4 com pelo menos uma função em M3 (well_path, petrophysics, dca, nodal). A evidência M3 do nodal é a mais fraca (notas de aula). Revisão adversarial independente feita e corrigida (ver CHANGELOG 0.2.0).

## Planeado (M0 — não existe código)

| Item | Prioridade |
|---|---|
| Correlações TPR multifásicas (Hagedorn–Brown, Beggs & Brill) | P1 |
| Derivada de Bourdet em tempo de superposição (buildup) | P1 |
| Aquíferos Fetkovich e Carter–Tracy | P2 |
| Monte Carlo com correlação entre entradas | P2 |
| Petrofísica: correções de gás/argila/compactação, Raymer–Hunt–Gardner, densidade-neutrão | P1 |
| Petrofísica: Simandoux, Indonesia, Dual-Water | P1 |
| Correção de declinação/convergência; transformação geodésica | Fase 2+ |
| Leitura LAS 2.0/3.0, surveys; DLIS/SEG-Y depois | Fase 2 |
| API FastAPI, UI web, piloto, IA assistiva | Fases 3–6 |
