"""services/nextcloud-calendar.py: where it looks, what it reads, and
marking a task done.

The calendar home is discovered through current-user-principal, never built
from the login name: an SSO account's id is often a UUID. Tasks are the open
VTODOs of every collection that holds them, in the order the calendar
dropdown lists them, and marking one done writes it back as Nextcloud Tasks
would, never over another client's change. End to end against the stand-in
Nextcloud (harness/nextcloud.py), in UTC, so due times read back exactly as
written. Where the app password may go is security/test_nextcloud.py's.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
import unittest
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from typing import Any
from unittest import mock

from harness import QUICKSHELL, load
from harness.nextcloud import PASSWORD, USER, Nextcloud, ics, todo

HELPER = QUICKSHELL / "services/nextcloud-calendar.py"
os.environ["TZ"] = "UTC"
time.tzset()
helper = load(HELPER)

# Nextcloud's own layout: a VEVENT calendar, a Tasks app list (VTODO only),
# and a journal, which is not for us.
COLLECTIONS: dict[str, dict[str, Any]] = {
    "personal/": {
        "name": "Personal",
        "colour": "#3A87ADFF",
        "components": ["VEVENT"],
        "objects": [
            ics(
                "\r\n".join(
                    [
                        "BEGIN:VEVENT",
                        "UID:meeting",
                        "SUMMARY:Meeting",
                        "DTSTART:20260105T090000Z",
                        "DTEND:20260105T100000Z",
                        # An alarm's own SUMMARY and DURATION are not the event's.
                        "BEGIN:VALARM",
                        "ACTION:EMAIL",
                        "SUMMARY:Reminder",
                        "DURATION:PT5M",
                        "REPEAT:2",
                        "TRIGGER:-PT15M",
                        "END:VALARM",
                        "END:VEVENT",
                    ]
                )
            )
        ],
    },
    "tasks/": {
        "name": "Tasks",
        "colour": "#f0a000",
        "components": ["VTODO"],
        "objects": [
            ics(todo("UID:plants", "SUMMARY:Water the plants")),
            ics(todo("UID:passport", "SUMMARY:Renew passport", "PRIORITY:1")),
            ics(
                todo("UID:rent", "SUMMARY:Pay rent", "DUE;VALUE=DATE:20260105")
            ),
            ics(
                todo(
                    "UID:taxes",
                    "SUMMARY:File taxes",
                    "DUE:20251231T170000Z",
                    "BEGIN:VALARM",
                    "ACTION:EMAIL",
                    "SUMMARY:Alarm",
                    "TRIGGER:-PT1H",
                    "END:VALARM",
                )
            ),
            ics(
                todo(
                    "UID:done",
                    "SUMMARY:Done long ago",
                    "STATUS:COMPLETED",
                    "COMPLETED:20250101T100000Z",
                )
            ),
            ics(
                todo(
                    "UID:status-only",
                    "SUMMARY:Ticked elsewhere",
                    "STATUS:COMPLETED",
                )
            ),
            ics(
                todo("UID:cancelled", "SUMMARY:Called off", "STATUS:CANCELLED")
            ),
            ics(
                todo(
                    "UID:weekly",
                    "SUMMARY:Take out bins",
                    "DUE:20260102T080000Z",
                    "RRULE:FREQ=WEEKLY",
                ),
                todo(
                    "UID:weekly",
                    "SUMMARY:Take out bins",
                    "DUE:20260109T090000Z",
                    "RECURRENCE-ID:20260109T080000Z",
                ),
            ),
        ],
    },
    "journal/": {
        "name": "Journal",
        "colour": "",
        "components": ["VJOURNAL"],
        "objects": [],
    },
}
STAMP = datetime(2026, 1, 3, 12, tzinfo=UTC)


def tasks_in(text: str) -> list[list[str]]:
    """Each VTODO's lines in an object as the helper writes it, unfolded."""
    found: list[list[str]] = []
    for line in helper.unfold(text):
        if line == "BEGIN:VTODO":
            found.append([])
        elif found and found[-1][-1:] != ["END:VTODO"]:
            found[-1].append(line)
    return [task[:-1] for task in found]


