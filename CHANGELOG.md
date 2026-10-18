# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versionamento: SemVer.

## [0.4.0] — 2026-10-18 — Fase 3 (API)

### Added
- `georeservoir.api`: FastAPI v1 com 28 rotas de cálculo (todas as funções públicas do núcleo), upload de LAS e de surveys, `health` e `methods`; resposta = `CalculationRecord` do núcleo sem alterações.
- Chaves portadoras guardadas só como SHA-256, autorização por projeto e escopo, limites de corpo (também em streaming), upload, arrays e amostras MC, timeout por cálculo, concorrência limitada, rate limit por chave, erros tipados sem eco de entradas, logs JSON sem dados sensíveis, cabeçalhos de segurança.
- CLI `python -m georeservoir.api {serve,new-key,openapi}`; snapshot OpenAPI em `docs/api/openapi-v1.json`; ADR-0005; hipóteses A-025 a A-027; extra `[api]`.
- Testes de contrato (31 casos, cada resposta igual à chamada direta) e de segurança.

### Fixed
- Núcleo: parâmetros numéricos das distribuições de Monte Carlo e dos modelos de IPR normalizados para float — `Fixed(1)` e `Fixed(1.0)` davam `inputs_hash` diferentes (encontrado pelos testes de contrato).
- Mensagens de erro mostram números simples (`1.5`) em vez de `np.float64(1.5)`.

## [0.3.0] — 2026-10-18 — Fase 2 (dados)

### Added
- `georeservoir.io.las.read_las`: LAS 1.2/2.0 com proveniência (SHA-256), cabeçalho verbatim + valor interpretado, NULL declarado, sentinelas suspeitas, vírgula decimal, verificações do índice (NULL, duplicados, monotonia, amostragem irregular, STRT/STOP/STEP), unidades e mnemónicas normalizadas com relatório, avisos do parser capturados. LAS 3.0 recusado (M0).
- `georeservoir.io.survey.read_survey`: surveys em texto delimitado com erros por linha e `Survey.trajectory()`.
- Extra opcional `[io]` (`lasio`, MIT) — ADR-0004; hipóteses A-021 a A-023; 16 ficheiros LAS públicos de teste; exemplo `las_to_porosity.py`.
- Teste do portão: 8 ficheiros públicos comparados com um parser independente.

### Fixed (revisão adversarial da Fase 2)
- Alterações silenciosas de valores: as substituições por omissão do `lasio` (divisão de valores colados, vírgula decimal) estão desligadas; tokens ambíguos fazem o ficheiro ser recusado com linha e curva.
- NULL substituído pela própria biblioteca, só nas curvas; NaN escritos no ficheiro e curvas sem dados reportados à parte.
- Sem perda de metadados: caixa das mnemónicas, texto da descrição (LAS 1.2) e ~O verbatim preservados.
- Codificação: cp1252 antes de latin-1; UTF-16 só com BOM ou padrão de NUL; codificações assumidas geram aviso.
- Índice que não é profundidade não recebe alias `DEPT`; `RT` e `SGR` deixam de ser mapeados.
- NULL não numérico reportado como tal; duplicados e inversões do índice reportados em conjunto; limiar de amostragem irregular 1 %.
- Surveys: sentinelas recusadas, linhas físicas corretas após campos com aspas, avisos para MD negativo, campos a mais e codificação assumida.
- Teste do portão reescrito com referência realmente independente e alargado a unidades, descrições, códigos API e ~O exato; `lasio` limitado a `<0.33`.

## [0.2.1] — 2026-10-18

### Added
- Casos VAL-ND-L04 a L06 a partir do exemplo resolvido do artigo original de Vogel (1968), SPE-1476.

### Changed
- `ipr_linear` e `vogel_qmax_from_test` passam a M3; `ipr_vogel` passa a assentar no artigo original (além das notas de aula).
- Procura de exemplos publicados para Vsh, porosidade de densidade e sónica e Bourdet: nenhum com entradas e resultados numéricos verificáveis encontrado; estas funções mantêm M2 (registado no README).

## [0.2.0] — 2026-10-18 — Fase 1 (núcleo completo)

