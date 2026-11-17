"""The VM rig's parts that run without a VM: the console reader, the
mirror and the reasons it gives for skipping.

The console is one end of a socket pair standing in for QEMU's serial port;
upstream is a loopback server counting what it is asked for.
"""

import http.server
import io
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import typing
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from vm import install, rig


class Console(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        vars_ = tmp / "OVMF_VARS.fd"
        vars_.write_bytes(b"vars")
        self.enterContext(mock.patch.object(rig, "OVMF_VARS", vars_))
        self.machine = rig.Machine(tmp / "vm", [rig.Disk("system", 1)])
        ours, self.vm = socket.socketpair()
        self.addCleanup(self.vm.close)
        self.machine._serial = ours
        self.machine._log = open(tmp / "serial.log", "wb")  # noqa: SIM115
        self.addCleanup(self.machine._close)
        self.log = tmp / "serial.log"

    def test_makes_its_disks_sparse_and_its_firmware_a_copy(self) -> None:
        image = self.machine.disk("system")
        self.assertEqual(image.stat().st_size, 2**30)
        self.assertLess(image.stat().st_blocks * 512, 2**20)
        self.assertEqual(
            (self.machine.folder / "vars.fd").read_bytes(), b"vars"
        )

    def test_reads_past_escape_sequences_cut_in_two(self) -> None:
        self.vm.sendall(b"\x1b[1;3")
        self.vm.sendall(b"1mroot\x1b[0m@archiso ~ # \r\n")
        self.assertEqual(
            self.machine.expect(r"root@archiso ~ # \n", 2).group(0),
            "root@archiso ~ # \n",
        )
        self.assertIn(b"\x1b[1;31m", self.log.read_bytes(), "the log is raw")

    def test_a_clone_keeps_its_firmware_and_screen(self) -> None:
        self.machine.secure_boot_firmware = False
        self.machine.screen = True
        clone = self.machine.clone(self.machine.folder.parent / "clone")
        self.assertFalse(clone.secure_boot_firmware)
        self.assertTrue(clone.screen)

    def test_a_second_run_on_the_same_disks_refuses(self) -> None:
        self.machine._lock()
        other = rig.Machine(self.machine.folder, [rig.Disk("system", 1)])
        with self.assertRaisesRegex(
            RuntimeError, f"in use by process {os.getpid()}"
        ):
            other._lock()
        self.machine.kill()
        other._lock()  # free once the first is done with them
        other.kill()

    def test_a_folder_in_use_is_not_deleted(self) -> None:
        self.machine._lock()
        other = rig.Machine(self.machine.folder, [rig.Disk("system", 1)])
        with self.assertRaisesRegex(RuntimeError, "in use by process"):
            other.remove()
        self.assertTrue(self.machine.disk("system").exists())
        self.machine.kill()
        other.remove()
        self.assertFalse(self.machine.folder.exists())

    def test_a_failed_install_leaves_no_vm_running(self) -> None:
        killed = []
        with (
            mock.patch.object(install, "VMS", self.machine.folder.parent),
            mock.patch.object(
                install, "install", side_effect=RuntimeError("x")
            ),
            mock.patch.object(
                rig.Machine, "kill", lambda m: killed.append(m.folder)
            ),
            self.assertRaisesRegex(RuntimeError, "x"),
        ):
            install.installed(
                "failing", install.Answers(), [rig.Disk("system", 1)]
            )
        self.assertTrue(killed and killed[-1].name.startswith("failing-"))

    def test_a_vm_dies_with_the_run_that_started_it(self) -> None:
        # A driver that starts a stand-in VM the rig's way, then is killed.
        driver = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import subprocess, sys, time; "
                f"p = subprocess.Popen({rig.WITH_PARENT!r} + ['sleep', '60']); "
                "print(p.pid, flush=True); time.sleep(60)",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert driver.stdout
        vm = int(driver.stdout.readline())
        # Once it runs the VM's own command, setpriv has set the signal.
        started = time.monotonic() + 5
        while time.monotonic() < started:
            if Path(f"/proc/{vm}/cmdline").read_bytes().startswith(b"sleep"):
                break
            time.sleep(0.02)
        driver.kill()
        driver.wait()

        def alive() -> bool:
            # A zombie waiting for its new parent to reap it is dead.
            try:
                stat = Path(f"/proc/{vm}/stat").read_text()
            except OSError:
                return False
            return stat.rsplit(")", 1)[1].split()[0] != "Z"

        deadline = time.monotonic() + 5
        while alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(), "the VM outlived it")

    def test_a_silent_console_fails_long_before_the_timeout(self) -> None:
        self.machine.silence = 0.3
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "silent for 0 s"):
            self.machine.expect("never", 30)
        self.assertLess(time.monotonic() - started, 3)

    def test_consumes_what_it_matched(self) -> None:
        self.vm.sendall(b"one\ntwo\n")
        self.machine.expect(r"one\n", 2)
        with self.assertRaisesRegex(TimeoutError, "two"):
            self.machine.expect(r"one\n", 0.2)

    def test_runs_a_command_and_gives_its_output_and_status(self) -> None:
        def shell() -> None:
            typed = b""
            while b"end\n" not in typed:
                typed += self.vm.recv(4096)
            token = typed.split(b":")[1]
            self.vm.sendall(
                b":" + token + b":start\nhello\n:" + token + b":3:end\n"
            )

        thread = threading.Thread(target=shell)
        thread.start()
        with self.assertRaisesRegex(AssertionError, "failed with 3:\nhello"):
            self.machine.sh("false")
        thread.join()


