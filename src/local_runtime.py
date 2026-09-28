"""Run the local ASGI app with root dotenv settings and no Worker bindings."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
import uvicorn
from dotenv import dotenv_values

from worker import LineLoginSettings, create_app


ROOT = Path(__file__).resolve().parents[1]


def load_local_settings(env_path: Path | None = None) -> LineLoginSettings:
    """Read local LINE Login settings without logging or exporting them."""
    env_path = env_path or ROOT / ".env"
    values = dotenv_values(env_path)
    return LineLoginSettings.from_mapping(
        {
            name: value or ""
            for name, value in values.items()
            if name != "NIY006_LOCAL_TEST_MODE"
        }
    )


def create_local_app() -> FastAPI:
    """Create the local app without Cloudflare bindings or test controls."""
    return create_app(settings=load_local_settings())


if __name__ == "__main__":
    uvicorn.run(create_local_app(), host="127.0.0.1", port=8787)
