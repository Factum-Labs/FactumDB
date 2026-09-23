from __future__ import annotations

import sys

from sidecar.protocol import CommandRouter, serve


def build_router() -> CommandRouter:
    router = CommandRouter()
    router.register(
        "health",
        lambda payload: {
            "name": "FactumDB",
            "status": "ready",
            "protocol": 1,
        },
    )
    # Production composition will register application use cases here after the
    # SQLite repositories and external-tool adapters have landed.
    return router


def main() -> None:
    serve(sys.stdin, sys.stdout, build_router())


if __name__ == "__main__":
    main()
