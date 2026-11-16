"""The tests of Jupiter-installer, on Arch and on NixOS: phase 1 from the
first question to the last file against stand-in commands and a temporary
/mnt, phases 2 to 4 the same way in a throwaway home; on NixOS also the
flake's modules, evaluated by Nix (test_nixos_flake.py). Who is made a
user, with which password and which rights, and what reaches the disk's
passphrase and the PAM stacks, is security/.

Which system the installer takes itself to be on (jupiter/distro.py) is
the stand-in os-release in fixtures/: Arch's unless a test says NixOS, so
the phases run as on Arch on whatever machine runs the tests.
"""

import os
import sys
from pathlib import Path

from harness import INSTALLER

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ARCH = FIXTURES / "arch-os-release"
NIXOS = FIXTURES / "nixos-os-release"

# Before jupiter is imported, which reads it then; the phases a test starts
# inherit it.
os.environ["JUPITER_OS_RELEASE"] = str(ARCH)

# `import jupiter`, as `python3 -m jupiter` does from the installer's folder.
if str(INSTALLER) not in sys.path:
    sys.path.insert(0, str(INSTALLER))
