"""Cold authentication stays lightweight; feature warm-up is authenticated."""
import subprocess
import sys


from tests.application.auth_support import authenticated_runtime


def test_cold_authentication_does_not_import_feature_bundles(tmp_path):
    code = """
import sys
from sidecar.desktop import DesktopRuntime
runtime = DesktopRuntime(sys.argv[1])
try:
    from sidecar.protocol import SidecarRequest
    router = runtime.router()
    assert router.dispatch(SidecarRequest('1', 'health', {})).ok
    assert router.dispatch(SidecarRequest('2', 'auth_status', {})).ok
    for module in ('fpdf', 'fontTools', 'uharfbuzz', 'sidecar.composition',
                   'core.application.use_cases.analysis',
                   'adapters.persistence.summary_report'):
        assert module not in sys.modules, module
finally:
    runtime.close()
"""
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_dependency_warmup_requires_authentication_and_does_not_open_cases(tmp_path):
    from sidecar.protocol import SidecarRequest
    runtime = authenticated_runtime(tmp_path)
    try:
        router = runtime.router()
        for kind in ('report', 'analysis', 'pdf'):
            result = router.dispatch(SidecarRequest(kind, 'warm_dependencies', {'kind': kind}))
            assert result.ok
            assert result.result == {'kind': kind, 'ready': True}
            assert not runtime.sessions
        assert not router.dispatch(SidecarRequest('bad', 'warm_dependencies', {'kind': 'other'})).ok
        runtime.auth.logout({})
        denied = router.dispatch(SidecarRequest('denied', 'warm_dependencies', {'kind': 'pdf'}))
        assert not denied.ok
        assert denied.error_code == 'AuthenticationRequiredError'
    finally:
        runtime.close()
