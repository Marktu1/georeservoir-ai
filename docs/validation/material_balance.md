# Validação — Balanço material (Havlena–Odeh)

Maturidade: todas as funções **M2**. Aquíferos Fetkovich e Carter–Tracy: **M0** (não implementados; We só como série fornecida).

## Casos
| ID | Tipo | O que prova |
|---|---|---|
| VAL-MB-001 | conformidade | Eo, Eg, Efw contra as definições escritas à mão para uma tabela PVT sintética de 5 passos. |
| VAL-MB-002 | sintético exato | Caso (b): N = 5e7 STB recuperado exatamente com m = 0,4 conhecido. |
| VAL-MB-003 | sintético exato | Caso (c): N e m recuperados exatamente de F/Eo vs Eg/Eo. |
| VAL-MB-004 | sintético exato | Caso (a) com série We fornecida: N recuperado exatamente após subtrair We. |

## Propriedades (tests/engineering/test_material_balance.py)
- Termos de expansão nulos nas condições iniciais.
- Recuperação exata de N para N ∈ [1e5, 1e9] e m ∈ [0, 3]; com 0,1 % de ruído, erro relativo < 1 %.
- `IdentifiabilityError` com poucos pontos, expansões nulas ou Eg/Eo constante (N e m inseparáveis).
- `PhysicalConsistencyError` para p > pi ou N ajustado ≤ 0; aviso para m < 0.

## Para M3
Reproduzir um exemplo publicado de Havlena–Odeh (por exemplo, do artigo original SPE-559-PA ou de um livro de engenharia de reservatórios) com os dados PVT e produção publicados.

## Limitações
Óleo apenas (sem balanço de gás seco/condensado). PVT e produção médios por passo são da responsabilidade do utilizador. Sem diagnóstico automático do mecanismo de produção.
