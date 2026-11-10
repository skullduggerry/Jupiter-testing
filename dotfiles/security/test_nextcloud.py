"""The Nextcloud account: where the app password may go, and where not.

services/nextcloud-login.py gets an app password through Login Flow v2 and
hands it to the keyring; services/nextcloud-calendar.py reads it back and
sends it as HTTP Basic auth on every CalDAV request. The password is to
reach the configured server only, and only over https or loopback: never
another host, never plain http, not through a redirect or an href the
server answers with, and never argv, stdout or the shell's log.

Both run end to end against the stand-in Nextcloud (harness/nextcloud.py)
on 127.0.0.1, which the helpers take as loopback. A second server at
127.0.0.1 is another origin, and one at 127.0.0.2 (loopback too, which the
helpers do not know) stands for a plain http host elsewhere: what reaches
either is recorded, and must be nothing.
"""

from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ElementTree
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

from harness import QUICKSHELL, SECRET, executable, load, temporary
from harness.nextcloud import (
    PASSWORD,
    USER,
    Elsewhere,
    Nextcloud,
    auth,
    collection,
    ics,
    todo,
)

CALENDAR = QUICKSHELL / "services/nextcloud-calendar.py"
LOGIN = QUICKSHELL / "services/nextcloud-login.py"
calendar = load(CALENDAR)
login = load(LOGIN)
# Runs a script as __main__ with time.sleep a no-op: the login helper waits
# POLL_SECONDS before each poll, which the stand-in answers at once
# (Login.test_polling covers the waiting itself).
WITHOUT_WAITS = (
    "import runpy, sys, time; time.sleep = lambda _: None; "
    "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
)

COLLECTIONS: dict[str, dict[str, Any]] = {
    "tasks/": {
        "name": "Tasks",
        "colour": "#f0a000",
        "components": ["VTODO"],
        "objects": [ics(todo("UID:plants", "SUMMARY:Water the plants"))],
    },
}
# Records how it was called and what came on stdin, and answers a lookup
# with the stand-in password.
SECRET_TOOL = f"""#!{sys.executable}
import json, os, sys
given = sys.stdin.read() if sys.argv[1] == "store" else ""
with open(os.environ["SECRET_CALLS"], "a") as calls:
    calls.write(json.dumps([sys.argv[1:], given]) + "\\n")
if sys.argv[1] == "lookup":
    print(os.environ["SECRET_ANSWER"], end="")
"""


class Transport(unittest.TestCase):
    """Which addresses count as https or loopback: the same rule in both."""

    SECURE = (
        "https://cloud.example.org",
        "https://cloud.example.org:8443/nextcloud",
        "HTTPS://cloud.example.org",
        "http://localhost:8080",
        "http://127.0.0.1",
        "http://[::1]:8080/",
    )
    INSECURE = (
        "http://cloud.example.org",
        "cloud.example.org",
        "ftp://cloud.example.org",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost.example.org",
        "http://127.0.0.1.example.org",
        "http://127.0.0.2",
        # What comes before an @ is a user name: these are example.org.
        "http://localhost:x@example.org",
        "http://127.0.0.1@example.org/",
        "http://localhost:8080@example.org:8080",
        # No address at all, which urllib raises over: refused, not raised.
        "https://[",
        "https://cloud.example.org:port",
        "https://",
        "https:///remote.php/dav",
    )

    def test_https_or_loopback(self) -> None:
        for helper in (calendar, login):
            for url in self.SECURE:
                with self.subTest(helper=helper.__name__, url=url):
                    self.assertTrue(helper.is_secure(url))
            for url in self.INSECURE:
                with self.subTest(helper=helper.__name__, url=url):
                    self.assertFalse(helper.is_secure(url))

    def test_origins(self) -> None:
        same = [
            ("https://cloud.example.org", "https://cloud.example.org:443/x"),
            ("http://127.0.0.1:80/a", "http://127.0.0.1/b"),
            ("https://Cloud.Example.org/", "https://cloud.example.org/"),
        ]
        other = [
            ("https://cloud.example.org", "http://cloud.example.org"),
            ("https://cloud.example.org", "https://cloud.example.org:8443"),
            ("https://cloud.example.org", "https://evil.example"),
            ("https://cloud.example.org", "https://cloud.example.org.evil"),
        ]
        for one, two in same:
            self.assertEqual(calendar.origin(one), calendar.origin(two))
        for one, two in other:
            self.assertNotEqual(calendar.origin(one), calendar.origin(two))


