# Validação — Decline Curve Analysis (Arps)

Maturidade: `nominal_to_effective_decline` **M3**; `arps_rate`, `arps_cumulative`, `arps_eur`, `effective_to_nominal_decline`, `convert_nominal_decline` e `arps_fit` M2.

## Casos
| ID | Tipo | O que prova |
|---|---|---|
| VAL-DCA-001…004 | analítico | Cumulativo fechado (b = 0; 0,5; 1; 1,6) contra integração numérica adaptativa da forma clássica q = qi(1+bDit)^(−1/b). |
| VAL-DCA-L01-b{00,05,10,15,20} | literatura | SPEE REP #6, Tabela 1: declínio efetivo (tangente para b = 0, secante para b > 0) para nominais de 1 % a 1000 %/ano — 140 valores dentro de ±5e-9 (6 casas decimais em %). |
| VAL-DCA-005-b… | conformidade | Mesma tabela: por definição SPEE, De secante = 1 − q(1 ano)/qi, logo `arps_rate` com qi = 1 e t = 1 ano reproduz 1 − De. **Não conta** como evidência de literatura separada para `arps_rate` (mesma tabela, um único instante). |

Nota de transcrição: a tabela foi transcrita do PDF da SPEE por extração automática de texto; recomenda-se uma verificação humana pontual. A tabela é a avaliação publicada da fórmula de conversão — prova transcrição e convenção (tangente vs secante), não validade física de Arps.

Linhas de 2000 % a 10000 % da tabela não foram usadas: a própria SPEE nota que a precisão de 8 dígitos limita valores acima de ~2000 %.

## Propriedades (tests/engineering/test_dca.py)
- Np = ∫q dt (quadratura) para b ∈ [0, 2] e Di ∈ [0,01; 2], com e sem declínio terminal.
- Continuidade em b → 0 e b → 1; q decrescente, Np crescente, Np ≤ qi·t.
- Hiperbólico modificado: continuidade de q na troca, declínio instantâneo = Dmin depois da troca, igual a Arps antes.
- EUR: q(t_end) = taxa-limite e EUR = Np(t_end); corte mais cedo entre taxa e horizonte.
- Ida-e-volta nominal ↔ efetivo (tolerância ajustada ao condicionamento quando De → 1).
- Ajuste: recupera qi, Di, b de curvas exatas (b = 0; 0,4; 0,9; 1,4) e de curvas com ruído log-normal (seed fixa) dentro de 4 erros-padrão; recusa shut-ins sem máscara; IdentifiabilityError com < 4 pontos.

## Limitações
Arps é empírico e pressupõe condições de operação constantes; b > 1 indica regime transiente. Sem segmentação multi-período nem ajuste com declínio terminal.
