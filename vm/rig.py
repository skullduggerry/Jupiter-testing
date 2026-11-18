"""A virtual machine to install Jupiter in, end to end: QEMU with KVM, OVMF
with Secure Boot (in Setup Mode on a fresh copy of its variables), swtpm for
a TPM 2.0, the Arch ISO on a serial console, and virtual disks.

    machine = Machine(folder, [Disk("system", 20)])
    machine.boot(live=True)
    machine.login("root")
    machine.sh("lsblk")

Everything a machine keeps lives in its folder: its disks, its firmware
variables, its TPM's state and a log of each boot's serial console
(`serial-<n>.log`), which is the first thing to read when a test fails. The
installer reaches the VM from a `Mirror` on the host (10.0.2.2 from inside),
which serves the working tree of Jupiter-installer as a tarball and stands in
for an Arch mirror, keeping every package it fetched for the next run.

Nothing here touches the host beyond the folders it is given and
~/.cache/jupiter-testing.
"""

from __future__ import annotations

import codecs
import contextlib
import email.utils
import fcntl
import hashlib
import http.server
import io
import json
import os
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from harness import INSTALLER

CACHE = (
    Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    / "jupiter-testing"
)
ISO = Path(os.environ.get("JUPITER_ISO") or CACHE / "archlinux-x86_64.iso")
OVMF = Path("/usr/share/edk2/x64")
OVMF_CODE = OVMF / "OVMF_CODE.secboot.4m.fd"
OVMF_VARS = OVMF / "OVMF_VARS.4m.fd"  # no keys: Setup Mode
UPSTREAM = os.environ.get("JUPITER_MIRROR", "https://geo.mirror.pkgbuild.com")
HOST_PACKAGES = Path("/var/cache/pacman/pkg")
TOOLS = {
    "qemu-system-x86_64": "qemu-system-x86",
    "swtpm": "swtpm",
    "bsdtar": "libarchive",
}
GATEWAY = "10.0.2.2"  # the host, as QEMU's user network shows it
SEARCH_BACK = 4096
ANSI = re.compile(rb"\x1b(\[[0-9;?]*[ -/]*[@-~]|[()][0-9A-Za-z]|[=>])|\r")


def missing() -> str | None:
    """Why the rig cannot run here, or None if it can."""
    tools = [name for name, _ in TOOLS.items() if not shutil.which(name)]
    if tools:
        packages = " ".join(TOOLS[name] for name in tools)
        return f"no {', '.join(tools)} (sudo pacman -S {packages})"
    if not os.access("/dev/kvm", os.R_OK | os.W_OK):
        return "no /dev/kvm to run the VM at speed"
    if not OVMF_CODE.exists():
        return f"no {OVMF_CODE} (sudo pacman -S edk2-ovmf)"
    if not ISO.exists():
        return (
            f"no Arch ISO at {ISO}: download archlinux-x86_64.iso from "
            "https://archlinux.org/download/ there, or set JUPITER_ISO"
        )
    return None


@dataclass
class Disk:
    """A virtual disk: its serial is what lsblk and /dev/disk/by-id show."""

    name: str
    gib: int
    attached: bool = True
    # Holds another system's file system from the start (foreign_disk).
    foreign: bool = False


