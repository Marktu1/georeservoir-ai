# Validação — Petrofísica

Maturidade atual: `archie_water_saturation` **M3**; restantes funções M2. Resultados numéricos em `REPORT.md` (gerado).

## Casos (tests/validation/cases/)
| ID | Tipo | O que prova |
|---|---|---|
| VAL-PP-001 | spec_conformance | IGR nos extremos e ponto médio. |
| VAL-PP-002 a 005 | spec_conformance | Steiber, Larionov (antigas e terciário) e Clavier em valores verificáveis à mão. |
| VAL-PP-006 | spec_conformance | Porosidade de densidade (quartzo/água doce). |
| VAL-PP-007 | spec_conformance | Porosidade sónica de Wyllie. |
| VAL-PP-008 | spec_conformance | Archie com Sw = 0,25 exato. |
| VAL-PP-L01 | literatura | Kansas Geological Survey, PfEFFER Concepts (atualizado em julho de 2010): 10 zonas, a = 1, m = 1,8, n = 2, Rw = 0,10 ohm·m. Todas reproduzidas dentro de ±0,005 (arredondamento publicado), incluindo a zona I com Sw = 1,07 (comparado com `sw_raw`, sem clipping). |
| VAL-PP-L02 | literatura | Exercício de Asquith & Krygowski (2004) — **fonte por verificar**. |

`spec_conformance` prova que a equação publicada foi transcrita corretamente; **não** prova a adequação física das correlações a uma formação.

## Testes de propriedades (tests/engineering/test_petrophysics.py)
- Vsh: f(0) = 0; f(1) documentado (Larionov terciário ≈ 0,9957; antigas 0,99; Steiber e Clavier 1); monotonia; Vsh ≤ IGR em [0, 1].
- Archie: Sw = 1 quando Rt = a·Rw/φ^m; monotonia decrescente em Rt; ida-e-volta Rt(Sw) → Sw.
- Porosidade de densidade decrescente em ρb; avisos e contagem quando fora de [0, 1]; clipping só com `clip=True`.

Nota: os testes de ida-e-volta (Archie direto/inverso) e Sw = 1 em R0 são **propriedades de consistência**, não validação: um erro igual nas duas direções passaria.

## Para levar as outras funções a M3
Vsh (Larionov, Steiber, Clavier), porosidade de densidade e Wyllie precisam cada uma de um caso publicado com entradas e resultado (por exemplo, exemplos de cartas de interpretação ou livros de análise de perfis). O exemplo KGS é didático (zona hipotética), não dados de campo.

## Limitações
Correlações de Vsh são empíricas. Archie só é válido em formações limpas (sobrestima Sw em areias argilosas). Sem correções de gás, argila ou compactação (M0).
