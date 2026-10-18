# ADR-0005 — API HTTP (Fase 3)

- Estado: aceite · Data: 2026-10-18

## Contexto
A Fase 3 pede uma API versionada (`/api/v1/...`) que devolva `CalculationRecord`, com autenticação, autorização por projeto, limites de upload, timeouts, OpenAPI e logs sem dados sensíveis; nunca aceitar caminhos arbitrários nem executar código enviado. O núcleo tem de continuar puro.

## Decisão
- **FastAPI** (MIT) sobre Starlette (BSD-3) e Pydantic v2 (MIT); servidor **uvicorn** (BSD-3); uploads com **python-multipart** (Apache-2.0). Tudo no extra opcional `[api]`; o núcleo não importa nada disto (teste `tests/io/test_core_purity.py`).
- **Contrato**: cada endpoint de cálculo chama exatamente uma função do núcleo e devolve o seu `CalculationRecord` sem alterações, dentro de `{"api_version": "v1", "project_id": ..., "record": ...}`. O documento OpenAPI é versionado em `docs/api/openapi-v1.json` e um teste falha se mudar sem regenerar o snapshot.
- **Autenticação**: tokens portadores (`Authorization: Bearer`), 256 bits aleatórios, guardados **só como SHA-256** num ficheiro de chaves controlado pelo operador; comparação em tempo constante sobre todas as chaves.
- **Autorização**: cada chave lista projetos e escopos (`calc`, `upload`). Projeto desconhecido ou não autorizado → 403 com a mesma mensagem (não revela existência).
- **Limites**: corpo JSON (10 MB por omissão; também em streaming sem `Content-Length`), upload (20 MB), tamanho de arrays (200 000), amostras de Monte Carlo (200 000), cálculos concorrentes (4), timeout por cálculo (30 s → 504), rate limit por chave (120/min → 429 com `Retry-After`).
- **Sem caminhos nem código**: o único parâmetro de caminho é `project_id` (regex `^[a-z0-9][a-z0-9_-]{0,62}$`); ficheiros só chegam por upload, são escritos numa pasta temporária privada com nome sanitizado e apagados após a leitura; não há campos de expressão, script, URL ou módulo (teste dedicado).
- **Erros tipados** `{"error": {"type", "message", "request_id"}}`: erros do núcleo → 422 com o tipo da exceção; `NotImplementedError` (M0) → 501; erros de validação sem eco dos valores enviados; erros internos → 500 "internal error" (sem detalhes).
- **Logs**: uma linha JSON por pedido com `request_id`, método, caminho, estado, duração, `key_id` e `project_id` — nunca corpo, ficheiros, nomes de ficheiro, query string ou cabeçalho `Authorization`.
- **Cabeçalhos**: `nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, CSP `default-src 'none'` (exceto `/docs`), `X-Request-ID`. Sem CORS por omissão.

## Alternativas
- Flask + marshmallow: maduro, mas OpenAPI e validação tipada exigem mais peças.
- Django REST: pesado para um serviço sem base de dados.
- OAuth2/OIDC: adequado para utilizadores finais (Fase 4); para integração máquina-a-máquina, chaves com escopos chegam nesta fase.

## Consequências e limites conhecidos
- O timeout devolve 504, mas a thread do cálculo **continua até terminar** (Python não interrompe threads); o limite de concorrência impede acumulação. Um isolamento por processo fica para quando houver carga real.
- O rate limit é **por processo**; com vários workers é preciso um armazenamento partilhado (ex.: Redis).
- **TLS** termina num proxy reverso (nginx, Caddy, balanceador); o servidor escuta em `127.0.0.1` por omissão e não confia em cabeçalhos `X-Forwarded-*`.
- Sem persistência: a API não guarda registos nem ficheiros (Fase 4+ decidirá o armazenamento; o `CalculationRecord` já é serializável).
