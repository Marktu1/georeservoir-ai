# Validação — Petrofísica

Maturidade atual: **M2**. Resultados numéricos em `REPORT.md` (gerado).

## Casos (tests/validation/cases/)
| ID | Tipo | O que prova |
|---|---|---|
| VAL-PP-001 | spec_conformance | IGR nos extremos e ponto médio. |
| VAL-PP-002 a 005 | spec_conformance | Steiber, Larionov (antigas e terciário) e Clavier em valores verificáveis à mão. |
| VAL-PP-006 | spec_conformance | Porosidade de densidade (quartzo/água doce). |
| VAL-PP-007 | spec_conformance | Porosidade sónica de Wyllie. |
| VAL-PP-008 | spec_conformance | Archie com Sw = 0,25 exato. |
| VAL-PP-L01 | literatura | Exercício publicado de Archie — **fonte por verificar**; não conta para M3. |

`spec_conformance` prova que a equação publicada foi transcrita corretamente; **não** prova a adequação física das correlações a uma formação.

## Testes de propriedades (tests/engineering/test_petrophysics.py)
- Vsh: f(0) = 0; f(1) documentado (Larionov terciário ≈ 0,9957; antigas 0,99; Steiber e Clavier 1); monotonia; Vsh ≤ IGR em [0, 1].
- Archie: Sw = 1 quando Rt = a·Rw/φ^m; monotonia decrescente em Rt; ida-e-volta Rt(Sw) → Sw.
- Porosidade de densidade decrescente em ρb; avisos e contagem quando fora de [0, 1]; clipping só com `clip=True`.

Nota: os testes de ida-e-volta (Archie direto/inverso) e Sw = 1 em R0 são **propriedades de consistência**, não validação: um erro igual nas duas direções passaria.

## Para atingir M3
Reproduzir um caso publicado (por exemplo, um exercício de livro de análise de perfis com entradas e Sw publicados), com referência completa (edição, página) verificada por pessoa.

## Limitações
Correlações de Vsh são empíricas. Archie só é válido em formações limpas (sobrestima Sw em areias argilosas). Sem correções de gás, argila ou compactação (M0).
