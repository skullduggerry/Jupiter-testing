"""A stand-in autostart.py: notes each call, lists two apps, and takes a
moment over a change, so the next click comes while it runs."""

import json
import sys
import time

with open("@FIXTURES@/autostart", "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1] == "list":
    print(
        json.dumps(
            [
                {
                    "id": app,
                    "name": app,
                    "comment": "",
                    "icon": "",
                    "exec": app,
                    "enabled": True,
                    "custom": False,
                    "state": "running",
                }
                for app in ("a", "b")
            ]
        )
    )
else:
    time.sleep(0.5)
