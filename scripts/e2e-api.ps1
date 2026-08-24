param([int]$Port = 8000)
$ErrorActionPreference = 'Stop'
uv run alembic upgrade head
uv run python -m poi_admin.seed --reset
$worker = Start-Process -FilePath 'uv' -ArgumentList @('run', 'python', '-m', 'poi_admin.worker', '--poll-seconds', '0.2') -PassThru -WindowStyle Hidden
try {
    uv run uvicorn poi_admin.main:app --app-dir backend --host 127.0.0.1 --port $Port
} finally {
    if ($worker -and !$worker.HasExited) { Stop-Process -Id $worker.Id -Force }
}
