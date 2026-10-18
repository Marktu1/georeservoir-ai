# Roadmap

Estado por nível de maturidade (M0 = planeado, não implementado). Portões conforme o Prompt Mestre v3.0, secção 9.

## Fase 0 — Núcleo Científico v0.1 (esta entrega)

| Item | Estado |
|---|---|
| Camada comum + `CalculationRecord` | M2 |
| Minimum Curvature | M2 — falta caso de literatura (ISCWSA) para M3 |
| Petrofísica (IGR, Vsh ×4, φD, φS Wyllie, Archie) | M2 — falta caso de literatura para M3 |

**Portão da Fase 0 ainda não cumprido:** P0 em M3 exige reproduzir pelo menos um caso publicado por módulo (ver `docs/validation/`). CI está criado mas não foi executado remotamente.

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
