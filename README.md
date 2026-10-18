# GeoReservoir AI — Núcleo Científico v0.3.0

Biblioteca Python de engenharia de subsuperfície em que cada resultado é um `CalculationRecord`: valores, unidades, método, referência bibliográfica, hash SHA-256 das entradas, versão, nível de maturidade, hipóteses e avisos tipados.

> Ferramenta de apoio à decisão. Não substitui profissionais qualificados, a validação dos dados de entrada nem a aprovação de workflows por quem tem responsabilidade técnica. Nenhum módulo está validado em campo.

## Estado

| Módulo | Funções | Maturidade |
|---|---|---|
| `common` | exceções, `units`, `validation`, `CalculationRecord` | M2 |
| `engineering.well_path` | `minimum_curvature` | **M3** |
| | `dogleg_angle`, `ratio_factor`, `normalize_azimuth` | M2 |
| `engineering.petrophysics` | `archie_water_saturation` | **M3** |
| `engineering.dca` | `nominal_to_effective_decline` | **M3** |
| | `arps_rate`, `arps_cumulative`, `arps_eur`, `arps_fit`, `effective_to_nominal_decline`, `convert_nominal_decline` | M2 |
| `engineering.nodal` | `ipr_linear`, `ipr_vogel`, `vogel_qmax_from_test`, `ipr_composite` | **M3** |
| | `composite_j_from_test`, `TabulatedTPR`, `nodal_solve` | M2 |
| | `hagedorn_brown_tpr`, `beggs_brill_tpr` | M0 (erro descritivo) |
| `engineering.bourdet` | `bourdet_derivative` (drawdown) | M2 |
| `engineering.material_balance` | `underground_withdrawal`, `expansion_terms`, `fit_no_cap_no_aquifer`, `fit_known_m`, `fit_gas_cap_unknown_m` | M2 |
| `engineering.uncertainty` | `mc_archie_sw`, `mc_arps_eur`, distribuições (`Fixed`, `Uniform`, `Triangular`, `Normal`, `LogNormal`) — P90/P50/P10 na convenção PRMS | M2 |
| `io.las` | `read_las` (LAS 1.2/2.0): proveniência SHA-256, cabeçalho verbatim, NULL, sentinelas, índice, unidades/mnemónicas, relatório de validação | M2 |
| `io.survey` | `read_survey` (CSV/TSV/espaços) → `Survey.trajectory()` | M2 |
| | LAS 3.0, DLIS, SEG-Y | M0 |
| | `gamma_ray_index`, `vsh_larionov_tertiary`, `vsh_larionov_older`, `vsh_steiber`, `vsh_clavier`, `density_porosity`, `sonic_porosity_wyllie`, `archie_true_resistivity` | M2 |

Níveis: M0 planeado · M1 protótipo · M2 verificado (propriedades + oráculos exatos: geometria analítica na trajetória; conformidade com as equações publicadas na petrofísica) · M3 validado com literatura · M4 validado em campo. **O que M3 significa neste projeto:** a função reproduz, dentro da tolerância de arredondamento da fonte, um exemplo ou tabela **publicada por terceiros** com as mesmas entradas. Isto prova transcrição correta da equação, unidades e convenções contra um cálculo independente — **não** prova que o modelo físico é adequado a um reservatório (isso é M4, validação em campo). Evidência por função:

| Função | Caso publicado | Força da fonte |
|---|---|---|
| `minimum_curvature` | Bourgoyne et al. (1991), via Amorin & Broni-Bediako (2010) | Livro SPE, citado por artigo de conferência |
| `archie_water_saturation` | Kansas Geological Survey, PfEFFER (2010) | Serviço geológico estatal (exemplo didático) |
| `nominal_to_effective_decline` | SPEE REP #6, Tabela 1 | Prática recomendada da SPEE |
| `ipr_linear`, `ipr_vogel`, `vogel_qmax_from_test` | Vogel (1968), JPT, SPE-1476 — exemplo resolvido do artigo original | Artigo original revisto por pares |
| `ipr_composite` | Notas de aula, Univ. de Mosul (2017), citando Beggs (1991) | **Mais fraca**: material didático, não revisto por pares |

Detalhe e erros observados em `docs/validation/REPORT.md`.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # inclui o extra de leitura de dados
pip install "georeservoir[io]"  # só núcleo + leitura de LAS (lasio, MIT; ADR-0004)
```

## Uso

```python
from georeservoir.engineering.well_path import minimum_curvature

rec = minimum_curvature(
    md=[0, 500, 800, 1100],
    inclination_deg=[0, 0, 15, 30],
    azimuth_deg=[0, 0, 135, 135],
    length_unit="m",
    azimuth_reference="true",
    start_east=0.0,
    start_north=0.0,
    start_tvd=0.0,
)
rec["tvd_m"], rec.units["tvd_m"], rec.maturity, rec.inputs_hash
print(rec.to_json(indent=2))
```

Exemplos: `python examples/end_to_end.py` e `python examples/las_to_porosity.py` (ficheiro LAS → porosidade, com linhagem do ficheiro ao resultado).

## Convenções
- Unidades na API explícitas (no nome do parâmetro ou em `Literal`); interno SI. Saídas de comprimento da trajetória em metros.
- Ângulos em graus na API; azimute a partir do Norte, horário, normalizado para [0, 360). E = +X, N = +Y, TVD positiva para baixo; deslocamentos locais.
- Arrays 1-D float64; escalares promovidos; NaN/inf recusados nas entradas e nas saídas (`NumericalError`); entradas nunca modificadas.
- Valores fora de [0, 1] nunca são limitados em silêncio: aviso com índices; clipping só com `clip=True`.
- Hipóteses: `docs/assumptions.md`. Decisões: `docs/adr/`.

## Comandos

```bash
pytest                                   # unitários, propriedades e validação
pytest --cov                             # cobertura (linhas + ramos)
ruff check . && ruff format --check .    # lint e formato
mypy                                     # tipos (strict, src/)
python scripts/bench.py                  # tempos de referência
python scripts/generate_validation_cases.py  # regenera casos a partir de fórmulas fechadas
python scripts/build_validation_report.py    # gera docs/validation/REPORT.md
```

## Limitações científicas
- Trajetória: sem correção de declinação/convergência; sem modelo de incerteza de posição (ISCWSA error model).
- Vsh: correlações empíricas. Archie: só formações limpas. Sem correções de gás, argila ou compactação.
- Vsh, porosidades, IGR, Bourdet e balanço material têm apenas validação analítica/de conformidade (não foram encontrados exemplos publicados com entradas e resultados numéricos verificáveis); os casos de literatura cobrem uma geometria de build e um exemplo didático de Archie, não dados de campo.
- DCA: Arps é empírico e pressupõe operação constante; b > 1 indica regime transiente; EUR com b ≥ 1 exige declínio terminal.
- Nodal: Vogel e IPR composta são empíricas (solution-gas drive); TPR só tabelada — correlações multifásicas por implementar (M0).
- Bourdet: apenas tempo de fluxo (drawdown); sem tempo de superposição, identificação de regimes, k ou skin.
- Balanço material: óleo apenas; We só como série fornecida; caso (c) despreza Efw.
- Leitura de dados: só LAS 1.2/2.0 e surveys em texto delimitado; unidades de survey declaradas pelo utilizador.
- Monte Carlo: entradas independentes (sem correlação); P90/P50/P10 na convenção de excedência PRMS.

## Licença
Todos os direitos reservados até à decisão do ADR-0002.