### Added
- `engineering.dca`: Arps (taxa, cumulativo, hiperbólico modificado, EUR, conversões nominal/efetivo, ajuste por mínimos quadrados com erros-padrão). `arps_rate` e `nominal_to_effective_decline` em M3 (SPEE REP #6, Tabela 1).
- `engineering.nodal`: IPR linear, Vogel e composta; TPR tabelada (PCHIP); solver de todas as interseções com estabilidade. `ipr_vogel` e `ipr_composite` em M3 (tabelas publicadas). Hagedorn–Brown e Beggs & Brill em M0.
- `engineering.bourdet`: derivada de Bourdet (drawdown) com janela em ln t, extremidades unilaterais e propagação de σp (M2).
- `engineering.material_balance`: Havlena–Odeh (F, Eo, Eg, Efw; casos a, b, c; We fornecido; IdentifiabilityError) (M2).
- `engineering.uncertainty`: Monte Carlo com seed obrigatória para Sw de Archie e EUR de Arps; P90/P50/P10 na convenção PRMS (M2).
- Casos de validação por linha (`per_row`) no runner; hipóteses A-010 a A-020.

### Fixed (revisão adversarial da Fase 1)
- `arps_rate` desce de M3 para M2: a tabela SPEE já é a evidência da conversão e não pode contar duas vezes; o antigo VAL-DCA-L02 passa a VAL-DCA-005 (conformidade).
- Caso Vogel sem as duas linhas triviais; ressalva sobre a fonte (notas de aula) levada às docstrings e ao README.
- Havlena–Odeh caso (c): a verificação de condicionamento usava dados centrados e nunca disparava; passa a usar colunas normalizadas.
- Casos (a)/(b): N ≤ 0 lança `PhysicalConsistencyError`; termos de expansão negativos geram aviso.
- Solver nodal: tangência detetada mesmo com outras raízes; aviso para interseção a q = 0; mensagem de `NO_INTERSECTION` distingue tabela TPR truncada.
- Avisos `TERMINAL_DECLINE_EXCEEDS_INITIAL` (DCA) e `B_GREATER_THAN_ONE` no Monte Carlo (este último não chegava ao resultado — encontrado pelos novos testes).
- `IPR.pwf(q)` recusa taxas fora de [0, q_max]; booleanos recusados como números.
- Tolerâncias dos testes de Bourdet apertadas para os erros observados.

### Changed
- README define o que M3 significa e lista a força de cada fonte.
- A equação de Archie passou para uma função interna partilhada (`_archie_sw`), usada pelo cálculo determinístico e pelo Monte Carlo.

## [0.1.1] — 2026-10-18

### Added
- Caso de literatura VAL-WP-L01: build de Bourgoyne et al. (1991), via Amorin & Broni-Bediako (2010).
- Caso de literatura VAL-PP-L01: exemplo de Archie de 10 zonas do Kansas Geological Survey (PfEFFER).
- Suporte a `expected_index` nos casos de validação; teste que impede declarar M3 sem caso publicado.

### Changed
- `minimum_curvature` e `archie_water_saturation` passam de M2 para **M3**; restantes funções mantêm M2.
- O relatório de validação mostra a maturidade por função, não por módulo.

## [0.1.0] — 2026-10-18

### Added
- Camada comum: hierarquia de exceções, conversões de unidades exatas (comprimento, pressão), validação de entradas, `CalculationRecord` imutável com hash SHA-256 determinístico.
- `engineering.well_path`: Minimum Curvature com dogleg vetorial `atan2`, ratio factor com série de Taylor, DLS em °/30 m e °/100 ft, deslocamento horizontal e azimute de fecho (M2).
- `engineering.petrophysics`: IGR, Vsh (Larionov terciário, Larionov rochas antigas, Steiber, Clavier), porosidade de densidade e sónica (Wyllie), Archie direto e inverso (M2).
- Testes unitários, de propriedades (Hypothesis, perfil determinístico) e 12 casos de validação analíticos/conformidade; 2 casos de literatura pendentes.
- Saídas não finitas (overflow, divisão por ~0) passam a lançar `NumericalError` em vez de devolver inf; `clip` exige bool; guardas em `ratio_factor`, `dogleg_angle` e `normalize_azimuth` (revisão adversarial).
- Gerador de casos de validação independente da implementação; gerador de relatório de validação, benchmark, exemplo de ponta a ponta, ADRs 0001–0003, CI (GitHub Actions, não executado).
