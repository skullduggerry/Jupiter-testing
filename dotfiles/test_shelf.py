"""The shelf's file work, services/shelf.sh, against a stand-in clipboard.

Pasting keeps text, an image or the files a file manager copied as new files,
numbered rather than written over, with a hidden name left visible, and never
a password manager's copy; a note is named after its first line; copying
puts text and images back as themselves and anything else as its file. Every
file is written under a hidden .part name first, and none of those is left.
"""

from __future__ import annotations

import os
import subprocess
import unittest

from harness import QUICKSHELL, executable, temporary

SCRIPT = QUICKSHELL / "services/shelf.sh"
STAMP = r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
# A clipboard made of files: $CLIP/types lists what it holds, and $CLIP/<type>
# (slashes as underscores) holds each. wl-copy keeps what it is given.
WL_PASTE = """#!/bin/sh
[ -f "$CLIP/types" ] || exit 1
[ "$1" = --list-types ] && exec cat "$CLIP/types"
for last; do :; done
exec cat "$CLIP/$(printf %s "$last" | tr / _)"
"""
WL_COPY = """#!/bin/sh
printf '%s\\n' "$*" >"$CLIP/copied-as"
cat >"$CLIP/copied"
"""


class Shelf(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.clip = self.tmp / "clip"
        self.shelf = self.tmp / "Shelf"
        executable(self.tmp / "bin/wl-paste", WL_PASTE)
        executable(self.tmp / "bin/wl-copy", WL_COPY)
        self.env = dict(
            os.environ,
            CLIP=str(self.clip),
            PATH=f"{self.tmp / 'bin'}:{os.environ['PATH']}",
        )

    def tearDown(self) -> None:
        if self.shelf.exists():
            self.assertEqual(
                list(self.shelf.glob(".*.part")), [], ".part left"
            )

    def clipboard(self, **held: str | bytes) -> None:
        if self.clip.exists():
            for old in self.clip.iterdir():
                old.unlink()
        self.clip.mkdir(exist_ok=True)
        (self.clip / "types").write_text("\n".join(held) + "\n")
        for kind, data in held.items():
            target = self.clip / kind.replace("/", "_")
            if isinstance(data, bytes):
                target.write_bytes(data)
            else:
                target.write_text(data)

    def shelf_sh(self, *args: str) -> tuple[int, list[str]]:
        result = subprocess.run(
            [str(SCRIPT), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout.splitlines()

    def paste(self) -> tuple[int, list[str]]:
        return self.shelf_sh("paste", str(self.shelf))

    def test_text_as_a_file_named_by_the_time(self) -> None:
        self.clipboard(
            **{"text/plain;charset=utf-8": "", "text": "hello shelf"}
        )
        code, names = self.paste()
        self.assertEqual(code, 0)
        self.assertRegex(names[0], f"^{STAMP}\\.txt$")
        self.assertEqual((self.shelf / names[0]).read_text(), "hello shelf")

    def test_an_image_as_itself(self) -> None:
        self.clipboard(**{"image/png": PNG})
        code, names = self.paste()
        self.assertEqual(
            (code, [n.endswith(".png") for n in names]), (0, [True])
        )

    def test_copied_files_under_their_names(self) -> None:
        source = self.tmp / "My notes"
        source.mkdir()
        (source / "plan.txt").write_text("the plan")
        (source / ".hidden").write_text("not hidden on the shelf")
        uris = "\r\n".join(
            [
                "file://" + str(source / "plan.txt").replace(" ", "%20"),
                "file://" + str(source / ".hidden").replace(" ", "%20"),
                "https://example.org/not-a-file",
            ]
        )
        self.clipboard(**{"text/uri-list": uris, "text": uris})
        self.assertEqual(self.paste(), (0, ["plan.txt", "hidden"]))
        self.assertEqual((self.shelf / "plan.txt").read_text(), "the plan")
        self.assertEqual(
            self.paste()[1], ["plan-1.txt", "hidden-1"], "numbered"
        )

    def test_an_empty_file_is_skipped_not_the_rest(self) -> None:
        source = self.tmp / "files"
        source.mkdir()
        (source / "empty.txt").write_text("")
        (source / "plan.txt").write_text("the plan")
        uris = "\r\n".join(
            "file://" + str(source / name)
            for name in ("empty.txt", "plan.txt")
        )
        self.clipboard(**{"text/uri-list": uris, "text": uris})
        self.assertEqual(self.paste(), (0, ["plan.txt"]))
        self.assertFalse((self.shelf / "empty.txt").exists())

    def test_a_password_managers_copy_stays_off_a_synced_folder(self) -> None:
        self.shelf.mkdir()
        self.clipboard(
            **{"text": "hunter2", "x-kde-passwordManagerHint": "secret"}
        )
        self.assertEqual(self.paste(), (3, []))
        self.assertEqual(list(self.shelf.iterdir()), [], "nothing written")

    def test_nothing_to_paste(self) -> None:
        self.clipboard(**{"text": "x"})
        (self.clip / "types").unlink()
        self.assertEqual(self.paste()[0], 1, "an empty clipboard")
        self.clipboard(**{"application/x-other": "?"})
        self.assertEqual(self.paste()[0], 1, "nothing it can keep")

    def test_notes_named_after_their_first_line(self) -> None:
        code, names = self.shelf_sh(
            "note", str(self.shelf), "  ../Groceries: milk/eggs?\nand bread"
        )
        self.assertEqual((code, names), (0, ["Groceries milkeggs.md"]))
        self.assertEqual(
            (self.shelf / "Groceries milkeggs.md").read_text(),
            "  ../Groceries: milk/eggs?\nand bread\n",
        )
        self.assertEqual(self.shelf_sh("note", str(self.shelf), " \n\t")[0], 1)

    def test_copying_back(self) -> None:
        self.shelf.mkdir()
        text = self.shelf / "plan.txt"
        text.write_text("the plan")
        image = self.shelf / "image.png"
        image.write_bytes(PNG)
        other = self.shelf / "form.pdf"
        other.write_bytes(b"%PDF-1.4\n%%EOF\n")
        self.clip.mkdir()
        for file, kind in ((text, ""), (image, "--type image/png")):
            with self.subTest(file.name):
                self.shelf_sh("copy", str(file))
                self.assertEqual(
                    (
                        (self.clip / "copied-as").read_text().strip(),
                        (self.clip / "copied").read_bytes(),
                    ),
                    (kind, file.read_bytes()),
                )
        self.shelf_sh("copy", str(other))
        self.assertEqual(
            (
                (self.clip / "copied-as").read_text().strip(),
                (self.clip / "copied").read_text().strip(),
            ),
            ("--type text/uri-list", other.as_uri()),
            "anything else copies as its file",
        )

    def test_an_unknown_command(self) -> None:
        self.assertEqual(self.shelf_sh("move")[0], 2)


if __name__ == "__main__":
    unittest.main()
