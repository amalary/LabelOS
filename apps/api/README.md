# Label OS API

FastAPI backend service for Label OS.

## Development

Create a virtual environment and install dependencies:

```sh
cd apps/api
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ../../packages/database
python -m pip install -e ".[dev]"
```

Run the API:

```sh
python scripts/dev.py
```

Run tests, linting, and formatting:

```sh
python -m pytest
python -m ruff check .
python -m black .
```

The API reads configuration from environment variables. Start from the root `.env.example`.

Database migrations live in `packages/database`. Run database commands from the repository root:

```sh
pnpm db:start
pnpm db:migrate
pnpm db:migration -- -m "describe change"
pnpm db:rollback
```
