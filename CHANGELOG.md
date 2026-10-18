# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versionamento: SemVer.

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
