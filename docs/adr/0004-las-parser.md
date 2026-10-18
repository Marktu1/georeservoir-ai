# ADR-0004 — Leitura de LAS: `lasio` como dependência opcional

- Estado: aceite · Data: 2026-10-18

## Contexto
A Fase 2 exige leitura de LAS 2.0/3.0 e de surveys com proveniência. O prompt pede avaliar bibliotecas open-source maduras antes de escrever parsers, e qualquer dependência nova exige ADR. O núcleo numérico deve continuar puro (NumPy + SciPy).

## Opções avaliadas
| Opção | Licença | Situação | Avaliação |
|---|---|---|---|
| `lasio` 0.32 | MIT | Projeto ativo desde 2013, ~95 ficheiros de teste públicos incluindo casos patológicos | Lê LAS 1.2/2.0 (incluindo *wrapped*, codificações UTF-16/cp1252). LAS 3.0 parcial: perde arrays e secções definidas pelo utilizador. Converte valores do cabeçalho para número (perde o texto original). |
| `welly` | Apache-2.0 | Usa `lasio` por baixo | Acrescenta objetos de poço; dependências pesadas (pandas). Não necessário agora. |
| Parser próprio | — | — | Controlo total, mas reinventa casos-limite que o `lasio` já cobre e testa. |

## Decisão
- `lasio>=0.31` como dependência **opcional** (`pip install georeservoir[io]`), importada só dentro de `georeservoir.io.las.read_las`. O núcleo (`common`, `engineering`) não a importa.
- Por cima do `lasio`, uma camada própria: SHA-256 dos bytes lidos, texto *verbatim* do cabeçalho (o `lasio` re-formata números), NULL só pelo valor declarado, deteção de sentinelas suspeitas e vírgula decimal, verificações do índice, normalização explícita de unidades e mnemónicas e captura dos avisos do parser num relatório.
- LAS 3.0 fica **M0**: recusa com erro descritivo, em vez de uma leitura parcial silenciosa.
- Leitor de surveys em Python puro (`csv`), sem dependência.

## Licenças
`lasio`: MIT — compatível com qualquer opção do ADR-0002. Os ficheiros de teste copiados para `tests/data/las/` vêm do repositório do `lasio` (MIT; licença em `tests/data/las/LICENSE-lasio`).

## Consequências
- Instalações só do núcleo continuam leves.
- Uma mudança de comportamento do `lasio` é apanhada pelo teste do portão (`tests/io/test_las.py`), que compara cabeçalhos e dados com um parser independente escrito no próprio teste.
