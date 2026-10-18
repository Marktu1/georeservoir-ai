# Validação — Leitura de dados (Fase 2)

Maturidade: `read_las` (LAS 1.2 e 2.0) **M2**; `read_survey` **M2**; LAS 3.0, DLIS e SEG-Y **M0**.

## Portão da Fase 2: ficheiros públicos lidos sem perda de metadados
`tests/io/test_las.py::test_gate_no_metadata_or_data_loss` lê 8 ficheiros LAS públicos (suite de testes do `lasio`, MIT) e compara com um **parser independente escrito no próprio teste** (divisão de texto + NumPy, sem `lasio` nem `georeservoir`):
- SHA-256 e tamanho iguais aos bytes do ficheiro;
- todas as linhas de ~V, ~W, ~C e ~P presentes, pela mesma ordem;
- valores do cabeçalho **iguais ao texto do ficheiro** (ex.: `1670.000000`, não `1670.0`) — este teste encontrou a perda de precisão do `lasio` e levou a guardar o texto original (`value`) ao lado do valor interpretado (`value_parsed`);
- texto livre de ~O preservado;
- dados iguais à tokenização independente, com NaN exatamente onde o valor é o NULL declarado.

Ficheiros: `sample.las` (1.2), `sample_2.0.las`, `sample_2.0_wrapped.las`, `sample_2.0_minimal.las`, `sample_curve_api.las`, `missing_null.las`, `encodings_cp1252.las`, `encodings_utf16le.las`.

## Casos patológicos (reportados, não escondidos)
| Ficheiro | Achado |
|---|---|
| `index_null.las` | NULL = 999,25 coincide com uma profundidade real: índice mantido, aviso `INDEX_EQUALS_NULL`. |
| `comma_decimal_mark.las` | O `lasio` lê "123,420" como 123,42 sem avisar; aviso `DECIMAL_COMMA`. |
| `missing_null.las` | Sem NULL declarado: nada é anulado (−999,25 fica como número); aviso `NULL_MISSING`. |
| `mnemonic_duplicate.las` | Mnemónica repetida renomeada pelo parser; aviso `DUPLICATE_MNEMONIC`. |
| `autodepthindex_M_FT.las` | Unidades de índice em conflito; aviso do parser capturado. |
| `header_only.las` | Sem dados; aviso `NO_DATA`. |
| `sample_3.0.las`, `missing_vers.las` | Recusados (`NotImplementedError`): versão não suportada. |
| ficheiro com profundidade duplicada | `INDEX_DUPLICATES` (falha); com `on_error="raise"` lança erro. |

## Surveys
`tests/io/test_survey.py` lê o exemplo de Bourgoyne et al. (1991) a partir de um CSV e reproduz TVD = 1 653,99 ft e N = 954,93 ft (±0,005 ft) — verificação de ponta a ponta ficheiro → trajetória. Erros de formato indicam a linha do ficheiro.

## Limitações
Sem LAS 3.0, DLIS, SEG-Y, ficheiros de surveys com cabeçalhos proprietários nem conversão de referência de azimute. A correção de curvas (ambiente, profundidade) é da responsabilidade do utilizador.
