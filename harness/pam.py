"""A PAM sandbox: a command run with a folder of stand-in stacks as its
/etc/pam.d, as the user running the tests.

The lock screen authenticates through the system's own `login` stack, which
a test cannot answer without a real password, nor change without root. In a
user namespace the test is root over a mount namespace of its own, binds its
folder over /etc/pam.d there, and maps itself back to its own uid in a
second namespace inside, so the program sees its own user name and the
stacks run unprivileged modules only: pam_exec with expose_authtok checks a
password against a script, pam_stress asks a second question, pam_deny
refuses as a wrong password does. That is pam_wrapper's idea (cwrap.org)
with util-linux alone. Nothing outside the namespace sees the bind.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

# Binds $3 over /etc/pam.d, then runs the rest as the caller ($1:$2) again.
# The tools by path: the program's own PATH may hold nothing.
BIND = (
    'uid=$1 gid=$2 stacks=$3 && shift 3 && {mount} --bind "$stacks" /etc/pam.d'
    ' && exec {unshare} --user --map-user="$uid" --map-group="$gid" -- "$@"'
)


def tool(name: str) -> str:
    return shutil.which(name) or name


def command(stacks: Path, *program: str) -> list[str]:
    """`program` with the stacks in `stacks` as its /etc/pam.d."""
    script = BIND.format(mount=tool("mount"), unshare=tool("unshare"))
    return [
        tool("unshare"),
        "--user",
        "--map-root-user",
        "--mount",
        "--",
        tool("sh"),
        "-c",
        script,
        "sh",
        str(os.getuid()),
        str(os.getgid()),
        str(stacks),
        *program,
    ]


@functools.cache
def available() -> str:
    """ "" where the sandbox works here, otherwise why not (a kernel without
    unprivileged user namespaces, a container that forbids them)."""
    probe = subprocess.run(
        command(Path("/etc/pam.d"), "true"),
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return f"no PAM sandbox here: {probe.stderr.strip()}"
    return ""
