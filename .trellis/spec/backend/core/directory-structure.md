# Backend Directory Structure

FilmOS uses FastAPI under `backend/app/`:

```text
app/
├── routers/    # HTTP input, auth dependencies, service calls, response schemas
├── services/   # business rules, use cases, transactions, current data access
├── schemas/    # Pydantic request and response contracts
├── models/     # SQLAlchemy ORM models
├── core/       # configuration, database, security, logging, observability
└── agent/      # LangGraph graph, tools, prompts, skills, and runner
```

## Placement rules

- Put HTTP orchestration in `routers/`, not business state transitions.
- Put domain rules and multi-entity transaction boundaries in `services/`.
- Keep ORM definitions in `models/` and API contracts in `schemas/`.
- `repositories/` is reserved; do not add forwarding-only repository classes.
- Keep optional infrastructure, such as Phoenix setup, isolated in `core/` and non-blocking.
- Group files by domain using existing names such as `orders.py`, `production_tasks.py`, and `order_service.py`.

## Real examples

- `backend/app/routers/orders.py` delegates order use cases.
- `backend/app/services/order_service.py` owns order rules and formula snapshots.
- `backend/app/services/production_service.py` owns production state changes.
- `backend/app/services/order_intake_service.py` owns controlled text/image draft extraction and shared image validation; it does not own attachment persistence.
- `backend/app/services/chat_attachment_service.py` owns chat attachment file persistence, compensation cleanup, and protected file resolution; PostgreSQL stores only attachment metadata.
- `backend/app/services/schedule_service.py` owns deterministic schedule generation, staleness checks, and atomic plan application.
- `backend/app/agent/runner.py` drives Agent execution and SSE events.

See `backend/README.md` and `meta/ENGINEERING_RULES.md` for the complete boundary rules.
