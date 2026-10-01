from __future__ import annotations

import sys

from sidecar.protocol import CommandRouter, serve
from sidecar.commands import ApplicationServices, register_application_commands


def build_router(services: ApplicationServices | None = None) -> CommandRouter:
    router = CommandRouter()
    router.register(
        "health",
        lambda payload: {
            "name": "FactumDB",
            "status": "ready",
            "protocol": 1,
            "application_configured": services is not None,
        },
    )
    register_application_commands(router, services)
    return router


def main(services: ApplicationServices | None = None) -> None:
    serve(sys.stdin, sys.stdout, build_router(services))


if __name__ == "__main__":
    main()
