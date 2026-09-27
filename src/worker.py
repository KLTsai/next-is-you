"""Cloudflare Python Worker entrypoint for the local application."""

from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

try:
    from workers import asgi
except ModuleNotFoundError as error:
    if error.name != "js":
        raise
    asgi = None

app = FastAPI(docs_url=None, redoc_url=None)
STATIC_ASSET_ROOT = Path(__file__).resolve().parents[1] / "dist"


@app.get("/api/healthz")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "mode": "local-development"}


@app.get("/{path:path}")
async def serve_static_asset(path: str, request: Request) -> Response:
    """Proxy non-API requests to Workers Static Assets after the UI build."""
    env = request.scope.get("env")
    if env is None:
        asset_path = (STATIC_ASSET_ROOT / (path or "index.html")).resolve()
        if not asset_path.is_relative_to(STATIC_ASSET_ROOT.resolve()) or not asset_path.is_file():
            return Response(status_code=404)
        return FileResponse(asset_path)

    asset_path = path or "index.html"
    asset_response = await env.ASSETS.fetch(f"https://assets.local/{asset_path}")
    return Response(
        content=await asset_response.bytes(),
        status_code=asset_response.status,
        headers=asset_response.headers,
    )


if asgi is not None:
    Default = asgi.entrypoint(app)
