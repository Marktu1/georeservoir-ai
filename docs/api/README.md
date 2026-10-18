# GeoReservoir AI — API v1

Contrato completo: [`openapi-v1.json`](openapi-v1.json) (também em `/api/v1/openapi.json` e, se ativo, em `/api/v1/docs`). Decisões: [ADR-0005](../adr/0005-http-api.md).

## Arrancar

```bash
pip install -e ".[api]"
python -m georeservoir.api new-key marcos-laptop     # mostra o token UMA vez + entrada JSON
# guardar a entrada em keys.json, acrescentar projetos e escopos:
# {"keys": [{"key_id": "marcos-laptop", "sha256": "…", "projects": ["block-17"],
#            "scopes": ["calc", "upload"]}]}
GEORESERVOIR_API_KEYS_FILE=keys.json python -m georeservoir.api serve   # 127.0.0.1:8000
```

Variáveis opcionais: `GEORESERVOIR_HOST`, `_PORT`, `_MAX_BODY_BYTES`, `_MAX_UPLOAD_BYTES`, `_MAX_ARRAY_LEN`, `_CALC_TIMEOUT_S`, `_QUEUE_TIMEOUT_S`, `_MAX_CONCURRENT_CALCS`, `_MC_MAX_SAMPLES`, `_RATE_LIMIT_PER_MINUTE`, `_ENABLE_DOCS` (0/1; com 0, `/docs` e `/openapi.json` ficam desligados). Em produção: TLS num proxy reverso.

## Exemplo

```bash
curl -X POST https://api.exemplo/api/v1/projects/block-17/calc/nodal/vogel-qmax-from-test \
  -H "Authorization: Bearer $TOKEN" -H "content-type: application/json" \
  -d '{"p_res": 2000, "q_test": 65, "pwf_test": 1500, "pressure_unit": "psi"}'
```

Resposta (resumida):

```json
{"api_version": "v1", "project_id": "block-17",
 "record": {"values": {"q_max": 162.50000000000003}, "units": {"q_max": "rate unit"},
            "method": "nodal.vogel_qmax_from_test", "maturity": "M3",
            "method_reference": "Vogel, J.V. (1968) …", "inputs_hash": "…",
            "library_version": "0.4.0", "assumptions": ["A-014"], "warnings": []}}
```

## Endpoints
| Método e caminho | Escopo | Função do núcleo |
|---|---|---|
| `GET /api/v1/health` | público | — |
| `GET …/methods` | calc | lista métodos, maturidade e referência |
| `POST …/calc/well-path/minimum-curvature` | calc | `well_path.minimum_curvature` |
| `POST …/calc/petrophysics/{gamma-ray-index, vsh, density-porosity, sonic-porosity-wyllie, archie-sw, archie-rt}` | calc | `petrophysics.*` |
| `POST …/calc/dca/{rate, cumulative, eur, fit, nominal-to-effective, effective-to-nominal}` | calc | `dca.*` |
| `POST …/calc/nodal/{ipr, vogel-qmax-from-test, composite-j-from-test, solve}` | calc | `nodal.*` |
| `POST …/calc/bourdet/derivative` | calc | `bourdet.bourdet_derivative` |
| `POST …/calc/material-balance/{underground-withdrawal, expansion-terms, fit-no-cap-no-aquifer, fit-known-m, fit-gas-cap-unknown-m}` | calc | `material_balance.*` |
| `POST …/calc/uncertainty/{mc-archie-sw, mc-arps-eur}` | calc | `uncertainty.*` |
| `POST …/data/las` (multipart `file`) | upload | `io.las.read_las` |
| `POST …/data/survey` (multipart `file` + campos) | upload | `io.survey.read_survey` + trajetória |

`…` = `/api/v1/projects/{project_id}`.

## Códigos de estado
| Código | Quando |
|---|---|
| 200 | cálculo ou leitura feitos (avisos científicos vêm em `record.warnings` / `report`) |
| 401 | sem token ou token inválido (verificado antes de ler o corpo) |
| 403 | projeto ou escopo não autorizados (mesma resposta para projetos inexistentes) |
| 413 | corpo ou ficheiro acima do limite |
| 422 | pedido inválido ou erro do núcleo (`InputValidationError`, `PhysicalConsistencyError`, `NumericalError`, `IdentifiabilityError`) |
| 429 | rate limit (ver `Retry-After`) |
| 501 | funcionalidade M0 (ex.: LAS 3.0) |
| 503 | todos os lugares de cálculo ocupados durante `queue_timeout_s` (ver `Retry-After`) |
| 504 | cálculo excedeu o timeout |

## Garantias verificadas por testes
- `tests/api/test_contract.py`: os 31 casos cobrem as 28 rotas de cálculo; o `record` de cada resposta é **igual** ao `CalculationRecord` da chamada direta à biblioteca (incluindo `inputs_hash`); o OpenAPI coincide com o snapshot.
- `tests/api/test_security.py`: autenticação (cabeçalhos malformados, duplicados, espaços), verificação **antes** do corpo, autorização por projeto e escopo, rate limit também para 401/403 e com memória limitada, limites de corpo por rota (cabeçalho e streaming), uploads (uma só parte, tamanho, nome com `../`, pasta temporária removida), arrays, amostras MC, números estritos (booleanos, strings, NaN, ±∞, 1e400), ausência de eco de entradas, nenhum campo de caminho/código, timeout sem acumulação de threads, fila que não conta como tempo de cálculo, erros 404/405/500 com envelope e cabeçalhos, logs sem segredos nem dados, docs e OpenAPI desligáveis, configuração e CLI.
- `tests/api/test_data_endpoints.py`: upload de survey reproduz a trajetória publicada (Bourgoyne) pela API; NULL → `null` em JSON; LAS 3.0 → 501.
