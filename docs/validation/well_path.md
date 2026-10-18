# Validação — Minimum Curvature

Maturidade atual: `minimum_curvature` **M3**; funções auxiliares M2. Resultados numéricos em `REPORT.md` (gerado).

## Casos (tests/validation/cases/)
| ID | Tipo | O que prova |
|---|---|---|
| VAL-WP-001 | analítico | Poço vertical: TVD = MD, deslocamento e dogleg nulos, para azimutes arbitrários. |
| VAL-WP-002 | analítico | Tangente inclinada (30°, 60°) contra trigonometria exata. |
| VAL-WP-003 | analítico | Arco circular R = 500 m (0°→90°) com 2 estações: ponto final e DLS exatos. |
| VAL-WP-004 | analítico | Mesmo arco com 10 estações: todas as estações intermédias sobre o círculo. |
| VAL-WP-L01 | literatura | Exemplo de build de Bourgoyne et al. (1991), *Applied Drilling Engineering*, tabelado em Amorin & Broni-Bediako (2010), UMaT, pp. 524–541: TVD = 1 653,99 ft e N = 954,93 ft aos 2 000 ft. Tolerância ±0,005 ft (arredondamento publicado). |
| VAL-WP-L02 | literatura | ISCWSA test well #1 — **fonte por verificar**; caso 3D mais exigente, ainda por obter. |

Os oráculos são fórmulas fechadas geradas por `scripts/generate_validation_cases.py`, que não importa `georeservoir` (não circulares). Tolerância 1e-11 m (+1e-13 relativo), ~10× o erro de arredondamento esperado; erro observado ≤ ~1e-13 m (ver REPORT.md).

## Testes de propriedades (tests/engineering/test_well_path.py)
- Rotação: somar θ a todos os azimutes roda (E, N) por θ; TVD e dogleg invariantes.
- Subdivisão: qualquer arco 3D (tangentes por slerp) dividido em k estações dá o mesmo ponto final que 2 estações.
- Corda ≤ comprimento de arco em cada curso; saídas finitas; azimute de fecho em [0, 360).
- Concordância `atan2` vs `arccos` clássico para β moderado; continuidade do RF no limiar da série de Taylor; β ≈ 0 vs β = 0; 359° → 1° = 2°.

## Nota sobre a força da evidência M3
O caso publicado é um build plano com azimute constante; o próprio artigo mostra que a mínima curvatura coincide com a geometria exata do arco. Prova a implementação num caso de referência da indústria, mas não exercita viragens 3D, que são cobertas pelos testes de propriedades. O caso ISCWSA (VAL-WP-L02) continua a ser o próximo reforço. A fonte primária (Bourgoyne) não foi consultada diretamente; os valores foram lidos no artigo de Amorin & Broni-Bediako.

## Limitações
Sem correção de declinação/convergência (A-002); resultados são deslocamentos locais; inversões de ~180° num curso recusadas (A-004).
