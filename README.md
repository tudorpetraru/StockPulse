# StockPulse

Local-first stock research and portfolio tracking application.

## Quick start

```bash
PYTHON_BIN=/opt/homebrew/bin/python3.11 ./scripts/bootstrap_env.sh
source .venv/bin/activate
python run.py
```

Open [http://localhost:8000](http://localhost:8000).

## Migrations

```bash
source .venv/bin/activate
alembic upgrade head
```
