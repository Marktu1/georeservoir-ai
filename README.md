# GeoReservoir AI — Núcleo Científico v0.1.1

Biblioteca Python de engenharia de subsuperfície em que cada resultado é um `CalculationRecord`: valores, unidades, método, referência bibliográfica, hash SHA-256 das entradas, versão, nível de maturidade, hipóteses e avisos tipados.

> Ferramenta de apoio à decisão. Não substitui profissionais qualificados, a validação dos dados de entrada nem a aprovação de workflows por quem tem responsabilidade técnica. Nenhum módulo está validado em campo.

## Estado

| Módulo | Funções | Maturidade |
|---|---|---|
| `common` | exceções, `units`, `validation`, `CalculationRecord` | M2 |
| `engineering.well_path` | `minimum_curvature` | **M3** |
| | `dogleg_angle`, `ratio_factor`, `normalize_azimuth` | M2 |
| `engineering.petrophysics` | `archie_water_saturation` | **M3** |
| | `gamma_ray_index`, `vsh_larionov_tertiary`, `vsh_larionov_older`, `vsh_steiber`, `vsh_clavier`, `density_porosity`, `sonic_porosity_wyllie`, `archie_true_resistivity` | M2 |

Níveis: M0 planeado · M1 protótipo · M2 verificado (propriedades + oráculos exatos: geometria analítica na trajetória; conformidade com as equações publicadas na petrofísica) · M3 validado com literatura · M4 validado em campo. M3 significa que a função reproduz um caso publicado dentro da tolerância de arredondamento da fonte: `minimum_curvature` (Bourgoyne et al. 1991, via Amorin & Broni-Bediako 2010) e `archie_water_saturation` (Kansas Geological Survey, PfEFFER). M3 não é validação em campo (M4). Detalhe em `docs/validation/REPORT.md`. Módulos futuros: `docs/roadmap.md`.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
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

Exemplo completo: `python examples/end_to_end.py`.

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
- Vsh, porosidades e IGR têm apenas validação analítica/de conformidade; os casos de literatura cobrem uma geometria de build e um exemplo didático de Archie, não dados de campo.

## Licença
Todos os direitos reservados até à decisão do ADR-0002.
