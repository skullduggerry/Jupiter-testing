"""A stand-in Nextcloud on loopback, the one place the calendar's helpers
accept plain http, answering CalDAV and Login Flow v2 the way Nextcloud does.

CalDAV: a principal, a calendar home that lists each collection with its
components, REPORTs that honour the COMPLETED filter, and objects to GET and
PUT under an ETag. Login Flow v2: a flow to start, and a poll that answers
404 until the browser would have finished. Everything asked is recorded,
with the Authorization it came with, and any path can be made to redirect
or to answer something else.
`prefix` puts it under a path, as an install at https://host/nextcloud is.

Elsewhere is another server, which answers nothing but records whatever
reaches it: where the password must never go.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import threading
from typing import Any, NamedTuple

USER = "tester"
PASSWORD = "stand-in-app-password"


class Asked(NamedTuple):
    method: str
    path: str
    authorization: str
    body: str


def auth(user: str = USER, password: str = PASSWORD) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def etag(text: str) -> str:
    return '"' + hashlib.sha1(text.encode()).hexdigest() + '"'


def ics(*components: str) -> str:
    return "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", *components, "END:VCALENDAR"]
    )


def todo(*lines: str) -> str:
    return "\r\n".join(["BEGIN:VTODO", *lines, "END:VTODO"])


def multistatus(responses: str) -> str:
    return (
        '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/">'
        f"{responses}</d:multistatus>"
    )


def propstat(inner: str) -> str:
    return (
        f"<d:propstat><d:prop>{inner}</d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
    )


def collection(
    href: str, name: str, colour: str, components: list[str]
) -> str:
    """A calendar's <d:response> in the home's listing."""
    held = "".join(f'<c:comp name="{kind}"/>' for kind in components)
    return (
        f"<d:response><d:href>{href}</d:href>"
        + propstat(
            "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
            f"<d:displayname>{name}</d:displayname>"
            f"<a:calendar-color>{colour}</a:calendar-color>"
            f"<c:supported-calendar-component-set>{held}</c:supported-calendar-component-set>"
        )
        + "</d:response>"
    )


class Recorder(http.server.ThreadingHTTPServer):
    """A loopback server in a thread that records what it is asked."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        super().__init__((host, 0), self.handler())
        self.asked: list[Asked] = []
        # shutdown() waits for the loop to look again, by default every
        # half second: a test with three servers waited that long for each.
        self.thread = threading.Thread(
            target=self.serve_forever, args=(0.01,), daemon=True
        )

    def __enter__(self) -> Any:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()
        self.server_close()

    @property
    def origin(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}"

    def handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *arguments: object) -> None:
                pass

            def answer(
                self,
                status: int,
                text: str = "",
                headers: dict[str, str] | None = None,
            ) -> None:
                data = text.encode()
                self.send_response(status)
                for key, value in (
                    headers
                    or {"Content-Type": "application/xml; charset=utf-8"}
                ).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_one_request(self) -> None:
                # Every method, PROPFIND and REPORT included, goes to one place.
                self.raw_requestline = self.rfile.readline(65537)
                if not self.raw_requestline or not self.parse_request():
                    self.close_connection = True
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode() if length else ""
                server.asked.append(
                    Asked(
                        self.command,
                        self.path,
                        self.headers.get("Authorization", ""),
                        body,
                    )
                )
                server.respond(self, body)
                self.wfile.flush()

        return Handler

    def respond(self, request: Any, body: str) -> None:
        request.answer(404)


class Elsewhere(Recorder):
    """Another server, where nothing is to be found."""


