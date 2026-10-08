"""Read-only diagnostics suitable for native Linux or Ubuntu WSL."""
import os
from pathlib import Path
import shutil
import subprocess

print("UID:", os.getuid())
print("Python:", shutil.which("python3"))
print("pkcheck:", shutil.which("pkcheck"))
print("System bus:", Path("/run/dbus/system_bus_socket").exists())
print("FactumDB policy:", Path("/usr/share/polkit-1/actions/org.factumdb.signup.policy").exists())
print("Processes:")
processes = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True, check=False)
for line in processes.stdout.splitlines():
    if any(name in line for name in ("polkit", "agent", "gnome-shell", "plasma")):
        print(" ", line)
