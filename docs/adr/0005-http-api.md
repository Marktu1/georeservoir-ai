# ADR-0005 — API HTTP (Fase 3)

- Estado: aceite · Data: 2026-10-18

## Contexto
A Fase 3 pede uma API versionada (`/api/v1/...`) que devolva `CalculationRecord`, com autenticação, autorização por projeto, limites de upload, timeouts, OpenAPI e logs sem dados sensíveis; nunca aceitar caminhos arbitrários nem executar código enviado. O núcleo tem de continuar puro.

## Decisão
- **FastAPI** (MIT) sobre Starlette (BSD-3) e Pydantic v2 (MIT); servidor **uvicorn** (BSD-3); uploads com **python-multipart** (Apache-2.0). Tudo no extra opcional `[api]`; o núcleo não importa nada disto (teste `tests/io/test_core_purity.py`).
- **Contrato**: cada endpoint de cálculo chama exatamente uma função do núcleo e devolve o seu `CalculationRecord` sem alterações, dentro de `{"api_version": "v1", "project_id": ..., "record": ...}`. O documento OpenAPI é versionado em `docs/api/openapi-v1.json` e um teste falha se mudar sem regenerar o snapshot.
- **Autenticação**: tokens portadores (`Authorization: Bearer`), 256 bits aleatórios, guardados **só como SHA-256** num ficheiro de chaves controlado pelo operador; comparação em tempo constante sobre todas as chaves.
- **Autorização**: cada chave lista projetos e escopos (`calc`, `upload`). Projeto desconhecido ou não autorizado → 403 com a mesma mensagem (não revela existência).
- **Ordem de verificação** (num middleware ASGI, **antes de ler o corpo**): autenticação → rate limit (por chave; e por endereço do cliente para autenticações falhadas) → autorização de projeto/escopo → limite de tamanho do corpo escolhido pela rota → corpo. Pedidos anónimos com corpos grandes recebem 401 sem que o corpo seja processado; tentativas de adivinhar tokens e de sondar projetos contam para o rate limit.
- **Limites**: corpo JSON (10 MB por omissão; também em streaming sem `Content-Length`), upload (20 MB, só nas rotas `data/las` e `data/survey`), tamanho de arrays (200 000), amostras de Monte Carlo (200 000), números JSON estritos (inteiros aceites; booleanos, strings e ±∞ recusados), cálculos **em execução** (4), espera na fila (10 s → 503 com `Retry-After`), timeout por cálculo (30 s → 504, contado só depois de obter um lugar), rate limit (120/min → 429 com `Retry-After`; memória limitada a 10 000 identidades).
- **Sem caminhos nem código**: o único parâmetro de caminho é `project_id` (regex `^[a-z0-9][a-z0-9_-]{0,62}$`); ficheiros só chegam por upload, são escritos numa pasta temporária privada com nome sanitizado e apagados após a leitura; não há campos de expressão, script, URL ou módulo (teste dedicado).
- **Erros tipados** `{"error": {"type", "message", "request_id"}}`: erros do núcleo → 422 com o tipo da exceção; `NotImplementedError` (M0) → 501; erros de validação sem eco dos valores enviados; erros internos → 500 "internal error" (sem detalhes).
- **Logs**: uma linha JSON por pedido com `request_id`, método, caminho, estado, duração, `key_id` e `project_id` — nunca corpo, ficheiros, nomes de ficheiro, query string ou cabeçalho `Authorization`.
- **Cabeçalhos**: `nosniff`, `X-Frame-Options: DENY`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, CSP `default-src 'none'` (exceto `/docs`), `X-Request-ID` — em todas as respostas, incluindo 401/403/404/405/413/429/500 (testado). Sem CORS por omissão. Com `ENABLE_DOCS=0` tanto `/docs` como `/openapi.json` ficam desligados.

## Alternativas
- Flask + marshmallow: maduro, mas OpenAPI e validação tipada exigem mais peças.
- Django REST: pesado para um serviço sem base de dados.
- OAuth2/OIDC: adequado para utilizadores finais (Fase 4); para integração máquina-a-máquina, chaves com escopos chegam nesta fase.

## Consequências e limites conhecidos
- O timeout devolve 504, mas a thread do cálculo **continua até terminar** (Python não interrompe threads). O lugar de cálculo só é libertado pela própria thread quando termina, por isso nunca há mais de `max_concurrent_calcs` cálculos a correr (testado: cinco pedidos com timeout com 1 lugar → nunca mais de 1 thread; os restantes recebem 503). Um cálculo que nunca termina ocupa o seu lugar para sempre: o isolamento por processo (com terminação forçada) fica para quando houver carga real.
- A revisão adversarial da Fase 3 encontrou e levou a corrigir: lugares libertados no timeout com a thread ainda a correr (acumulação), espera na fila contada como tempo de cálculo, corpo lido antes da autenticação, 401/403 fora do rate limit, limite de upload escolhido por substring do caminho, respostas 500/404/405 sem cabeçalhos ou envelope, números em modo lato (`true` → 1,0), uploads duas vezes em memória e fora do limite de concorrência, `/openapi.json` público com docs desligadas.
- O rate limit é **por processo**; com vários workers é preciso um armazenamento partilhado (ex.: Redis). O limite por endereço usa o endereço da ligação: atrás de um proxy todos os clientes partilham o mesmo endereço (o servidor não confia em `X-Forwarded-For`).
- `/api/v1/health` é público e indica a versão da biblioteca (impressão digital menor, aceite para diagnóstico).
- **TLS** termina num proxy reverso (nginx, Caddy, balanceador); o servidor escuta em `127.0.0.1` por omissão e não confia em cabeçalhos `X-Forwarded-*`.
- Sem persistência: a API não guarda registos nem ficheiros (Fase 4+ decidirá o armazenamento; o `CalculationRecord` já é serializável).
