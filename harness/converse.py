"""A PAM conversation, as greetd's worker holds one: run a service's auth and
account stacks for a user, answering each question from a list.

    python3 harness/converse.py SERVICE USER < answers.json

answers.json is a JSON list of strings, one per question PAM asks (prompts
with or without echo), in order; a question past the end of the list is
answered with an empty string. Prints a JSON object: every message PAM sent
(style and text, in order) and what pam_authenticate and pam_acct_mgmt
returned (0 is PAM_SUCCESS). libpam through ctypes: Python's standard
library alone, as the stacks under test run inside harness/pam.py's sandbox.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import sys
from typing import Any

PROMPT_ECHO_OFF, PROMPT_ECHO_ON, ERROR_MSG, TEXT_INFO = 1, 2, 3, 4
STYLES = {1: "secret", 2: "visible", 3: "error", 4: "info"}


class Message(ctypes.Structure):
    _fields_ = [("style", ctypes.c_int), ("text", ctypes.c_char_p)]


class Response(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_char_p), ("retcode", ctypes.c_int)]


CONVERSE = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.POINTER(Message)),
    ctypes.POINTER(ctypes.POINTER(Response)),
    ctypes.c_void_p,
)


class Conversation(ctypes.Structure):
    _fields_ = [("conv", CONVERSE), ("appdata", ctypes.c_void_p)]


def main() -> int:
    service, user = sys.argv[1], sys.argv[2]
    answers: list[str] = json.load(sys.stdin)
    pam = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
    libc.calloc.restype = ctypes.c_void_p
    libc.strdup.restype = ctypes.c_void_p
    said: list[dict[str, Any]] = []

    def converse(count: int, messages: Any, responses: Any, _: Any) -> int:
        size = ctypes.sizeof(Response)
        replies = libc.calloc(count, size)
        for index in range(count):
            message = messages[index].contents
            style = STYLES.get(message.style, str(message.style))
            text = (message.text or b"").decode()
            said.append({"style": style, "text": text})
            if message.style in (PROMPT_ECHO_OFF, PROMPT_ECHO_ON):
                answer = answers.pop(0) if answers else ""
                reply = Response.from_address(replies + index * size)
                reply.resp = None
                ctypes.cast(
                    replies + index * size, ctypes.POINTER(ctypes.c_void_p)
                )[0] = libc.strdup(answer.encode())
        responses[0] = ctypes.cast(replies, ctypes.POINTER(Response))
        return 0

    conversation = Conversation(CONVERSE(converse), None)
    handle = ctypes.c_void_p()
    started = pam.pam_start(
        service.encode(), user.encode(), ctypes.byref(conversation),
        ctypes.byref(handle),
    )  # fmt: skip
    if started:
        print(json.dumps({"said": said, "start": started}))
        return 1
    authenticated = pam.pam_authenticate(handle, 0)
    account = pam.pam_acct_mgmt(handle, 0) if authenticated == 0 else None
    pam.pam_end(handle, authenticated)
    print(
        json.dumps(
            {"said": said, "authenticate": authenticated, "account": account}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
