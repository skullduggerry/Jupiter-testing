#!/usr/bin/env python3
"""The greeter's stand-in greeter-env.py: three users, and two sessions, the
second of which a click starts as the argv it is listed with."""

import json

print(
    json.dumps(
        {
            "users": [
                {"name": "alice", "display": "Alice"},
                {"name": "bob", "display": "Bob"},
                {"name": "carol", "display": "Carol"},
            ],
            "sessions": [
                {
                    "id": "hyprland-uwsm",
                    "name": "Hyprland (uwsm-managed)",
                    "exec": "uwsm start -- hyprland.desktop",
                    "command": ["uwsm", "start", "--", "hyprland.desktop"],
                },
                {
                    "id": "shell",
                    "name": "A shell; $(not run)",
                    "exec": "sh -c 'echo; $(not run)'",
                    "command": ["sh", "-c", "echo; $(not run)"],
                },
            ],
        }
    )
)