@dataclass
class Machine:
    """One VM, its disks and its firmware and TPM state, in a folder."""

    folder: Path
    disks: list[Disk]
    tpm: bool = True
    memory: str = "4G"
    # A screen (bochs-display, a plain framebuffer) for the login screen to start on, which
    # screenshot() reads through QEMU's monitor.
    screen: bool = False
    # How long the console may say nothing before expect() gives up.
    silence: float = 300
    secure_boot_firmware: bool = True
    _qemu: subprocess.Popen[bytes] | None = None
    _swtpm: subprocess.Popen[bytes] | None = None
    _serial: socket.socket | None = None
    _sockets: Path | None = None
    _locked: io.TextIOWrapper | None = None
    _log: io.BufferedWriter | None = None
    _pending: bytes = b""
    _text: str = ""
    _decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(
            errors="replace"
        )
    )
    before: str = ""
    boots: int = 0
    _seen: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        vars_ = self.folder / "vars.fd"
        if not vars_.exists():
            shutil.copyfile(OVMF_VARS, vars_)
        for disk in self.disks:
            path = self.disk(disk.name)
            if not path.exists():
                with path.open("wb") as image:  # sparse
                    image.truncate(disk.gib * 2**30)
                if disk.foreign:
                    foreign_disk(path)
                    path.with_suffix(".sha256").write_text(digest(path))

    def disk(self, name: str) -> Path:
        """The raw image of the disk of that name, which the host can read
        byte for byte, and copy at no cost on Btrfs (`clone()`)."""
        return self.folder / f"{name}.img"

    def clone(self, folder: Path) -> Machine:
        """A copy of this powered-off machine, its disks, firmware variables
        and TPM included, sharing their blocks where the file system can."""
        shutil.copytree(
            self.folder,
            folder,
            copy_function=_reflink,
            # The install's own log (phases.log) comes along.
            ignore=shutil.ignore_patterns(
                "*.sock", "serial-*.log", "qemu.log", "swtpm.log", "lock"
            ),
        )
        disks = [
            Disk(d.name, d.gib, d.attached, d.foreign) for d in self.disks
        ]
        return Machine(
            folder,
            disks,
            tpm=self.tpm,
            memory=self.memory,
            secure_boot_firmware=self.secure_boot_firmware,
            screen=self.screen,
            silence=self.silence,
        )

    # Starting and stopping.

    def boot(self, live: bool = False, append: str = "") -> None:
        """Power on, from the ISO's kernel on the serial console if live,
        otherwise from the disks, as the firmware's boot entries say."""
        self._lock()
        self.boots += 1
        socket_path = self.sockets() / "serial.sock"
        socket_path.unlink(missing_ok=True)
        command = [
            "qemu-system-x86_64",
            "-machine",
            "q35,smm=on,accel=kvm",
            "-cpu",
            "host",
            "-smp",
            "4",
            "-m",
            self.memory,
            "-display",
            "none",
            "-nodefaults",
            # A reboot powers off: the test boots again, as it chooses.
            "-no-reboot",
            "-global",
            "driver=cfi.pflash01,property=secure,value=on",
            "-drive",
            f"if=pflash,format=raw,unit=0,readonly=on,file={self.code()}",
            "-drive",
            f"if=pflash,format=raw,unit=1,file={self.folder / 'vars.fd'}",
            "-serial",
            f"unix:{socket_path},server=on,wait=on",
            "-nic",
            "user,model=virtio-net-pci",
            "-device",
            "virtio-rng-pci",
        ]
        if self.screen:
            monitor = self.sockets() / "qmp.sock"
            command += [
                "-device",
                "bochs-display",
                "-qmp",
                f"unix:{monitor},server=on,wait=off",
            ]
        for index, disk in enumerate(d for d in self.disks if d.attached):
            command += [
                "-drive",
                f"if=none,id=d{index},file={self.disk(disk.name)},"
                "format=raw,discard=unmap,cache=unsafe",
                "-device",
                f"virtio-blk-pci,drive=d{index},serial={disk.name},"
                f"bootindex={index + 1}",
            ]
        if live:
            kernel, initrd, options = live_boot_files(self.folder)
            command += [
                "-drive",
                f"if=none,id=iso,file={ISO},format=raw,readonly=on,media=cdrom",
                "-device",
                "ide-cd,drive=iso",
                "-kernel",
                str(kernel),
                "-initrd",
                str(initrd),
                "-append",
                f"{options} console=ttyS0,115200 {append}".strip(),
            ]
        if self.tpm:
            command += self._start_swtpm()
        with (self.folder / "qemu.log").open("ab") as log:
            self._qemu = subprocess.Popen(
                [*WITH_PARENT, *command],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 30
        while True:
            connection = socket.socket(socket.AF_UNIX)
            try:
                connection.connect(str(socket_path))
                break
            except OSError:
                connection.close()
            if self._qemu.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(
                    f"QEMU did not start: {self.folder / 'qemu.log'}"
                )
            time.sleep(0.1)
        self._serial = connection
        self._pending = b""
        self._text = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._log = open(self.folder / f"serial-{self.boots}.log", "wb")  # noqa: SIM115

    def _lock(self) -> None:
        """The machine's folder for this process alone, while it lives: a
        second run on the same disks refuses, naming who holds them."""
        if self._locked is not None:
            return
        lock = (self.folder / "lock").open("a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.seek(0)
            holder = lock.read().strip()
            lock.close()
            raise RuntimeError(
                f"{self.folder} is in use by process {holder}: stop it first"
            ) from None
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        self._locked = lock

    def remove(self) -> None:
        """Delete the machine's folder, refusing while a run holds it: its
        lock file, deleted, would let the next run lock a new one beside a
        VM still using the old disks."""
        if self.folder.exists():
            self._lock()
        shutil.rmtree(self.folder, ignore_errors=True)
        self.kill()

    def sockets(self) -> Path:
        """A short folder for the machine's sockets: a Unix socket's path
        must stay under 108 bytes, and the machine's folder may be long."""
        if self._sockets is None:
            self._sockets = Path(tempfile.mkdtemp(prefix="jvm-", dir="/tmp"))
        return self._sockets

    def code(self) -> Path:
        """The firmware: with Secure Boot, or OVMF without it."""
        return (
            OVMF_CODE
            if self.secure_boot_firmware
            else OVMF / "OVMF_CODE.4m.fd"
        )

    def _start_swtpm(self) -> list[str]:
        state = self.folder / "tpm"
        state.mkdir(exist_ok=True)
        control = self.sockets() / "tpm.sock"
        control.unlink(missing_ok=True)
        log = (self.folder / "swtpm.log").open("ab")
        self._swtpm = subprocess.Popen(
            [
                *WITH_PARENT,
                "swtpm",
                "socket",
                "--tpm2",
                "--tpmstate",
                f"dir={state}",
                "--ctrl",
                f"type=unixio,path={control}",
                "--terminate",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()
        deadline = time.monotonic() + 10
        while not control.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("swtpm did not start")
            time.sleep(0.05)
        return [
            "-chardev",
            f"socket,id=tpm,path={control}",
            "-tpmdev",
            "emulator,id=tpm0,chardev=tpm",
            "-device",
            "tpm-tis,tpmdev=tpm0",
        ]

    def wait_off(self, timeout: float = 120) -> None:
        """Wait for the VM to power itself off."""
        assert self._qemu
        deadline = time.monotonic() + timeout
        while self._qemu.poll() is None:
            self._read(min(1.0, max(0.0, deadline - time.monotonic())))
            if time.monotonic() > deadline:
                raise TimeoutError("the VM did not power off")
        self._close()

    def kill(self) -> None:
        """Pull the plug, and let another run have the disks."""
        if self._qemu and self._qemu.poll() is None:
            self._qemu.kill()
            self._qemu.wait()
        self._close()
        if self._locked is not None:
            self._locked.close()
            self._locked = None

    def _close(self) -> None:
        if self._sockets is not None:
            shutil.rmtree(self._sockets, ignore_errors=True)
            self._sockets = None
        if self._serial:
            self._serial.close()
            self._serial = None
        if self._log:
            self._log.close()
            self._log = None
        if self._swtpm:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._swtpm.wait(5)
            if self._swtpm.poll() is None:
                self._swtpm.kill()
                self._swtpm.wait()
            self._swtpm = None

    def power_off(self) -> None:
        """Shut the running system down cleanly."""
        self.send("systemctl poweroff\n")
        self.wait_off()

    # The serial console.

    def _read(self, timeout: float) -> bool:
        assert self._serial
        self._serial.settimeout(max(timeout, 0.01))
        try:
            data = self._serial.recv(65536)
        except TimeoutError:
            return True
        except OSError:
            return False
        if not data:
            return False
        assert self._log
        self._log.write(data)
        self._log.flush()
        data = self._pending + data
        # An escape sequence cut in two waits for its end.
        cut = data.rfind(b"\x1b")
        if cut >= 0 and len(data) - cut < 16 and not ANSI.match(data, cut):
            data, self._pending = data[:cut], data[cut:]
        else:
            self._pending = b""
        # A character cut between two reads waits for its other bytes.
        self._text += self._decoder.decode(ANSI.sub(b"", data))
        return True

    def expect(self, pattern: str, timeout: float = 60) -> re.Match[str]:
        """Wait for the console to print text matching pattern (escape
        sequences and carriage returns left out), and consume what it
        printed up to the match's end; what came before the match is
        `before`. Only new text is searched (and the last SEARCH_BACK
        characters before it), so a pattern matches SEARCH_BACK characters
        at most: one that spans more, such as (.*?)... over a long output,
        would search the whole output again on every read."""
        regex = re.compile(pattern)
        deadline = time.monotonic() + timeout
        start = 0
        heard = time.monotonic()
        size = len(self._text)
        while True:
            found = regex.search(self._text, start)
            if found:
                self.before = self._text[: found.start()]
                self._text = self._text[found.end() :]
                return found
            start = max(0, len(self._text) - SEARCH_BACK)
            now = time.monotonic()
            if len(self._text) != size:
                heard, size = now, len(self._text)
            left = deadline - now
            # A console silent for SILENCE is stuck, whatever the timeout:
            # say so now, with what it last showed.
            silent = now - heard > self.silence
            if left <= 0 or silent or not self._read(min(left, 1.0)):
                why = (
                    f"silent for {self.silence:.0f} s"
                    if silent
                    else "timed out"
                )
                raise TimeoutError(
                    f"{why}; the console never showed {pattern!r}; it last "
                    f"showed:\n{self._text[-2000:]}"
                )

    def send(self, text: str) -> None:
        """Type text on the console."""
        assert self._serial
        self._serial.sendall(text.encode())

    def answer_secret(self, text: str) -> None:
        """Answer a password prompt that just showed: a moment later, since
        the program asking turns echo off after printing it, flushing what
        was typed meanwhile (TCSAFLUSH)."""
        time.sleep(0.5)
        self.send(f"{text}\n")

    def login(
        self, user: str, password: str = "", timeout: float = 300
    ) -> None:
        """Log in at the serial console and get a plain bash, no echo."""
        self.expect(r"login: $", timeout)
        self.send(f"{user}\n")
        if password:
            self.expect(r"Password: $")
            self.send(f"{password}\n")
        # zsh on the ISO, bash on the system: either takes these, once its
        # prompt is up, which is when it answers. The typed line says
        # $((n+1)), the answer the number: only the answer matches.
        self.expect(r"[#$] $", timeout)
        self.send(
            "stty -echo cols 250; exec env PS1= TERM=dumb "
            "bash --noprofile --norc --noediting\n"
        )
        for attempt in range(30):
            self.send(f"echo :sync:$(({attempt} + 1000)):\n")
            with contextlib.suppress(TimeoutError):
                self.expect(f":sync:{attempt + 1000}:\n", 2)
                break
        else:
            raise TimeoutError("no shell answered on the console")

    def sh(
        self, command: str, timeout: float = 120, check: bool = True
    ) -> str:
        """Run a shell command, return what it printed; raise on a failure
        if check."""
        token = f"{time.monotonic_ns():x}"
        self.send(
            f"echo :{token}:start; {{ {command}\n}} 2>&1; "
            f"echo :{token}:$?:end\n"
        )
        self.expect(f":{token}:start\n", 30)
        done = self.expect(rf":{token}:(\d+):end\n", timeout)
        output, status = self.before, int(done.group(1))
        if check and status:
            raise AssertionError(
                f"{command!r} failed with {status}:\n{output}"
            )
        return output

    def screenshot(self, path: Path) -> None:
        """What the screen shows now, as a PPM image (needs screen)."""
        connection = socket.socket(socket.AF_UNIX)
        connection.connect(str(self.sockets() / "qmp.sock"))
        with connection, connection.makefile("rw") as qmp:
            qmp.readline()  # the greeting
            for command in (
                {"execute": "qmp_capabilities"},
                {
                    "execute": "screendump",
                    "arguments": {"filename": str(path)},
                },
            ):
                qmp.write(json.dumps(command) + "\n")
                qmp.flush()
                while True:
                    reply = json.loads(qmp.readline())
                    if "return" in reply or "error" in reply:
                        break
            if "error" in reply:
                raise RuntimeError(f"screendump: {reply['error']}")

    def console(self) -> str:
        """What the console showed this boot so far, escapes left out."""
        raw = (self.folder / f"serial-{self.boots}.log").read_bytes()
        return ANSI.sub(b"", raw).decode(errors="replace")

    def type_passphrase(self, passphrase: str, timeout: float = 180) -> str:
        """Answer the initramfs's passphrase prompt; returns the prompt."""
        # "passphrase for disk root", or once there is a recovery key,
        # "passphrase or recovery key for disk root".
        prompt = self.expect(r"[Pp]assphrase[^\n]*? for [^\n]*?: ?", timeout)
        self.answer_secret(passphrase)
        return prompt.group(0)

    def answer(self, dialogue: list[tuple[str, str]], timeout: float) -> None:
        """Answer the prompts in order: (pattern, answer) each."""
        for pattern, reply in dialogue:
            self.expect(pattern, timeout)
            self.send(f"{reply}\n")
            self._seen.append(pattern)


def foreign_disk(image: Path) -> None:
    """Make a disk image hold another system's file system, as Windows'
    disk does on a desktop that dual-boots: GPT, one partition, ext4 with a
    file in it. Built on the host without root."""
    content = image.with_suffix(".content")
    content.mkdir(exist_ok=True)
    (content / "kept.txt").write_text("another system's file\n")
    subprocess.run(
        ["sfdisk", "--quiet", image],
        input="label: gpt\nstart=2048, type=linux\n",
        text=True,
        check=True,
        capture_output=True,
    )
    table = json.loads(
        subprocess.run(
            ["sfdisk", "--json", image], capture_output=True, check=True
        ).stdout
    )["partitiontable"]["partitions"][0]
    partition = image.with_suffix(".part")
    with partition.open("wb") as file:
        file.truncate(table["size"] * 512)
    subprocess.run(
        ["mkfs.ext4", "-q", "-L", "other", "-d", content, partition],
        check=True,
    )
    with image.open("r+b") as disk, partition.open("rb") as source:
        disk.seek(table["start"] * 512)
        shutil.copyfileobj(source, disk)
    partition.unlink()
    shutil.rmtree(content)


def digest(path: Path) -> str:
    """A disk image's SHA-256, to compare byte for byte."""
    sha = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(2**20):
            sha.update(block)
    return sha.hexdigest()


# Before QEMU's and swtpm's command: they die with the process that started
# them, however it ends, so no VM outlives its run.
WITH_PARENT = ["setpriv", "--pdeathsig", "KILL", "--"]


def _reflink(source: str, target: str) -> None:
    subprocess.run(["cp", "--reflink=auto", source, target], check=True)


def live_boot_files(folder: Path) -> tuple[Path, Path, str]:
    """The ISO's kernel, initramfs and command line, extracted once per
    ISO: a new one (by size and time) has its own, whose archisosearchuuid
    matches it."""
    stat = ISO.stat()
    target = folder.parent / f"iso-{stat.st_size}-{int(stat.st_mtime)}"
    kernel = target / "arch/boot/x86_64/vmlinuz-linux"
    initrd = target / "arch/boot/x86_64/initramfs-linux.img"
    entry = target / "loader/entries/01-archiso-linux.conf"
    if not kernel.exists():
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "bsdtar",
                "-xf",
                ISO,
                "-C",
                target,
                "arch/boot/x86_64",
                "loader/entries",
            ],
            check=True,
        )
    entries = sorted((target / "loader/entries").glob("*.conf"))
    entry = entries[0]
    options = next(
        line.split(None, 1)[1]
        for line in entry.read_text().splitlines()
        if line.startswith("options")
    )
    return kernel, initrd, options.strip()


class Mirror:
    """The installer's working tree and an Arch mirror, on the host.

    /installer.tar is Jupiter-installer as it is on disk, without .git and
    caches. /<repo>/os/x86_64/<file> is a mirror: the databases are fetched
    once per day from UPSTREAM, the packages from the host's own cache when
    it has them, and otherwise fetched once and kept in
    ~/.cache/jupiter-testing/packages for the next run.
    """

    def __init__(self, revision: str | None = None) -> None:
        self.revision = revision
        self.packages = CACHE / "packages"
        self.packages.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.locks: dict[Path, threading.Lock] = {}
        handler = self._handler()
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), handler
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}
        )
        self.thread.daemon = True
        self.thread.start()

    @property
    def url(self) -> str:
        """The mirror's address as the VM sees it."""
        return f"http://{GATEWAY}:{self.server.server_address[1]}"

    def close(self) -> None:
        """Stop serving."""
        self.server.shutdown()
        self.server.server_close()

    def installer(self) -> bytes:
        """Jupiter-installer's working tree as a tarball, or the revision's
        tree."""
        if self.revision:
            return subprocess.run(
                [
                    "git",
                    "-C",
                    INSTALLER,
                    "archive",
                    "--format=tar",
                    "--prefix=Jupiter-installer/",
                    self.revision,
                ],
                capture_output=True,
                check=True,
            ).stdout
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as tar:
            for path in sorted(INSTALLER.rglob("*")):
                relative = path.relative_to(INSTALLER)
                if relative.parts[0].startswith(".") or any(
                    part == "__pycache__" for part in relative.parts
                ):
                    continue
                if path.is_file():
                    tar.add(path, arcname=f"Jupiter-installer/{relative}")
        return data.getvalue()

    def cached(self, path: str) -> Path:
        """Where the file a mirror has at path is kept: a database for the
        day, a package for good."""
        name = path.rsplit("/", 1)[-1]
        if name.endswith((".db", ".db.sig", ".files", ".files.sig")):
            day = time.strftime("%Y%m%d")
            return (
                self.packages / "db" / day / path.strip("/").replace("/", "_")
            )
        host = HOST_PACKAGES / name
        if os.access(host, os.R_OK) and not (self.packages / name).exists():
            return host
        return self.packages / name

    def note(self, line: str) -> None:
        """A line in ~/.cache/jupiter-testing/mirror.log."""
        with self.lock, (CACHE / "mirror.log").open("a") as log:
            log.write(f"{time.strftime('%H:%M:%S')} {line}\n")

    def lock_for(self, path: Path) -> threading.Lock:
        """One download of a file at a time; another asking waits."""
        with self.lock:
            return self.locks.setdefault(path, threading.Lock())

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        mirror = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/installer.tar":
                    self._send(mirror.installer())
                    return
                cached = mirror.cached(self.path)
                start = time.monotonic()
                with mirror.lock_for(cached):
                    waited = time.monotonic() - start
                    if cached.exists():
                        self._file(cached)
                    else:
                        self._fetch(cached)
                mirror.note(
                    f"{self.path} from {cached} waited {waited:.1f}s, "
                    f"took {time.monotonic() - start:.1f}s, "
                    f"range {self.headers.get('Range')}"
                )

            def _file(self, found: Path) -> None:
                self.send_response(200)
                self.send_header("Content-Length", str(found.stat().st_size))
                self.send_header(
                    "Last-Modified",
                    email.utils.formatdate(found.stat().st_mtime, usegmt=True),
                )
                self.end_headers()
                with found.open("rb") as file:
                    shutil.copyfileobj(file, self.wfile)

            def _fetch(self, cached: Path) -> None:
                """From upstream, to pacman and the cache at once: pacman
                gives up on a download that sends nothing for a while."""
                try:
                    reply = urllib.request.urlopen(
                        UPSTREAM + self.path, timeout=60
                    )
                except OSError:
                    self.send_error(404)
                    return
                cached.parent.mkdir(parents=True, exist_ok=True)
                partial = cached.with_name(cached.name + ".part")
                with reply, partial.open("wb") as file:
                    self.send_response(200)
                    length = reply.headers.get("Content-Length")
                    if length:
                        self.send_header("Content-Length", length)
                    self.end_headers()
                    while chunk := reply.read(2**16):
                        file.write(chunk)
                        self.wfile.write(chunk)
                partial.rename(cached)

            def _send(self, data: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: object) -> None:
                pass

            def handle(self) -> None:
                # pacman gives up on a download now and then and tries again:
                # its end of the socket going away is no error of the mirror's.
                with contextlib.suppress(
                    BrokenPipeError, ConnectionResetError
                ):
                    super().handle()

        return Handler


@contextlib.contextmanager
def mirror(revision: str | None = None) -> Iterator[Mirror]:
    """A mirror for as long as the block runs, serving the installer as it
    is, or at a git revision."""
    server = Mirror(revision)
    try:
        yield server
    finally:
        server.close()


def prepare_live(machine: Machine, server: Mirror) -> None:
    """On the ISO, logged in: the mirror for pacman and the installer in
    /root/Jupiter-installer."""
    # reflector rewrites the mirror list once the network is up, whenever
    # that is; pacman-init fills the keyring.
    machine.sh("systemctl mask --now reflector.service", check=False)
    machine.sh(
        "until systemctl is-active -q pacman-init.service; do sleep 1; done",
        timeout=300,
    )
    use_mirror(machine, server)
    machine.sh(
        f"curl -fsS {server.url}/installer.tar | tar -x -C /root",
        timeout=60,
    )


def use_mirror(machine: Machine, server: Mirror) -> None:
    """pacman fetches from the mirror on the host, nowhere else."""
    machine.sh(
        f"echo 'Server = {server.url}/$repo/os/$arch' "
        "> /etc/pacman.d/mirrorlist"
    )
