# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versionamento: SemVer.

## [0.1.0] — 2026-10-18

### Added
- Camada comum: hierarquia de exceções, conversões de unidades exatas (comprimento, pressão), validação de entradas, `CalculationRecord` imutável com hash SHA-256 determinístico.
- `engineering.well_path`: Minimum Curvature com dogleg vetorial `atan2`, ratio factor com série de Taylor, DLS em °/30 m e °/100 ft, deslocamento horizontal e azimute de fecho (M2).
- `engineering.petrophysics`: IGR, Vsh (Larionov terciário, Larionov rochas antigas, Steiber, Clavier), porosidade de densidade e sónica (Wyllie), Archie direto e inverso (M2).
- Testes unitários, de propriedades (Hypothesis, perfil determinístico) e 12 casos de validação analíticos/conformidade; 2 casos de literatura pendentes.
- Saídas não finitas (overflow, divisão por ~0) passam a lançar `NumericalError` em vez de devolver inf; `clip` exige bool; guardas em `ratio_factor`, `dogleg_angle` e `normalize_azimuth` (revisão adversarial).
- Gerador de casos de validação independente da implementação; gerador de relatório de validação, benchmark, exemplo de ponta a ponta, ADRs 0001–0003, CI (GitHub Actions, não executado).