def moved(*lines: str) -> list[str]:
    """A task's own lines after marking it done, alarms aside."""
    return tasks_in(helper.mark_completed(ics(todo(*lines)), STAMP))[0]


class Principal(unittest.TestCase):
    @staticmethod
    def multistatus(href: str | None) -> ElementTree.Element:
        inner = (
            f"<d:current-user-principal><d:href>{href}</d:href></d:current-user-principal>"
            if href
            else ""
        )
        return ElementTree.fromstring(
            '<?xml version="1.0"?>'
            '<d:multistatus xmlns:d="DAV:">'
            "<d:response><d:href>/remote.php/dav/</d:href>"
            f"<d:propstat><d:prop>{inner}</d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
            "</d:response></d:multistatus>"
        )

    def test_the_id_whatever_the_login(self) -> None:
        for href, wanted in (
            # An Authentik-provisioned account: a UUID, nothing like the login.
            (
                "/remote.php/dav/principals/users/6b3f1c02-9a77-4d51-bb0e-1f0e2f7d4c88/",
                "6b3f1c02-9a77-4d51-bb0e-1f0e2f7d4c88",
            ),
            # Still percent-encoded, because it is pasted into a URL.
            ("/remote.php/dav/principals/users/Jane%20Doe/", "Jane%20Doe"),
            ("/remote.php/dav/principals/users/jane", "jane"),
            # Missing: fall back, not raise or return a stray segment.
            (None, ""),
        ):
            self.assertEqual(
                helper.principal_id(self.multistatus(href)), wanted
            )


class Parsing(unittest.TestCase):
    def test_a_task_on_its_own(self) -> None:
        [task] = helper.parse_tasks(
            ics(todo("SUMMARY:Call\\, then write", "PRIORITY:x")), "Tasks"
        )
        self.assertEqual((task["due"], task["allDay"]), ("", False))
        self.assertEqual(task["summary"], "Call, then write")
        self.assertEqual(task["priority"], 0, "a malformed priority is unset")
        [dated] = helper.parse_tasks(
            ics(todo("DUE;VALUE=DATE:20260105")), "Tasks"
        )
        self.assertEqual(dated["due"], "2026-01-05T00:00:00", "local midnight")

    def test_an_alarm_is_not_its_event(self) -> None:
        [event] = helper.parse_ics(
            COLLECTIONS["personal/"]["objects"][0], "Personal"
        )
        self.assertEqual(event["summary"], "Meeting")
        self.assertEqual(event["end"], "2026-01-05T10:00:00")

    def test_an_event_that_cannot_be_read_costs_only_itself(self) -> None:
        events = helper.parse_ics(
            ics(
                "BEGIN:VEVENT\r\nSUMMARY:Broken\r\nDTSTART:2026-01-05\r\nEND:VEVENT",
                "BEGIN:VEVENT\r\nSUMMARY:Fine\r\nDTSTART:20260105T090000Z\r\nEND:VEVENT",
            ),
            "Personal",
        )
        self.assertEqual([event["summary"] for event in events], ["Fine"])


