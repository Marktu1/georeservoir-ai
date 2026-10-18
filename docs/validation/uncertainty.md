# Validação — Incerteza (Monte Carlo)

Maturidade: `mc_archie_sw`, `mc_arps_eur` e as distribuições **M2**.

Convenção: P90/P50/P10 de excedência (SPE-PRMS) — `p90_low` ≤ `p50` ≤ `p10_high`.

## Testes (tests/engineering/test_uncertainty.py)
- Entradas fixas reproduzem exatamente o cálculo determinístico (mesma equação, fonte única).
- Mesma seed → JSON e hash idênticos; seed diferente → resultados e hash diferentes.
- Oráculo de quantis exato por monotonia: Sw é decrescente em Rt, logo os quantis de Sw são Sw(quantis de Rt) espelhados; com Rt log-normal e 400 000 amostras, P90/P50/P10 dentro de 0,3 % (erro de amostragem esperado ~0,04 %).
- EUR é proporcional a qi com Di e b fixos: com qi uniforme em [500, 1500], P90/P50/P10 = 600/1000/1400 × EUR(qi = 1) dentro de 0,5 %.
- Hiperbólico modificado com taxa-limite; avisos de Sw > 1; validação de distribuições e truncagem; recusa de amostras fora do domínio físico.

## Limitações
Sem correlação entre entradas (A-020). Sem diagnóstico de convergência além do erro-padrão da média. Não substitui uma análise probabilística de reservas segundo o PRMS.