class Calendar(unittest.TestCase):
    """nextcloud-calendar.py: the app password goes to the configured server
    only, the tasks it marks done are only that server's, and what it reads
    cannot make it read anything else."""

    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.server = self.enterContext(Nextcloud(copy.deepcopy(COLLECTIONS)))
        self.other = self.enterContext(Elsewhere())
        self.plain = self.enterContext(Elsewhere("127.0.0.2"))
        self.secret_calls = self.tmp / "secret-calls"
        executable(self.tmp / "bin/secret-tool", SECRET_TOOL)

    def tearDown(self) -> None:
        for elsewhere in (self.other, self.plain):
            self.assertEqual(elsewhere.asked, [], "the other server was asked")

    def helper(
        self,
        *arguments: str,
        server: str = "",
        password: str | None = PASSWORD,
    ) -> dict[str, Any]:
        env = {
            "PATH": f"{self.tmp / 'bin'}:/usr/bin",
            "NEXTCLOUD_URL": server or self.server.url,
            "NEXTCLOUD_USER": USER,
            "SECRET_CALLS": str(self.secret_calls),
            "SECRET_ANSWER": PASSWORD,
            "TZ": "UTC",
        }
        if password is not None:
            env["NEXTCLOUD_APP_PASSWORD"] = password
        result = subprocess.run(
            [
                sys.executable,
                str(CALENDAR),
                *(
                    arguments
                    or ("--start", "2026-01-01", "--end", "2026-02-01")
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=helper_env(env),
            check=False,
        )
        for secret in (PASSWORD, SECRET, auth()):
            self.assertNotIn(secret, result.stdout + result.stderr)
        payload: dict[str, Any] = json.loads(result.stdout)
        return payload

    def test_only_the_server_gets_the_password(self) -> None:
        payload = self.helper()
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(
            [task["summary"] for task in payload["tasks"]],
            ["Water the plants"],
        )
        self.assertEqual(
            {asked.authorization for asked in self.server.asked}, {auth()}
        )

    def test_plain_http_elsewhere_is_never_asked(self) -> None:
        payload = self.helper(server=self.plain.origin)
        self.assertEqual(payload["status"], "unconfigured")
        self.assertIn("must be https://", payload["message"])

    def test_the_password_from_the_keyring_is_not_in_argv(self) -> None:
        payload = self.helper(password=None)
        self.assertEqual(payload["status"], "ok", payload)
        [(argv, _)] = [
            json.loads(line)
            for line in self.secret_calls.read_text().splitlines()
        ]
        # Asked for by server and user: one server's password never goes to
        # another that has a user of the same name.
        self.assertEqual(
            argv,
            [
                "lookup",
                "service",
                "nextcloud",
                "server",
                self.server.url,
                "username",
                USER,
            ],
        )

    def test_a_wrong_password_is_not_shown_back(self) -> None:
        payload = self.helper(password=SECRET)
        self.assertEqual(payload["status"], "error")
        self.assertIn("wrong user or app password", payload["message"])

    def test_a_calendar_elsewhere_is_not_read(self) -> None:
        # A server's listing naming collections on other servers: each costs
        # only itself, and none of them is asked.
        for elsewhere, name in ((self.other, "Other"), (self.plain, "Plain")):
            self.server.listed.append(
                collection(
                    f"{elsewhere.origin}/remote.php/dav/calendars/{USER}/x/",
                    name,
                    "",
                    ["VEVENT", "VTODO"],
                )
            )
        self.server.listed.append(
            collection(
                f"//127.0.0.2:{self.plain.server_address[1]}/cal/",
                "Schemeless",
                "",
                ["VTODO"],
            )
        )
        payload = self.helper()
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(
            payload["message"], "could not read Other, Plain, Schemeless"
        )
        self.assertEqual(len(payload["tasks"]), 1)

    def test_a_redirect_elsewhere_is_not_followed(self) -> None:
        # urllib keeps Authorization on a redirect it follows: a GET that
        # went to another server would hand it the password.
        href = self.server.home + "tasks/0.ics"
        for elsewhere in (self.other, self.plain):
            self.server.redirects[href] = elsewhere.origin + "/steal.ics"
            payload = self.helper("--complete", href)
            self.assertEqual(payload["status"], "error")
            self.assertIn("redirected to another server", payload["message"])
        self.assertEqual(self.server.puts, [])

    def test_a_subpath_install(self) -> None:
        # hrefs come back as the server's own paths, /nextcloud/remote.php/…,
        # and are not appended to the configured address a second time.
        server = self.enterContext(
            Nextcloud(copy.deepcopy(COLLECTIONS), prefix="/nextcloud")
        )
        payload = self.helper(server=server.url)
        self.assertEqual(payload["status"], "ok", payload)
        [task] = payload["tasks"]
        self.assertEqual(task["href"], server.home + "tasks/0.ics")
        done = self.helper("--complete", task["href"], server=server.url)
        self.assertEqual(done["status"], "ok", done)
        self.assertEqual(server.puts[0][0], task["href"])

    def test_only_a_task_on_the_server_is_marked_done(self) -> None:
        home = self.server.home
        refused = [
            f"{self.other.origin}{home}tasks/0.ics",
            f"//127.0.0.2:{self.plain.server_address[1]}{home}tasks/0.ics",
            f"{home}../../../../index.php/a.ics",
            f"{home}%2e%2e/%2E%2E/files/{USER}/a.ics",
            f"{home}tasks%2F..%2F..%2F..%2Ffiles/{USER}/a.ics",
            f"{home}./tasks/0.ics",
            f"{home}tasks\\..\\0.ics",
            f"{home}tasks/0.ics?export",
            f"{home}tasks/0.ics#x",
            f"{home}tasks/0",
            f"/remote.php/dav/files/{USER}/notes.ics",
            "/index.php/apps/tasks/a.ics",
            "remote.php/dav/calendars/tester/tasks/0.ics",
            f"/x{home}tasks/0.ics",
        ]
        for href in refused:
            with self.subTest(href=href):
                before = len(self.server.asked)
                payload = self.helper("--complete", href)
                self.assertEqual(payload["status"], "error")
                self.assertIn("not a task's address", payload["message"])
                self.assertEqual(len(self.server.asked), before)
        base = "https://cloud.example.org/nextcloud"
        self.assertEqual(
            calendar.task_url(
                base, f"/nextcloud{home}personal%20list/a%20b.ics"
            ),
            f"https://cloud.example.org/nextcloud{home}personal%20list/a%20b.ics",
        )

    def test_a_principal_cannot_step_out(self) -> None:
        for principal in ("..", "%2e%2e", "."):
            self.server.principal = (
                f"/remote.php/dav/principals/users/{principal}/"
            )
            payload = self.helper()
            self.assertEqual(payload["status"], "ok", payload)
        paths = {asked.path for asked in self.server.asked}
        self.assertFalse(
            [path for path in paths if ".." in path or "%2e" in path]
        )

    def test_entities_are_not_expanded(self) -> None:
        # A billion laughs, and an entity that names a file: expat refuses
        # both, and the helper says the answer was malformed.
        laughs = (
            '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
            + "".join(
                f'<!ENTITY {chr(98 + n)} "{("&" + chr(97 + n) + ";") * 10}">'
                for n in range(8)
            )
            + ']><d:multistatus xmlns:d="DAV:">&i;</d:multistatus>'
        )
        hostname = Path("/etc/hostname")
        external = (
            '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM '
            f'"file://{hostname}">]><d:multistatus xmlns:d="DAV:">'
            "<d:response><d:href>&x;</d:href></d:response></d:multistatus>"
        )
        for document in (laughs, external):
            self.server.canned["/remote.php/dav/"] = (207, document)
            payload = self.helper()
            self.assertEqual(payload["status"], "error")
            self.assertIn("malformed CalDAV response", payload["message"])
            if hostname.exists() and hostname.read_text().strip():
                self.assertNotIn(
                    hostname.read_text().strip(), payload["message"]
                )

    def test_a_colour_is_only_a_colour(self) -> None:
        # It is pasted into QML as a colour; anything but hex is dropped.
        for value, wanted in (
            ("#3A87ADFF", "#3a87ad"),
            ("#abc", "#aabbcc"),
            ("red", ""),
            ("#12345", ""),
            ('#000000"; color: "#fff', ""),
            ("#gggggg", ""),
        ):
            self.assertEqual(calendar.normalise_colour(value), wanted, value)


def helper_env(env: dict[str, str]) -> dict[str, str]:
    """What a helper runs with: these, coverage's own variables, which
    measure it, and no session bus, so no keyring but the stand-in's."""
    kept = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("COVERAGE_", "JUPITER_", "PYTHON"))
    }
    return kept | {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent"} | env


class Login(unittest.TestCase):
    """nextcloud-login.py: the browser is sent to https only, the app
    password comes back over https only, and goes to the keyring on stdin."""

    def setUp(self) -> None:
        self.tmp = temporary(self)
        self.server = self.enterContext(Nextcloud({}))
        self.plain = self.enterContext(Elsewhere("127.0.0.2"))
        self.server.pending_polls = 0
        self.secret_calls = self.tmp / "secret-calls"
        executable(self.tmp / "bin/secret-tool", SECRET_TOOL)

    def tearDown(self) -> None:
        self.assertEqual(self.plain.asked, [], "plain http was asked")

    def sign_in(
        self, url: str = "", path: str = ""
    ) -> tuple[list[dict[str, Any]], str]:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                WITHOUT_WAITS,
                str(LOGIN),
                "--url",
                url or self.server.url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=helper_env(
                {
                    "PATH": path or f"{self.tmp / 'bin'}:/usr/bin",
                    "SECRET_CALLS": str(self.secret_calls),
                    "SECRET_ANSWER": "",
                }
            ),
            check=False,
        )
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        return lines, result.stderr

    def stored(self) -> list[Any]:
        if not self.secret_calls.exists():
            return []
        return [
            json.loads(line)
            for line in self.secret_calls.read_text().splitlines()
        ]

    def test_the_password_goes_to_the_keyring_on_stdin(self) -> None:
        lines, _ = self.sign_in()
        self.assertEqual(
            lines,
            [
                {
                    "status": "open",
                    "url": self.server.url + "/login/v2/flow/flow-token",
                },
                {"status": "ok", "server": self.server.url, "loginName": USER},
            ],
        )
        [(argv, given)] = self.stored()
        self.assertEqual(
            argv,
            [
                "store",
                "--label=Nextcloud",
                "service",
                "nextcloud",
                "server",
                self.server.url,
                "username",
                USER,
            ],
        )
        self.assertEqual(given, PASSWORD)

    def test_plain_http_is_refused_before_asking(self) -> None:
        lines, _ = self.sign_in(self.plain.origin)
        self.assertEqual(
            lines,
            [
                {
                    "status": "error",
                    "message": "the server address must be https://",
                }
            ],
        )

    def test_the_server_cannot_send_the_browser_or_the_poll_elsewhere(
        self,
    ) -> None:
        plain = self.plain.origin
        replies: list[dict[str, Any]] = [
            {
                "login": f"{plain}/login/v2/flow/x",
                "poll": {"endpoint": self.server.url + "/login/v2/poll"},
            },
            {
                "login": "file:///etc/passwd",
                "poll": {"endpoint": self.server.url + "/login/v2/poll"},
            },
            {
                "login": self.server.url + "/login/v2/flow/x",
                "poll": {"endpoint": f"{plain}/login/v2/poll"},
            },
        ]
        for reply in replies:
            reply["poll"]["token"] = "poll-token"
            self.server.login_reply = reply
            lines, _ = self.sign_in()
            self.assertEqual(
                lines,
                [
                    {
                        "status": "error",
                        "message": "the server answered with an address that is not https://",
                    }
                ],
                "the browser is not opened",
            )
        self.assertEqual(self.stored(), [])

    def test_no_redirect_to_plain_http(self) -> None:
        # The poll's answer carries the app password; urllib follows a
        # POST's 302 as a GET, so the answer would come back in the clear.
        for path in ("/index.php/login/v2", "/login/v2/poll"):
            self.server.redirects = {path: f"{self.plain.origin}{path}"}
            lines, _ = self.sign_in()
            self.assertEqual(lines[-1]["status"], "error", path)
            self.assertIn("HTTP 302", lines[-1]["message"])
        self.assertEqual(self.stored(), [])

    def test_polling(self) -> None:
        # In process, without its two seconds between polls.
        self.enterContext(mock.patch.object(login, "POLL_SECONDS", 0))
        stored: list[tuple[str, ...]] = []
        self.enterContext(
            mock.patch.object(
                login, "store", lambda *values: stored.append(values)
            )
        )
        self.server.pending_polls = 3
        with redirect_stdout(io.StringIO()):
            self.assertEqual(login.sign_in(self.server.url), USER)
        self.assertEqual(stored, [(self.server.url, USER, PASSWORD)])
        polls = [a for a in self.server.asked if a.path == "/login/v2/poll"]
        self.assertEqual(len(polls), 4)
        self.assertEqual({poll.body for poll in polls}, {"token=poll-token"})

        self.enterContext(mock.patch.object(login, "GIVE_UP_SECONDS", 0.2))
        self.server.pending_polls = 10**6
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(login.Failed, "timed out"),
        ):
            login.sign_in(self.server.url)

        self.server.canned["/login/v2/poll"] = (500, "")
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(login.Failed, "poll: HTTP 500"),
        ):
            login.sign_in(self.server.url)

        self.server.canned["/login/v2/poll"] = (200, '{"loginName": 1}')
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(login.Failed, "unexpected reply"),
        ):
            login.sign_in(self.server.url)

        # A name or a password that is no text is no login: secret-tool
        # would be started with it.
        for reply in (
            '{"loginName": 1, "appPassword": "x"}',
            '{"loginName": "a", "appPassword": ["x"]}',
            '{"loginName": null, "appPassword": null}',
        ):
            self.server.canned["/login/v2/poll"] = (200, reply)
            with (
                self.subTest(reply=reply),
                redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(login.Failed, "unexpected reply"),
            ):
                login.sign_in(self.server.url)
        self.assertEqual(len(stored), 1, "nothing more reached the keyring")

    def test_without_a_keyring(self) -> None:
        (self.tmp / "bin/secret-tool").unlink()
        lines, _ = self.sign_in(path=str(self.tmp / "bin"))
        self.assertEqual(lines[-1]["status"], "error")
        self.assertIn("secret-tool is not installed", lines[-1]["message"])

        executable(
            self.tmp / "bin/secret-tool",
            "#!/bin/sh\necho locked >&2\nexit 1\n",
        )
        lines, _ = self.sign_in()
        self.assertEqual(
            lines[-1]["message"], "could not save to the keyring: locked"
        )


class Discovery(unittest.TestCase):
    """The principal's id, which the calendar home is built from."""

    def test_an_id_that_steps_out_is_none(self) -> None:
        def document(href: str) -> ElementTree.Element:
            return ElementTree.fromstring(
                '<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>'
                f"<d:current-user-principal><d:href>{href}</d:href>"
                "</d:current-user-principal></d:prop></d:propstat></d:response>"
                "</d:multistatus>"
            )

        for href, wanted in (
            ("/remote.php/dav/principals/users/a1b2/", "a1b2"),
            ("/remote.php/dav/principals/users/../", ""),
            ("/remote.php/dav/principals/users/%2E%2E", ""),
            ("/remote.php/dav/principals/users/./", ""),
        ):
            self.assertEqual(calendar.principal_id(document(href)), wanted)


if __name__ == "__main__":
    unittest.main()
