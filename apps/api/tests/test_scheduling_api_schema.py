"""Schema/client drift checks also run without a PostgreSQL service."""

import runpy
from pathlib import Path


def test_generated_scheduling_client_matches_public_openapi():
    root = Path(__file__).resolve().parents[3]
    generator = runpy.run_path(str(root / "scripts/generate-scheduling-client.py"))
    assert (
        generator["OUTPUT"].read_text(encoding="utf-8")
        == generator["generated_source"]()
    )
