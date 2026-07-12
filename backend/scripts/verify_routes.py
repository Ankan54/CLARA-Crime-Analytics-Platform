"""Assert every expected FastAPI route is registered, without a DB connection or
running server — just imports app.main:app and reads its OpenAPI schema.

Run: python backend/scripts/verify_routes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

EXPECTED_ROUTES: dict[str, set[str]] = {
    "/healthz": {"get"},
    "/api/v1/upload": {"post"},
    "/api/v1/upload/{batch_id}": {"get"},
    "/api/v1/process/{batch_id}": {"post"},
    "/api/v1/process/{run_id}/proceed": {"post"},
    "/api/v1/process/{run_id}/retry": {"post"},
    "/api/v1/process/{run_id}/findings": {"get"},
    "/api/v1/runs": {"get"},
    "/api/v1/pipeline-status/{run_id}": {"get"},
    "/api/v1/review-queue": {"get"},
    "/api/v1/review-queue/{review_id}/resolve": {"post"},
    "/api/v1/admin/config": {"get"},
    "/api/v1/admin/config/{config_key}": {"put"},
    "/api/v1/admin/config/entity-review-threshold": {"get", "put"},
    "/api/v1/admin/schema": {"get"},
    "/api/v1/admin/schema/{doc_type}": {"get", "post"},
    "/api/v1/admin/schema/{doc_type}/versions": {"get"},
    "/api/v1/admin/schema/{doc_type}/activate/{version}": {"put"},
    "/api/v1/admin/schema/{doc_type}/rollback/{version}": {"post"},
    "/api/v1/cases": {"get", "post"},
    "/api/v1/cases/{case_id}": {"get"},
    "/internal/entity/splink-match": {"post"},
    "/internal/pipeline-event": {"post"},
}


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    spec = TestClient(app).get("/openapi.json").json()
    actual: dict[str, set[str]] = {path: set(methods.keys()) for path, methods in spec["paths"].items()}

    failures = []
    for path, methods in EXPECTED_ROUTES.items():
        if path not in actual:
            failures.append(f"MISSING route: {path}")
            continue
        missing_methods = methods - actual[path]
        if missing_methods:
            failures.append(f"MISSING method(s) {sorted(missing_methods)} on {path}")

    # Also confirm the websocket route exists on the underlying Starlette app
    # (not reflected in the OpenAPI schema).
    ws_paths = {getattr(r, "path", None) for r in app.routes if type(r).__name__ == "APIWebSocketRoute"}

    def _flatten_ws_paths() -> set[str]:
        # FastAPI >=0.139 wraps included routers lazily; walk router.routes recursively.
        found: set[str] = set(ws_paths)
        for route in app.routes:
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                for sub in getattr(original_router, "routes", []):
                    if type(sub).__name__ == "APIWebSocketRoute":
                        found.add(sub.path)
        return found

    if "/ws/pipeline/{run_id}" not in _flatten_ws_paths():
        failures.append("MISSING websocket route: /ws/pipeline/{run_id}")

    if failures:
        print(f"FAIL  {len(failures)} route check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"PASS  All {len(EXPECTED_ROUTES)} expected routes (+ websocket) are registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
