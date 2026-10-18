# Roadmap

Estado por nível de maturidade (M0 = planeado, não implementado). Portões conforme o Prompt Mestre v3.0, secção 9.

## Fase 0 — Núcleo Científico v0.1 (esta entrega)

| Item | Estado |
|---|---|
| Camada comum + `CalculationRecord` | M2 |
| Minimum Curvature | **M3** (caso Bourgoyne/Amorin); ISCWSA 3D pendente |
| Petrofísica | Archie **M3** (caso KGS); IGR, Vsh ×4, φD, φS em M2 |

**Portão da Fase 0: cumprido em 2026-10-18.** Cada módulo P0 tem uma função central em M3 com caso publicado reproduzido; relatório de validação gerado no repositório; CI verde em Python 3.11 e 3.12 (GitHub Actions, run 39086151294). Reforços recomendados na Fase 1: casos publicados para Vsh e porosidades, e o caso ISCWSA 3D.

## Planeado (M0 — não existe código)

| Item | Prioridade |
|---|---|
| Decline Curve Analysis (Arps) com declínio terminal | P1 |
| Nodal: IPR linear, Vogel, IPR composta, TPR tabelada, solver de interseções | P1 |
| Derivada de Bourdet (drawdown) | P1 |
| Balanço material Havlena–Odeh | P2 |
| Petrofísica: correções de gás/argila/compactação, Raymer–Hunt–Gardner, densidade-neutrão | P1 |
| Petrofísica: Simandoux, Indonesia, Dual-Water | P1 |
| Correção de declinação/convergência; transformação geodésica | Fase 2+ |
| Leitura LAS 2.0/3.0, surveys; DLIS/SEG-Y depois | Fase 2 |
| API FastAPI, UI web, piloto, IA assistiva | Fases 3–6 |
