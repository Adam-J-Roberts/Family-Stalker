# Backend

FastAPI/Uvicorn with SQLAlchemy/PostgreSQL. `app.py` serves the first-run site and administrative account APIs; `static/` contains its local assets. See [implemented scope and acceptance](../../docs/server-setup.md) and [deployment](../../deploy/README.md).

Location and device-pairing APIs remain unavailable. The server does not receive household private decryption keys. Its separate persistent `server.key` encrypts SMTP credentials and queued email; this is server storage protection, not household E2EE.

## Local checks

```bash
python3 -m venv .venv
.venv/bin/pip install -r services/backend/requirements-dev.txt
.venv/bin/python -m unittest discover -s services/backend -v
```

Tests use temporary SQLite databases. CI repeats them against a disposable PostgreSQL database and smoke-tests the hardened image. `STALKER_TEST_DATABASE_URL` is explicitly a **disposable test database**: the test suite drops its tables. Never point it at a deployment database.

Only one application replica/worker is supported. The initial schema has a version guard; future schema changes require reviewed migrations.
