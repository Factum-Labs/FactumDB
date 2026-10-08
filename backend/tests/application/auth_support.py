"""Test-only device port; real account persistence and authentication are retained."""

from sidecar.desktop import DesktopRuntime

PASSWORD = "Examiner test password 123"


class FakeDeviceSecurity:
    def identity(self):
        return "test:device-user"

    def verify(self):
        return self.identity()


def authenticated_runtime(root):
    runtime = DesktopRuntime(root, device=FakeDeviceSecurity())
    if runtime.auth.accounts.find("examiner"):
        runtime.auth.login({"username": "Examiner", "password": PASSWORD})
    else:
        runtime.auth.signup(
            {"username": "Examiner", "password": PASSWORD, "password_confirmation": PASSWORD}
        )
    return runtime
