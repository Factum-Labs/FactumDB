"""Select native device security without importing another platform's APIs."""

import sys


def device_security(*, verify_device=None):
    if sys.platform == "win32":
        from .windows import WindowsDeviceSecurity

        return WindowsDeviceSecurity(verify_device=verify_device)
    if sys.platform == "linux":
        from .linux import LinuxDeviceSecurity

        return LinuxDeviceSecurity()
    raise RuntimeError("Device authentication is supported on Windows and Linux")
