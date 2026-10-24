"""The tests of Jupiter-installer: phase 1 from the first question to the
last file against stand-in commands and a temporary /mnt, phases 2 to 4 the
same way in a throwaway home. Who is made a user, with which password and
which rights, is security/.
"""

import sys

from harness import INSTALLER

# `import jupiter`, as `python3 -m jupiter` does from the installer's folder.
if str(INSTALLER) not in sys.path:
    sys.path.insert(0, str(INSTALLER))
