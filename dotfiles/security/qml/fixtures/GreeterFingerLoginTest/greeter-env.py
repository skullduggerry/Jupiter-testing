#!/usr/bin/env python3
"""The stand-in greeter-env.py of a machine with a fingerprint reader, whose
first user is erin, whose finger the reader matches: the greeter's own scan
as it opens logs her in (GreeterFingerLoginTest)."""

import json

print(
    json.dumps(
        {
            "users": [
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
