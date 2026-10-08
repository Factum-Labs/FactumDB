"""Polkit delegates verification to the desktop agent and configured PAM stack."""

import os
import shutil
import subprocess
from pathlib import Path

from core.application.authentication import AuthenticationError


class LinuxDeviceSecurity:
    def identity(self):
        return f"linux:uid:{os.getuid()}"

    def verify(self):
        executable = shutil.which("pkcheck")
        if executable is None:
            raise AuthenticationError(
                "Install polkit and a desktop authentication agent to sign up"
            )
        # Include start time and uid to avoid pid reuse/race ambiguity.
        stat = Path("/proc/self/stat").read_text()
        start = stat[stat.rfind(")") + 2 :].split()[19]
        subject = f"{os.getpid()},{start},{os.getuid()}"
        try:
            result = subprocess.run(
                [
                    executable,
                    "--action-id",
                    "org.factumdb.signup",
                    "--process",
                    subject,
                    "--allow-user-interaction",
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AuthenticationError("Device verification failed or timed out") from error
        if result.returncode != 0:
            raise AuthenticationError(
                "Device verification cancelled or unavailable. Check the FactumDB polkit policy "
                "and your desktop authentication agent (WSL may not provide one)."
            )
        return self.identity()
