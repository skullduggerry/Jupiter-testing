#!/usr/bin/env python3
"""The stand-in greeter-env.py of a machine with a fingerprint reader: the
greeter asks the first user (dana, whose reader times out) for a finger as
it opens, and Enter on an empty field asks again (GreeterFingerTest)."""

import json

print(
    json.dumps(
        {
            "users": [
                {"name": "dana", "display": "Dana"},
                {"name": "erin", "display": "Erin"},
                {"name": "frank", "display": "Frank"},
                {"name": "gina", "display": "Gina"},
            ],
            "sessions": [
                {
                    "id": "hyprland-uwsm",
                    "name": "Hyprland (uwsm-managed)",
                    "exec": "uwsm start -- hyprland.desktop",
                    "command": ["uwsm", "start", "--", "hyprland.desktop"],
                }
            ],
            "fingerprint": True,
        }
    )
)
