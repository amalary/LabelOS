$ErrorActionPreference = "Stop"

$values = @{}
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        $values[$matches[1].Trim()] = $matches[2].Trim()
    }
}

foreach ($entry in $values.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
}

$db = $values["POSTGRES_DB"]
$user = $values["POSTGRES_USER"]
$password = $values["POSTGRES_PASSWORD"]
$port = $values["POSTGRES_PORT"]

$env:DATABASE_URL = "postgresql+psycopg://${user}:${password}@localhost:${port}/${db}"
$env:APP_ENV = "local"
$root = (Get-Location).Path
$env:PYTHONPATH = "$root/apps/api/src;$root/packages/database/src"

Set-Location apps/api
python scripts/dev.py
