import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from labelos_api.config import get_settings  # noqa: E402

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "labelos_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
