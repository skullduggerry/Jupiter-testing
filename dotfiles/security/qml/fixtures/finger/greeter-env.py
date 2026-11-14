#!/usr/bin/env python3
"""The stand-in greeter-env.py of a machine with a fingerprint reader: Enter
on an empty field asks for a finger (GreeterFinger*Test)."""

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
