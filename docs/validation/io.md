# Validação — Leitura de dados (Fase 2)

Maturidade: `read_las` (LAS 1.2 e 2.0) **M2**; `read_survey` **M2**; LAS 3.0, DLIS e SEG-Y **M0**.

## Portão da Fase 2: ficheiros públicos lidos sem perda de metadados
`tests/io/test_las.py::test_gate_no_metadata_or_data_loss` lê 8 ficheiros LAS públicos (suite do `lasio`, MIT) e compara com uma **referência independente escrita no teste**: codificação tirada de uma tabela fixa por ficheiro (não detetada), linhas do cabeçalho divididas por uma expressão regular da gramática LAS 2.0 (`MNEM.UNIT  DATA : DESCRIPTION`), ~A tokenizado com `str.split`. A referência não usa `lasio` nem `georeservoir`.

**O que o portão verifica:**
- SHA-256 e tamanho iguais aos bytes do ficheiro;
- ~V, ~W, ~P: mnemónica (com a caixa original), unidade, texto do valor e texto da descrição, linha a linha e pela mesma ordem;
- ~C: mnemónica, unidade, código API e descrição por curva;
- ~O exatamente igual ao ficheiro (indentação e espaços finais incluídos);
- ~A: número de tokens múltiplo do número de curvas, números idênticos, NaN exatamente onde o valor é igual ao NULL declarado.

**O que o portão não verifica:** comentários `#` do cabeçalho (descartados, como manda a norma), espaçamento interno das linhas do cabeçalho, ficheiros LAS 3.0, e o formato com que os números estavam escritos em ~A (só o valor).

**O que este teste encontrou e levou a corrigir** (o `lasio` faz isto por omissão):
- valores do cabeçalho re-formatados (`1670.000000` → `1670.0`) — guardamos o texto original (`value`) e a interpretação (`value_parsed`);
- em LAS 1.2, valor e descrição trocados no ~W — guardamos o texto original da descrição;
- indentação do ~O removida — guardamos o ~O verbatim;
- mnemónicas forçadas a maiúsculas — mantemos a caixa original.

A revisão adversarial encontrou ainda alterações silenciosas de valores (divisão de valores colados, `123.452550.0` → dois NaN; vírgula decimal convertida) que o portão original não exercitava: as substituições do `lasio` foram desligadas e esses ficheiros são agora recusados (testes em `tests/data/las/problem/`).

Ficheiros do portão: `sample.las` (1.2), `sample_2.0.las`, `sample_2.0_wrapped.las`, `sample_2.0_minimal.las`, `sample_curve_api.las`, `missing_null.las`, `encodings_cp1252.las`, `encodings_utf16le.las`.

## Casos patológicos (reportados, não escondidos)
| Ficheiro | Achado |
|---|---|
| `index_null.las` | NULL = 999,25 coincide com uma profundidade real: índice mantido, aviso `INDEX_EQUALS_NULL`. |
| `comma_decimal_mark.las` | O `lasio` lia "123,420" como 123,42 sem avisar; agora o ficheiro é **recusado** (vírgula ambígua). |
| `problem/runon_*.las` | Valores colados (`123.45-999.25`, `123.452550.0`) **recusados**, em vez de divididos ou transformados em NaN. |
| `problem/nan_tok.las`, `fewer_cols.las` | NaN escritos no ficheiro e curvas sem dados reportados à parte (`NAN_IN_DATA`, `CURVE_WITHOUT_DATA`), nunca como NULL. |
| `problem/mixed_enc.las`, `cp1252dash.las` | Codificação assumida reportada como aviso. |
| `missing_null.las` | Sem NULL declarado: nada é anulado (−999,25 fica como número); aviso `NULL_MISSING`. |
| `mnemonic_duplicate.las` | Mnemónica repetida renomeada pelo parser; aviso `DUPLICATE_MNEMONIC`. |
| `autodepthindex_M_FT.las` | Unidades de índice em conflito; aviso do parser capturado. |
| `header_only.las` | Sem dados; aviso `NO_DATA`. |
| `sample_3.0.las`, `missing_vers.las` | Recusados (`NotImplementedError`): versão não suportada. |
| ficheiro com profundidade duplicada | `INDEX_DUPLICATES` (falha); com `on_error="raise"` lança erro. |

## Surveys
`tests/io/test_survey.py` lê o exemplo de Bourgoyne et al. (1991) a partir de um CSV e reproduz TVD = 1 653,99 ft e N = 954,93 ft (±0,005 ft) — verificação de ponta a ponta ficheiro → trajetória. Erros de formato indicam a linha física do ficheiro (também depois de campos entre aspas em várias linhas); sentinelas (−999, −9999…) são recusadas; MD negativo, campos a mais e codificação assumida geram aviso.

## Limitações
Sem LAS 3.0, DLIS, SEG-Y, ficheiros de surveys com cabeçalhos proprietários nem conversão de referência de azimute. A correção de curvas (ambiente, profundidade) é da responsabilidade do utilizador.
