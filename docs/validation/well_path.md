# Validação — Minimum Curvature

Maturidade atual: **M2**. Resultados numéricos em `REPORT.md` (gerado).

## Casos (tests/validation/cases/)
| ID | Tipo | O que prova |
|---|---|---|
| VAL-WP-001 | analítico | Poço vertical: TVD = MD, deslocamento e dogleg nulos, para azimutes arbitrários. |
| VAL-WP-002 | analítico | Tangente inclinada (30°, 60°) contra trigonometria exata. |
| VAL-WP-003 | analítico | Arco circular R = 500 m (0°→90°) com 2 estações: ponto final e DLS exatos. |
| VAL-WP-004 | analítico | Mesmo arco com 10 estações: todas as estações intermédias sobre o círculo. |
| VAL-WP-L01 | literatura | ISCWSA test well #1 — **fonte por verificar**; não conta para M3. |

Os oráculos são fórmulas fechadas geradas por `scripts/generate_validation_cases.py`, que não importa `georeservoir` (não circulares). Tolerância 1e-11 m (+1e-13 relativo), ~10× o erro de arredondamento esperado; erro observado ≤ ~1e-13 m (ver REPORT.md).

## Testes de propriedades (tests/engineering/test_well_path.py)
- Rotação: somar θ a todos os azimutes roda (E, N) por θ; TVD e dogleg invariantes.
- Subdivisão: qualquer arco 3D (tangentes por slerp) dividido em k estações dá o mesmo ponto final que 2 estações.
- Corda ≤ comprimento de arco em cada curso; saídas finitas; azimute de fecho em [0, 360).
- Concordância `atan2` vs `arccos` clássico para β moderado; continuidade do RF no limiar da série de Taylor; β ≈ 0 vs β = 0; 359° → 1° = 2°.

## Para atingir M3
Obter a listagem oficial ISCWSA (ou outro caso publicado com coordenadas de referência), registar a fonte completa no JSON, fixar a tolerância a partir da precisão publicada e mudar `source_status` para `confirmed`.

## Limitações
Sem correção de declinação/convergência (A-002); resultados são deslocamentos locais; inversões de ~180° num curso recusadas (A-004).
