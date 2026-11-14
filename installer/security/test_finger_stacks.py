"""The sudo and polkit stacks with phase 4's finger line first, run as PAM
runs them, in harness/pam.py's sandbox (harness/converse.py answering): a
finger or the password lets you in, nothing else does, and without
pam_fprintd (or with no reader, no print) the password works as before.

pam_fprintd is a stand-in reader in its place (pam_exec), which matches once
the test touched it; system-auth is a password check.
"""

import json
import subprocess
import unittest
import unittest.mock
from pathlib import Path

from jupiter import phase4

from harness import SECRET, TESTING, pam, temporary

STACKS = {
    "sudo": "#%PAM-1.0\nauth\t\tinclude\t\tsystem-auth\naccount\t\tinclude\t\tsystem-auth\n",
    "polkit-1": "#%PAM-1.0\n\nauth       include      system-auth\naccount    include      system-auth\n",
}
SYSTEM_AUTH = """auth [success=1 default=ignore] pam_exec.so expose_authtok quiet {folder}/password
auth requisite pam_deny.so
auth required pam_permit.so
account required pam_permit.so
"""


@unittest.skipIf(pam.available(), pam.available())
class FingerFirst(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = temporary(self)
        self.stacks = self.folder / "pam.d"
        self.stacks.mkdir()
        scripts = {
            "password": f'#!/bin/sh\nread -r p\n[ "$p" = "{SECRET}" ]\n',
            "reader": (
                "#!/bin/sh\necho 'Place your finger on the fingerprint reader'\n"
                f'[ -e "{self.folder}/touched" ]\n'
            ),
        }
        for name, text in scripts.items():
            (self.folder / name).write_text(text)
            (self.folder / name).chmod(0o755)
        (self.stacks / "system-auth").write_text(
            SYSTEM_AUTH.format(folder=self.folder)
        )

    def write(self, name: str, reader: str) -> None:
        """The stack as phase 4 leaves it, its pam_fprintd replaced."""
        target = self.stacks / name
        target.write_text(STACKS[name])
        with unittest.mock.patch.object(phase4, "run", self.install):
            phase4._take_a_finger(target, None)
        target.write_text(target.read_text().replace("pam_fprintd.so", reader))

    @staticmethod
    def install(*command: str | Path) -> None:
        Path(command[-1]).write_text(Path(command[-2]).read_text())

    def login(self, name: str, *answers: str) -> int:
        done = subprocess.run(
            pam.command(
                self.stacks, "python3", str(TESTING / "harness/converse.py"),
                name, "nobody-in-particular",
            ),
            input=json.dumps(list(answers)),
            capture_output=True,
            text=True,
            check=True,
        )  # fmt: skip
        result = json.loads(done.stdout)
        code: int = result["authenticate"]
        return code

    def readers(self) -> dict[str, str]:
        return {
            "a reader": f"pam_exec.so quiet stdout {self.folder}/reader",
            "no pam_fprintd": "pam_not_installed.so",
        }

    def test_a_finger_or_the_password_and_nothing_else(self) -> None:
        for name in STACKS:
            for kind, reader in self.readers().items():
                with self.subTest(stack=name, reader=kind):
                    self.write(name, reader)
                    (self.folder / "touched").unlink(missing_ok=True)
                    self.assertEqual(self.login(name, SECRET), 0)
                    self.assertNotEqual(self.login(name, "wrong"), 0)
                    self.assertNotEqual(self.login(name, ""), 0)
                    (self.folder / "touched").touch()
                    touched = self.login(name, "wrong")
                    self.assertEqual(touched == 0, kind == "a reader")


if __name__ == "__main__":
    unittest.main()