class MarkingDone(unittest.TestCase):
    def test_as_the_tasks_app_marks_it_the_alarm_untouched(self) -> None:
        marked = helper.mark_completed(
            ics(
                todo(
                    "UID:plants",
                    "SUMMARY:Water the plants",
                    "STATUS:IN-PROCESS",
                    "PERCENT-COMPLETE:40",
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    "STATUS:ignored-here",
                    "TRIGGER:-PT1H",
                    "END:VALARM",
                )
            ),
            STAMP,
        )
        self.assertEqual(
            marked.split("\r\n"),
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VTODO",
                "STATUS:COMPLETED",
                "PERCENT-COMPLETE:100",
                "COMPLETED:20260103T120000Z",
                "LAST-MODIFIED:20260103T120000Z",
                "UID:plants",
                "SUMMARY:Water the plants",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                "STATUS:ignored-here",
                "TRIGGER:-PT1H",
                "END:VALARM",
                "END:VTODO",
                "END:VCALENDAR",
                "",
            ],
        )

    def test_long_lines_are_folded(self) -> None:
        long = "SUMMARY:" + "ä" * 60
        folded = helper.mark_completed(ics(todo(long)), STAMP)
        self.assertLessEqual(
            max(len(line.encode()) for line in folded.split("\r\n")), 75
        )
        self.assertIn(long, helper.unfold(folded))

    def test_a_changed_instance_is_not_the_task(self) -> None:
        marked = helper.mark_completed(
            ics(
                todo("UID:a", "RECURRENCE-ID:20260109T080000Z"),
                todo("UID:a", "SUMMARY:Main"),
            ),
            STAMP,
        )
        instance, task = tasks_in(marked)
        self.assertNotIn("STATUS:COMPLETED", instance)
        self.assertIn("STATUS:COMPLETED", task)
        self.assertIn("SUMMARY:Main", task)

    def test_an_object_without_a_task_is_refused(self) -> None:
        with self.assertRaises(helper.Failed):
            helper.mark_completed(ics(), STAMP)

    def test_a_repeating_task_moves_on(self) -> None:
        # Only this occurrence done, as Nextcloud Tasks does it.
        [task, record] = tasks_in(
            helper.mark_completed(
                ics(
                    todo(
                        "UID:bins",
                        "SUMMARY:Take out bins",
                        "PRIORITY:5",
                        "DTSTART:20260101T080000Z",
                        "DUE:20260102T080000Z",
                        "RRULE:FREQ=WEEKLY;COUNT=3",
                        "STATUS:NEEDS-ACTION",
                    )
                ),
                STAMP,
            )
        )
        self.assertEqual(
            task,
            [
                "DUE:20260109T080000Z",
                "LAST-MODIFIED:20260103T120000Z",
                "DTSTART:20260108T080000Z",
                "RRULE:FREQ=WEEKLY;COUNT=2",
                "UID:bins",
                "SUMMARY:Take out bins",
                "PRIORITY:5",
            ],
            "start and due a day apart still, one fewer left",
        )
        self.assertEqual(
            record,
            [
                "UID:bins",
                "SUMMARY:Take out bins",
                "PRIORITY:5",
                "RECURRENCE-ID:20260102T080000Z",
                "DUE:20260102T080000Z",
                "DTSTART:20260101T080000Z",
                "STATUS:COMPLETED",
                "PERCENT-COMPLETE:100",
                "COMPLETED:20260103T120000Z",
                "LAST-MODIFIED:20260103T120000Z",
                "DTSTAMP:20260103T120000Z",
            ],
        )

    def test_the_next_occurrence(self) -> None:
        for label, lines, wanted in (
            (
                "the clock in its zone kept across the change from summer time",
                ("DUE;TZID=Europe/Berlin:20261024T090000", "RRULE:FREQ=DAILY"),
                "DUE;TZID=Europe/Berlin:20261025T090000",
            ),
            (
                "a whole day stays one, on the rule's weekdays",
                ("DUE;VALUE=DATE:20260105", "RRULE:FREQ=WEEKLY;BYDAY=MO,TH"),
                "DUE;VALUE=DATE:20260108",
            ),
            (
                "from a day off the rule, to its first day",
                ("DUE;VALUE=DATE:20260106", "RRULE:FREQ=WEEKLY;BYDAY=SU"),
                "DUE;VALUE=DATE:20260111",
            ),
            (
                "only a start date moves that",
                ("DTSTART:20260105T090000", "RRULE:FREQ=DAILY;INTERVAL=2"),
                "DTSTART:20260107T090000",
            ),
            (
                "a repeating task with no date is done for good",
                ("UID:someday", "RRULE:FREQ=WEEKLY"),
                "STATUS:COMPLETED",
            ),
        ):
            with self.subTest(label):
                self.assertEqual(moved(*lines)[0], wanted)

    def test_done_for_good_when_the_rule_runs_out(self) -> None:
        for label, lines in (
            (
                "the last of a count",
                ("DUE:20260105T090000Z", "RRULE:FREQ=DAILY;COUNT=1"),
            ),
            (
                "past the rule's end",
                (
                    "DUE:20260105T090000Z",
                    "RRULE:FREQ=DAILY;UNTIL=20260105T235959Z",
                ),
            ),
            (
                "past the rule's last day",
                (
                    "DUE;VALUE=DATE:20260105",
                    "RRULE:FREQ=WEEKLY;UNTIL=20260111",
                ),
            ),
        ):
            with self.subTest(label):
                tasks = tasks_in(
                    helper.mark_completed(ics(todo(*lines)), STAMP)
                )
                self.assertEqual(
                    [
                        (
                            "STATUS:COMPLETED" in task,
                            "RECURRENCE-ID" in str(task),
                        )
                        for task in tasks
                    ],
                    [(True, False), (True, True)],
                )

    def test_a_rule_or_date_that_cannot_be_read_is_refused(self) -> None:
        """At once: dateutil takes an interval of 0 and then looks for the
        next occurrence for ever, and the shell marks tasks done one at a
        time."""
        for label, lines in (
            (
                "no interval",
                ("DUE:20260105T090000Z", "RRULE:FREQ=DAILY;INTERVAL=0"),
            ),
            (
                "no number",
                ("DUE:20260105T090000Z", "RRULE:FREQ=DAILY;INTERVAL=x"),
            ),
            ("no frequency", ("DUE:20260105T090000Z", "RRULE:FREQ=SOMETIMES")),
            ("no date", ("DUE:sometime", "RRULE:FREQ=DAILY")),
        ):
            with self.subTest(label), self.assertRaises(ValueError):
                helper.mark_completed(ics(todo(*lines)), STAMP)


class EndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        # A copy, since marking done writes into it.
        self.collections = copy.deepcopy(COLLECTIONS)
        self.server = self.enterContext(Nextcloud(self.collections))
        self.home = self.server.home

    def run_helper(self, *arguments: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                sys.executable,
                str(HELPER),
                *(
                    arguments
                    or ("--start", "2026-01-01", "--end", "2026-02-01")
                ),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "NEXTCLOUD_URL": self.server.url,
                "NEXTCLOUD_USER": USER,
                "NEXTCLOUD_APP_PASSWORD": PASSWORD,
            },
            check=False,
        )
        payload: dict[str, Any] = json.loads(result.stdout)
        return payload

    def test_open_tasks_and_events(self) -> None:
        payload = self.run_helper()
        self.assertEqual((payload["status"], payload["message"]), ("ok", ""))
        self.assertEqual(
            [task["summary"] for task in payload["tasks"]],
            [
                "File taxes",
                "Take out bins",
                "Pay rent",
                "Renew passport",
                "Water the plants",
            ],
            "dated first, then by priority",
        )
        self.assertEqual(
            [task["due"] for task in payload["tasks"]],
            [
                "2025-12-31T17:00:00",
                "2026-01-02T08:00:00",
                "2026-01-05T00:00:00",
                "",
                "",
            ],
        )
        self.assertEqual(
            (payload["tasks"][0]["calendar"], payload["tasks"][0]["colour"]),
            ("Tasks", "#f0a000"),
        )
        self.assertEqual(
            {task["summary"]: task["href"] for task in payload["tasks"]},
            {
                "File taxes": self.home + "tasks/3.ics",
                "Take out bins": self.home + "tasks/7.ics",
                "Pay rent": self.home + "tasks/2.ics",
                "Renew passport": self.home + "tasks/1.ics",
                "Water the plants": self.home + "tasks/0.ics",
            },
        )
        self.assertEqual(
            [event["summary"] for event in payload["events"]], ["Meeting"]
        )
        self.assertEqual(
            sorted(
                (path.removeprefix(self.home), component)
                for path, component, _ in self.server.reports
            ),
            [("personal/", "VEVENT"), ("tasks/", "VTODO")],
            "each collection asked for what it holds",
        )
        self.assertTrue(
            all(
                "<c:is-not-defined/>" in body
                for _, component, body in self.server.reports
                if component == "VTODO"
            ),
            "completed tasks left to the server",
        )

    def test_a_list_lost_costs_only_its_tasks(self) -> None:
        for broken in ("failing", "dropping"):
            with self.subTest(broken):
                setattr(self.server, broken, {self.home + "tasks/"})
                payload = self.run_helper()
                self.assertEqual(
                    (
                        payload["status"],
                        payload["message"],
                        len(payload["events"]),
                        payload["tasks"],
                    ),
                    ("ok", "could not read Tasks", 1, []),
                )
                setattr(self.server, broken, set())
        self.server.failing = {self.home + "tasks/", self.home + "personal/"}
        self.assertEqual(
            self.run_helper()["status"], "error", "everything lost"
        )

    def test_marking_done(self) -> None:
        done = self.run_helper("--complete", self.home + "tasks/0.ics")
        self.assertEqual(done, {"status": "ok", "message": ""})
        self.assertEqual(
            [match.startswith('"') for _, match in self.server.puts],
            [True],
            "written only over the version read",
        )
        self.assertNotIn(
            "Water the plants",
            [task["summary"] for task in self.run_helper()["tasks"]],
        )
        repeating = self.run_helper("--complete", self.home + "tasks/7.ics")
        self.assertEqual(repeating["status"], "ok")
        self.assertEqual(
            [
                task["due"]
                for task in self.run_helper()["tasks"]
                if task["summary"] == "Take out bins"
            ],
            ["2026-01-09T08:00:00"],
            "still open, due next week",
        )
        self.assertEqual(
            [path for path, _ in self.server.puts],
            [self.home + "tasks/0.ics", self.home + "tasks/7.ics"],
            "its record in the same object",
        )
        gone = self.run_helper("--complete", self.home + "tasks/99.ics")
        self.assertEqual(gone["status"], "error")

    def test_a_task_that_cannot_be_read_is_answered_not_written(self) -> None:
        objects = self.collections["tasks/"]["objects"]
        objects.append(
            ics(todo("DUE:20260105T090000Z", "RRULE:FREQ=DAILY;INTERVAL=0"))
        )
        answer = self.run_helper(
            "--complete", f"{self.home}tasks/{len(objects) - 1}.ics"
        )
        self.assertEqual(answer["status"], "error")
        self.assertIn("cannot be read", answer["message"])
        self.assertEqual(self.server.puts, [])

    def test_an_address_that_is_none_is_answered(self) -> None:
        for url in ("https://[", "https://cloud.example.org:port"):
            with self.subTest(url=url):
                result = subprocess.run(
                    [sys.executable, str(HELPER)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env={
                        **os.environ,
                        "NEXTCLOUD_URL": url,
                        "NEXTCLOUD_USER": USER,
                        "NEXTCLOUD_APP_PASSWORD": PASSWORD,
                    },
                    check=False,
                )
                self.assertEqual(
                    json.loads(result.stdout)["status"], "unconfigured"
                )

    def test_another_clients_change_is_not_written_over(self) -> None:
        real = helper.exchange

        def edited_meanwhile(method: str, url: str, *rest: Any) -> Any:
            answer = real(method, url, *rest)
            if method == "GET":
                self.collections["tasks/"]["objects"][1] += "\r\n"
            return answer

        self.enterContext(
            mock.patch.object(helper, "exchange", edited_meanwhile)
        )
        self.enterContext(
            mock.patch.dict(
                os.environ,
                NEXTCLOUD_URL=self.server.url,
                NEXTCLOUD_USER=USER,
                NEXTCLOUD_APP_PASSWORD=PASSWORD,
            )
        )
        with self.assertRaisesRegex(
            helper.Failed,
            "HTTP 412 Precondition Failed \\(changed on the server meanwhile\\)",
        ):
            helper.complete(self.home + "tasks/1.ics")
        self.assertNotIn("COMPLETED", self.collections["tasks/"]["objects"][1])


if __name__ == "__main__":
    unittest.main()
