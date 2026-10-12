import json

import pytest

from core.application.safe_errors import safe_error
from sidecar.protocol import CommandRouter, SidecarRequest
from tests.application.test_orchestrator import STAGES, Handler, orchestrator

SECRETS = (
    "password=fake-secret token=fake-token mysql://alice:fake-pass@host/db "
    "C:\\Users\\Alice\\evidence.ibd /home/alice/case alice@example.com"
)


@pytest.mark.parametrize("kind", [RuntimeError, ValueError, PermissionError, OSError])
def test_errors_never_contain_exception_text(kind):
    code, message = safe_error(kind(SECRETS * 1000))
    assert SECRETS not in message
    assert len(message) < 200
    assert code


def test_transport_drops_exception_details():
    router = CommandRouter()

    def fail(payload):
        raise RuntimeError(SECRETS)

    router.register("fail", fail)
    text = router.dispatch(SidecarRequest("request", "fail", {})).to_json()
    assert "fake-secret" not in text
    assert "Alice" not in text
    assert "example.com" not in text


def test_saved_pipeline_and_progress_drop_exception_details():
    class LeakyHandler(Handler):
        def execute(self, context):
            raise RuntimeError(SECRETS)

    service, repository, publisher, _ = orchestrator(tuple(LeakyHandler(s) for s in STAGES))
    run = service.run_all(service.start("case-1").id)
    saved = repository.get(run.id)
    text = json.dumps(
        [saved.stages[0].attempts[0].error_message, *[event.message for event in publisher.events]]
    )
    assert "fake-secret" not in text
    assert "Alice" not in text
    assert "example.com" not in text
