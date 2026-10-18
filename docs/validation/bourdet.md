# Validação — Derivada de Bourdet

Maturidade: `bourdet_derivative` **M2** (drawdown). Superposição para buildup: **M0**.

## Casos
| ID | Tipo | O que prova |
|---|---|---|
| VAL-BD-001 | analítico | Δp = m·ln t + c em tempos irregulares: derivada = m em todos os pontos, centrais e unilaterais. |
| VAL-BD-002 | analítico | Δp = t com espaçamento log uniforme h = L: interior = Δp·sinh(L)/L, extremos (e^L − 1)/L e (1 − e^(−L))/L — resultado discreto exato. |

## Propriedades (tests/engineering/test_bourdet.py)
- Invariância a uma constante somada a Δp; invariância à unidade de tempo; operador linear.
- σ propagado = desvio-padrão de 4000 simulações Monte Carlo (±8 %).
- Solução de fonte linear (E1): derivada = ½·exp(−1/(4t_D)) dentro de 1 % com L = 0,1.
- Pontos unilaterais sinalizados; registos mais curtos do que L recusados (`NumericalError`).

## Para M3
Reproduzir a derivada de um teste publicado (por exemplo, os dados do artigo de Bourdet et al. 1989 ou de um livro de análise de testes de poço) com tolerância derivada da precisão publicada.

## Limitações
Sem identificação de regimes nem cálculo de k e skin (fora de escopo). Sem tempo de superposição.
