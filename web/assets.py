"""Content-versioned static assets and cache policy."""
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs

from starlette.staticfiles import StaticFiles


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
# Calculated once when the application loads, before page headers are built.
ASSET_VERSIONS = {
    name: sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:12]
    for name in ("app.js", "app.css", "fonts/fonts.css", "design.css", "public.css")
}


def asset_url(name: str) -> str:
    return f"/static/{name}?v={ASSET_VERSIONS[name]}"


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            versioned = "v" in parse_qs(scope.get("query_string", b"").decode(), keep_blank_values=True)
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable" if versioned else "public, max-age=300"
            )
        return response
