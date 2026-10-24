"""A stand-in greetd, speaking greetd-ipc(7) on a Unix socket in a thread.

Each request is a 32-bit length in native byte order and that many bytes of
JSON, and so is each answer. Who can log in and what PAM would ask them is a
scenario (a fixture's greetd.json), by user name:

    {"alice": [{"secret": "Password:", "answer": "..."}],
     "bob":   [{"secret": "Password:", "answer": "..."},
               {"visible": "Verification code:", "answer": "123456"}],
     "carol": [{"secret": "Password:", "answer": "..."},
               {"info": "The account is locked."}, {"fail": true}],
     "dave":  [{"refuse": "dave may not log in here"}]}

A wrong answer, or a user the scenario does not know, ends in an auth_error,
as PAM ends one: an unknown user is asked for a password all the same. A
"refuse" step answers create_session itself with an error, as greetd does
when it cannot start a login at all.
Every request is written to the log as a line of JSON, for the test to read
back. start_session is recorded and never answered, because Quickshell
quits once a session has started, and the test would end with it.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any

LENGTH = struct.Struct("=I")


class Greetd:
    def __init__(
        self, path: Path, log: Path, scenario: dict[str, list[dict[str, Any]]]
    ) -> None:
        self.path, self.log, self.scenario = path, log, scenario
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen()
        log.write_text("")
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def __enter__(self) -> Greetd:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.close()

    def serve(self) -> None:
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return  # closed
            threading.Thread(
                target=self.talk, args=(client,), daemon=True
            ).start()

    def talk(self, client: socket.socket) -> None:
        steps: list[dict[str, Any]] = []
        with client:
            while (request := receive(client)) is not None:
                with self.log.open("a") as log:
                    log.write(json.dumps(request) + "\n")
                kind = request.get("type")
                if kind == "create_session":
                    name = request.get("username", "")
                    steps = list(
                        self.scenario.get(
                            name, [{"secret": "Password:", "answer": None}]
                        )
                    )
                    if steps and "refuse" in steps[0]:
                        answer = {
                            "type": "error",
                            "error_type": "error",
                            "description": steps.pop(0)["refuse"],
                        }
                    else:
                        answer = self.next(steps)
                elif kind == "post_auth_message_response":
                    step = steps.pop(0) if steps else {}
                    wanted = step.get("answer")
                    asked = "secret" in step or "visible" in step
                    if asked and request.get("response") != wanted:
                        steps = []
                        answer = failure("authentication failed")
                    else:
                        answer = self.next(steps)
                elif kind == "cancel_session":
                    steps = []
                    answer = {"type": "success"}
                elif kind == "start_session":
                    continue
                else:
                    answer = {
                        "type": "error",
                        "error_type": "error",
                        "description": f"unknown request {kind}",
                    }
                send(client, answer)

    @staticmethod
    def next(steps: list[dict[str, Any]]) -> dict[str, Any]:
        """The answer that the next step, or its absence, gives."""
        if not steps:
            return {"type": "success"}
        step = steps[0]
        if step.get("fail"):
            steps.clear()
            return failure("authentication failed")
        for kind in ("secret", "visible", "info", "error"):
            if kind in step:
                return {
                    "type": "auth_message",
                    "auth_message_type": kind,
                    "auth_message": step[kind],
                }
        raise ValueError(f"a step greetd cannot take: {step}")


def failure(description: str) -> dict[str, Any]:
    return {
        "type": "error",
        "error_type": "auth_error",
        "description": description,
    }


def receive(client: socket.socket) -> dict[str, Any] | None:
    head = read(client, LENGTH.size)
    if head is None:
        return None
    body = read(client, LENGTH.unpack(head)[0])
    if body is None:
        return None
    request: dict[str, Any] = json.loads(body)
    return request


def read(client: socket.socket, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = client.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def send(client: socket.socket, message: dict[str, Any]) -> None:
    data = json.dumps(message).encode()
    client.sendall(LENGTH.pack(len(data)) + data)
