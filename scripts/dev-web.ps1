param([int]$Port = 5173)
$ErrorActionPreference = 'Stop'
Push-Location frontend
try { npm.cmd run dev -- --host 127.0.0.1 --port $Port } finally { Pop-Location }