class Upstream(http.server.BaseHTTPRequestHandler):
    asked: typing.ClassVar[list[str]] = []

    def do_GET(self) -> None:
        Upstream.asked.append(self.path)
        body = f"upstream {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class MirrorTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        Upstream.asked = []
        self.host = tmp / "host-cache"
        self.host.mkdir()
        port = upstream.server_address[1]
        for name, value in {
            "CACHE": tmp / "cache",
            "HOST_PACKAGES": self.host,
            "UPSTREAM": f"http://127.0.0.1:{port}",
        }.items():
            self.enterContext(mock.patch.object(rig, name, value))
        self.mirror = self.enterContext(rig.mirror())
        self.local = self.mirror.url.replace(rig.GATEWAY, "127.0.0.1")

    def get(self, path: str) -> bytes:
        with urllib.request.urlopen(self.local + path) as reply:
            data: bytes = reply.read()
            return data

    def test_serves_the_installer_without_git_or_caches(self) -> None:
        with tarfile.open(
            fileobj=io.BytesIO(self.get("/installer.tar"))
        ) as tar:
            names = tar.getnames()
        self.assertIn("Jupiter-installer/jupiter/arch/phase1.py", names)
        self.assertIn("Jupiter-installer/arch/packages/core.txt", names)
        self.assertFalse(
            [n for n in names if "/.git" in n or "__pycache__" in n]
        )

    def test_fetches_a_package_once(self) -> None:
        path = "/core/os/x86_64/linux-1-1-x86_64.pkg.tar.zst"
        for _ in range(2):
            self.assertEqual(self.get(path), f"upstream {path}".encode())
        self.assertEqual(Upstream.asked, [path])

    def test_takes_the_hosts_packages_first(self) -> None:
        (self.host / "zsh-1-1-x86_64.pkg.tar.zst").write_bytes(b"from host")
        self.assertEqual(
            self.get("/extra/os/x86_64/zsh-1-1-x86_64.pkg.tar.zst"),
            b"from host",
        )
        self.assertEqual(Upstream.asked, [])

    def test_keeps_a_database_for_the_day(self) -> None:
        for _ in range(2):
            self.get("/core/os/x86_64/core.db")
        self.assertEqual(Upstream.asked, ["/core/os/x86_64/core.db"])


class Skipping(unittest.TestCase):
    def test_names_what_is_missing(self) -> None:
        with mock.patch("shutil.which", return_value=None):
            self.assertRegex(
                rig.missing() or "", r"no qemu-system-x86_64, swtpm"
            )
        with (
            mock.patch("shutil.which", return_value="/usr/bin/x"),
            mock.patch("os.access", return_value=True),
            mock.patch.object(rig, "ISO", Path("/nonexistent.iso")),
            # The firmware there, whether or not this machine has it.
            mock.patch.object(rig, "OVMF_CODE", Path(__file__)),
        ):
            self.assertRegex(
                rig.missing() or "", r"no Arch ISO at /nonexistent"
            )
        if os.access("/dev/kvm", os.W_OK) and rig.ISO.exists():
            self.assertIsNone(rig.missing())


if __name__ == "__main__":
    unittest.main()
