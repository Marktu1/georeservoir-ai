# ADR-0003 — Sistema de unidades

- Estado: aceite · Data: 2026-10-18

## Decisão
- Sistema interno canónico SI (m, Pa, s, m³, kg/m³, rad).
- A API pública declara a unidade no nome do parâmetro (`rho_bulk_g_cc`, `dt_us_per_ft`, `rt_ohm_m`) ou num argumento `Literal` (`length_unit: "m" | "ft"`). Nunca unidade implícita.
- Saídas trazem a unidade no nome da chave e em `record.units`.
- Fatores exatos por definição: pé internacional 0,3048 m; psi a partir de libra internacional e g padrão.
- Razões adimensionais avaliadas nas unidades de entrada (A-009).

## Alternativas
- Unidades de campo internas (ft, psi, bbl): habituais na indústria, mas favorecem mistura de sistemas.
- Pint: verificação dimensional automática; adiado (custo e dependência).

## Consequências
Balanço material (P2) usará unidades de campo declaradas na própria função, com conversão explícita na fronteira.
