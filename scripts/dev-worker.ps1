param([int]$PollSeconds = 2)
$ErrorActionPreference = 'Stop'
uv run alembic upgrade head
uv run python -m poi_admin.worker --poll-seconds $PollSeconds