class Nextcloud(Recorder):
    def __init__(
        self,
        collections: dict[str, dict[str, Any]],
        prefix: str = "",
        host: str = "127.0.0.1",
    ) -> None:
        super().__init__(host)
        # By name in the home: {"tasks/": {name, colour, components, objects}}.
        self.collections = collections
        self.prefix = prefix
        self.home = f"{prefix}/remote.php/dav/calendars/{USER}/"
        self.principal = f"{prefix}/remote.php/dav/principals/users/{USER}/"
        # More <d:response>s for the home's listing, as a server might add.
        self.listed: list[str] = []
        self.redirects: dict[str, str] = {}
        # Whatever a path should answer instead, as (status, body).
        self.canned: dict[str, tuple[int, str]] = {}
        self.failing: set[str] = set()
        self.dropping: set[str] = set()
        self.reports: list[tuple[str, str, str]] = []
        self.puts: list[tuple[str, str]] = []
        # Login Flow v2: polls answered 404 before the sign-in finishes.
        self.pending_polls = 1
        self.login_reply: dict[str, Any] | None = None
        self.credentials = {"loginName": USER, "appPassword": PASSWORD}

    @property
    def url(self) -> str:
        return self.origin + self.prefix

    def respond(self, request: Any, body: str) -> None:
        path = request.path
        if path in self.redirects:
            request.answer(302, "", {"Location": self.redirects[path]})
            return
        if path in self.canned:
            request.answer(*self.canned[path])
            return
        if not path.startswith(self.prefix + "/"):
            request.answer(404)
            return
        route = path[len(self.prefix) :]
        if route.startswith(("/index.php/login/v2", "/login/v2")):
            self.login(request, route, body)
            return
        if request.headers.get("Authorization") != auth():
            request.answer(401)
            return
        handler = getattr(self, f"do_{request.command}", None)
        if handler is None:
            request.answer(405)
        else:
            handler(request, body)

    def login(self, request: Any, route: str, body: str) -> None:
        json_headers = {"Content-Type": "application/json"}
        if route == "/index.php/login/v2" and request.command == "POST":
            reply = self.login_reply or {
                "poll": {
                    "token": "poll-token",
                    "endpoint": self.url + "/login/v2/poll",
                },
                "login": self.url + "/login/v2/flow/flow-token",
            }
            request.answer(200, json.dumps(reply), json_headers)
        elif route == "/login/v2/poll" and request.command == "POST":
            if "token=poll-token" not in body:
                request.answer(404)
            elif self.pending_polls > 0:
                self.pending_polls -= 1
                request.answer(404)
            else:
                reply = {"server": self.url, **self.credentials}
                request.answer(200, json.dumps(reply), json_headers)
        else:
            request.answer(404)

    def do_PROPFIND(self, request: Any, body: str) -> None:
        if request.path == f"{self.prefix}/remote.php/dav/":
            request.answer(
                207,
                multistatus(
                    f"<d:response><d:href>{self.prefix}/remote.php/dav/</d:href>"
                    + propstat(
                        "<d:current-user-principal><d:href>"
                        f"{self.principal}</d:href></d:current-user-principal>"
                    )
                    + "</d:response>"
                ),
            )
        elif request.path == self.home:
            responses = [
                f"<d:response><d:href>{self.home}</d:href>"
                + propstat("<d:resourcetype><d:collection/></d:resourcetype>")
                + "</d:response>",
                f"<d:response><d:href>{self.home}inbox/</d:href>"
                + propstat(
                    "<d:resourcetype><d:collection/><c:schedule-inbox/></d:resourcetype>"
                )
                + "</d:response>",
            ]
            for name, held in self.collections.items():
                responses.append(
                    collection(
                        self.home + name,
                        held["name"],
                        held["colour"],
                        held["components"],
                    )
                )
            request.answer(207, multistatus("".join(responses + self.listed)))
        else:
            request.answer(404)

    def held(self, path: str) -> dict[str, Any] | None:
        if not path.startswith(self.home):
            return None
        return self.collections.get(path[len(self.home) :])

    def do_REPORT(self, request: Any, body: str) -> None:
        held = self.held(request.path)
        if held is None:
            request.answer(404)
            return
        component = "VTODO" if 'name="VTODO"' in body else "VEVENT"
        self.reports.append((request.path, component, body))
        if request.path in self.failing:
            request.answer(500)
            return
        if request.path in self.dropping:
            request.send_response(207)
            request.send_header("Content-Length", "1000")
            request.end_headers()
            request.wfile.write(b"<d:multistatus")
            request.close_connection = True
            return
        objects = [
            (index, text)
            for index, text in enumerate(held["objects"])
            if f"BEGIN:{component}" in text
        ]
        # As the server matches it: an object is open while any task in it
        # is, the main one beside a record of an occurrence done.
        if "<c:is-not-defined/>" in body:
            objects = [
                (index, text)
                for index, text in objects
                if any(
                    "\r\nCOMPLETED:" not in part
                    for part in text.split("BEGIN:VTODO")[1:]
                )
            ]
        request.answer(
            207,
            multistatus(
                "".join(
                    f"<d:response><d:href>{request.path}{index}.ics</d:href>"
                    + propstat(f"<c:calendar-data>{text}</c:calendar-data>")
                    + "</d:response>"
                    for index, text in objects
                )
            ),
        )

    def stored(self, path: str) -> tuple[list[str], int] | None:
        """The collection's objects and this path's index in them."""
        parent, _, name = path.rpartition("/")
        held = self.held(parent + "/")
        index = name.removesuffix(".ics")
        if held is None or not index.isdigit():
            return None
        if int(index) >= len(held["objects"]):
            return None
        return held["objects"], int(index)

    def do_GET(self, request: Any, body: str) -> None:
        found = self.stored(request.path)
        if found is None:
            request.answer(404)
            return
        objects, index = found
        request.answer(
            200,
            objects[index],
            {
                "Content-Type": "text/calendar; charset=utf-8",
                "ETag": etag(objects[index]),
            },
        )

    def do_PUT(self, request: Any, body: str) -> None:
        found = self.stored(request.path)
        if found is None:
            request.answer(404)
            return
        objects, index = found
        match = request.headers.get("If-Match", "")
        self.puts.append((request.path, match))
        if match and match != etag(objects[index]):
            request.answer(412)
            return
        objects[index] = body
        request.answer(204)
