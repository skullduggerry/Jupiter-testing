"""The tests of Jupiter-nixos: phase 1 from the first question to
nixos-install against stand-in commands and a temporary /mnt, phases 2 and 3
the same way in a throwaway home, and the flake's modules evaluated with
Nix where it is installed. What reaches the disk's passphrase, the
passwords and the PAM stacks is security/.
"""

import sys

from harness import NIXOS

# `import jupiter_nixos`, as `python3 -m jupiter_nixos` does from its folder.
if str(NIXOS) not in sys.path:
    sys.path.insert(0, str(NIXOS))
