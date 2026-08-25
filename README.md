# Generation Service — Deployment

## Architecture

```
                 ┌─────────┐        ┌───────────────┐
  client ───────▶│   api   │──enqueue──▶│  redis queue │
                 └─────────┘        └───────┬───────┘
                                             │ dequeue
                                     ┌───────▼────────┐
                                     │     worker      │
                                     │ (LLMOrchestrator)│
                                     └───┬────────┬────┘
                                         │        │
                                   moderation   provider
                                   (Hive/     (Claude/OpenAI/
                                    Sightengine) self-hosted)
                                         │
                                     ┌───▼────┐
                                     │postgres │  audit log +
                                     │(audit)  │  human review queue
                                     └─────────┘
```

The API process only enqueues jobs and reports status — it never calls an
LLM provider directly. The worker process is the only thing that holds an
`LLMOrchestrator`, so a slow provider or moderation call never blocks an
HTTP request thread, and you can scale API replicas and worker replicas
independently based on where your actual bottleneck is.

## Before you deploy — non-negotiable prerequisites

This scaffolding assumes these are already in place; it does not implement
them:

1. **Age/identity verification** gating account activation (Persona,
   Veriff, Stripe Identity, etc.) — sits in front of everything here.
   `user_id` should only ever reach `/v1/generate` for a verified session.
2. **`HIVE_API_KEY` and Sightengine credentials** actually set. Per
   `moderation/service.py`, missing credentials means every request fails
   closed (blocked), not open — the service won't silently skip
   moderation.
3. **A real CSAM-detection integration** for any image/video generation
   you add later (see `moderation/service.py` and
   `moderation/sightengine_client.py` docstrings) — general nudity
   classifiers are not sufficient on their own, and any confirmed hit
   needs a legal-reviewed reporting workflow (NCMEC CyberTipline in the
   US), not an improvised call from application code.
4. Legal review of your target markets' specific age-verification and
   content laws (these vary and change — e.g. UK Online Safety Act) before
   launch in that market.

## Local / staging deployment

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY, OPENAI_API_KEY, HIVE_API_KEY, etc.

docker compose up --build
```

This brings up Postgres, Redis, runs the one-off `migrate` job to create
tables, then starts the `api` and `worker` services. API is on
`localhost:8000`; check `GET /healthz`.

Scale workers for throughput:
```bash
docker compose up --scale worker=4
```

## Endpoints

- `POST /v1/generate {"prompt": "..."}` → `202 {"job_id": "...", "status": "queued"}`
- `GET /v1/generate/{job_id}` → `{"status": "queued"|"running"|"done"|"blocked"|"failed", "result": {...} | null, "error": "..." | null}`
- `GET /v1/review-queue` → pending human-review items (gate this behind moderator auth in production — not done here)
- `POST /v1/review-queue/{request_id}/resolve {"reviewer_id": "...", "approved": true|false}`
- `GET /healthz`

## Production hardening still needed

- **Auth**: `/v1/generate` needs a real auth dependency resolving to a
  KYC-verified `user_id`; `/v1/review-queue*` needs moderator-role auth.
  Both are stubbed as comments in `api.py`.
- **Migrations**: `init_db.py` does `create_all` from ORM metadata, fine
  for a first deploy. Switch to Alembic before you have real data you
  can't afford to lose to a schema change.
- **TLS/ingress**: put this behind a real load balancer / ingress
  terminating TLS (nginx, an ALB, etc.) — not included here.
- **Secrets**: `.env` is fine for local dev; use your platform's secrets
  manager (AWS Secrets Manager, Vault, etc.) in production rather than an
  env file on disk.
- **Observability**: hook `logging` calls throughout (already structured
  with `extra=`) into your log aggregator; add metrics around queue depth,
  job latency, and moderation block/review rates specifically — those
  numbers are what you'll want on a dashboard.
- **Rate limiting**: add per-user rate limits at the API layer (e.g. via
  an API gateway or `slowapi`) before this is public.

## Testing without live provider credentials

The core logic (orchestrator retry/fallback, moderation policy, job
queue, worker lifecycle) is unit-testable without real Hive/Sightengine/
Redis credentials by injecting fakes matching the relevant protocols —
see the test snippets used during development of this scaffold for the
pattern (fake `AsyncRedisLike` client, fake moderation client returning
canned `ModerationResult`s, fake `LLMAdapter`). Wire these into a proper
`pytest` suite under a `tests/` directory before relying on this in
production; none is included here.
