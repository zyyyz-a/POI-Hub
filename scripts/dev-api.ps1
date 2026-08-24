param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
uv run alembic upgrade head
uv run uvicorn poi_admin.main:app --app-dir backend --host 127.0.0.1 --port $Port --reload
