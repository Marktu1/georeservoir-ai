# Hipóteses (assumptions)

Cada hipótese é referenciada nas docstrings e no campo `assumptions` do `CalculationRecord`.

| ID | O que foi assumido | Porquê | Impacto na validade | Como reverter |
|---|---|---|---|---|
| A-001 | Comprimentos convertidos para metros internamente; todas as saídas de comprimento da trajetória em metros (`*_m`), mesmo com entrada em pés. | Sistema canónico SI (spec §4.3); evita mistura de sistemas numa fórmula. | Nenhum na exatidão; o utilizador converte com `units.length_from_si`. | Acrescentar argumento `output_length_unit` tipado. |
| A-002 | O azimute é usado tal como fornecido; `azimuth_reference` (true/magnetic/grid) é apenas registado. Sem correção de declinação nem convergência. Resultados são deslocamentos locais. | Spec §5.1 e §9 (transformação geodésica é módulo separado). | Erro de orientação igual à diferença entre referências se o utilizador misturar referências. | Módulo futuro de correção de declinação/convergência. |
| A-003 | Ratio factor usa série de Taylor `1 + β²/12 + β⁴/120` para β < 1e-4 rad. | Spec §5.1. Erro de truncatura O(β⁶) ≈ 1e-25 no limiar; continuidade testada na fronteira. | Desprezável. | Alterar `RF_TAYLOR_THRESHOLD_RAD`. |
| A-004 | Cursos com dogleg β ≥ π − 1e-6 rad são recusados (`PhysicalConsistencyError`). | Em β = π o arco não é único e RF diverge (tan(π/2)). | Surveys com inversão de ~180° num só curso não são aceites (fisicamente implausível). | Exigir subdivisão do curso pelo utilizador. |
| A-005 | Azimute de fecho = 0,0 onde o deslocamento horizontal < 1e-12 m. Na estação 0 (origem) por convenção, sem aviso; nas restantes com aviso `CLOSURE_AZIMUTH_UNDEFINED`. | O azimute de fecho é indefinido para deslocamento nulo; nunca devolver NaN em silêncio. | Valor convencional, sinalizado. | — |
| A-006 | As funções de Vsh exigem IGR ∈ [0, 1] e lançam `InputValidationError` fora desse domínio. | As correlações não estão definidas fora de [0, 1]; obriga a tratar o clipping do IGR de forma explícita a montante. | Nenhum. | — |
| A-007 | Vsh pode diferir dos valores exatos nos extremos por arredondamento float64 (Clavier: f(1) = 0,9999999999999998). Não é aplicado clipping. | Evitar clipping silencioso; o desvio (~1e-16) está abaixo de qualquer significado físico. | Desprezável. | — |
| A-008 | Escalares são promovidos a arrays 1-D de tamanho 1; todas as saídas são arrays 1-D. NaN e ±inf são recusados em todas as entradas. | Contrato uniforme e política "nunca NaN em silêncio". | Curvas com valores em falta têm de ser filtradas pelo utilizador antes do cálculo. | Política de máscara explícita na Fase 2 (dados). |
| A-009 | Razões adimensionais (IGR, φ, Sw) calculadas diretamente nas unidades declaradas (API, g/cm³, µs/ft, ohm·m), sem conversão para SI. | O resultado é invariante à unidade comum do numerador e denominador. | Nenhum. | — |

## Discrepâncias com a especificação

Nenhuma equação da secção 5 foi alterada.
