# Validação — Análise Nodal

Maturidade: `ipr_linear`, `ipr_vogel`, `vogel_qmax_from_test` e `ipr_composite` **M3**; `composite_j_from_test`, `TabulatedTPR` e `nodal_solve` M2; Hagedorn–Brown e Beggs & Brill **M0** (lançam `NotImplementedError`).

## Casos
| ID | Tipo | O que prova |
|---|---|---|
| VAL-ND-001 | analítico | IPR linear × TPR reta: interseção única e estável igual à solução algébrica. |
| VAL-ND-L01 | literatura | Problema 1-3: tabela IPR de Vogel (p̄r = 2500 psig) nas 4 linhas não triviais (as de pwf = p̄r e pwf = 0 foram retiradas por serem verdadeiras por construção), ±0,05 STB/d. |
| VAL-ND-L01b | literatura | Mesmo problema: qmax a partir do teste arredonda para 1067,1 (o "1076,1" do texto é uma gralha de transposição, assinalada e não usada). |
| VAL-ND-L02 | literatura | Problema 1-4: tabela IPR composta (pb = 2130, p̄r = 3000, J = 0,5) e qb = 435, ±0,5 STB/d. |
| VAL-ND-L04 | literatura | **Vogel (1968), SPE-1476, exemplo original**: 65 BOPD a 1 500 psi, p̄r = 2 000 psi → (qo)max = 162 BOPD. Tolerância ±2,1 BOPD porque o artigo lê qo/qmax = 0,40 de um gráfico (±0,005). Erro observado 0,5 BOPD (162,5 vs 162). |
| VAL-ND-L05 | literatura | Vogel (1968): com qmax = 162, q a 500 psi = 146 BOPD (±0,5). |
| VAL-ND-L06 | literatura | Vogel (1968): IP em linha reta a partir do mesmo teste prevê 195 BOPD a 500 psi (±0,5). |
| VAL-ND-L03 | literatura | Problema 1-5: J a partir de um reteste abaixo de pb = 0,5 STB/d/psi. |

**Força da evidência:** Vogel, a IPR linear e qmax assentam agora no artigo original (VAL-ND-L04 a L06). A IPR composta assenta apenas nas notas de aula publicadas (Engenharia de Produção II, Departamento de Engenharia de Petróleo, Universidade de Mosul, 2017), que citam Vogel (1968) e Beggs (1991). Isto é mais fraco do que um livro ou artigo revisto por pares; o reforço recomendado para a composta é um exemplo de Beggs (1991) consultado diretamente.

## Propriedades (tests/engineering/test_nodal.py)
- Para qualquer IPR (linear, Vogel, composta): q decrescente em pwf, q ∈ [0, q_max], inversa pwf(q) exata.
- IPR composta: continuidade de q e de dq/dpwf (= −J) em pb.
- Solver: TPR em forma de J com duas interseções classificadas instável/estável; sem interseção → resultado tipado com aviso; tangência assinalada; solução linear igual à algébrica para parâmetros aleatórios.

## Limitações
Vogel é empírico (solution-gas drive; erros típicos ~10 %). Sem correções de skin/eficiência de fluxo (Standing), sem IPR de gás. TPR só tabelada.
