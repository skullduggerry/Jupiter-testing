import QtQuick
import "../shell/services"

// The Nextcloud address the calendar is set up with, from any page of the
// web UI, and the tasks marked done. Which addresses the app password may go
// to: security/qml/CalendarAddressTest.qml.
TestCase {
    function test_anyPageOfTheWebUi() {
        compare(CalendarService.baseAddress(" https://cloud.example.org/index.php/apps/calendar/dayGridMonth "), "https://cloud.example.org");
        compare(CalendarService.baseAddress("https://example.org/nextcloud/remote.php/dav/"), "https://example.org/nextcloud");
        compare(CalendarService.baseAddress("https://cloud.example.org///"), "https://cloud.example.org");
    }

    // A task marked done stays hidden while the write is on its way, even
    // from a fetch that started before it.
    function test_doneTasksStayHidden() {
        const task = (href, summary) => ({
                    href: href,
                    summary: summary,
                    calendar: "Tasks",
                    colour: "",
                    allDay: false,
                    due: ""
                });
        CalendarService.completing = ["/remote.php/dav/calendars/a/tasks/1.ics"];
        CalendarService.adopt([], [task("/remote.php/dav/calendars/a/tasks/1.ics", "Done"), task("/remote.php/dav/calendars/a/tasks/2.ics", "Open")]);
        compare(CalendarService.tasks.length, 1);
        compare(CalendarService.tasks[0].summary, "Open");
        CalendarService.adopt([], [
            {
                summary: "Cached",
                calendar: "Tasks",
                allDay: false,
                due: ""
            }
        ]);
        compare(CalendarService.tasks[0].href, "");
        CalendarService.complete("");
        compare(CalendarService.completing.length, 1);
        CalendarService.completing = [];
        CalendarService.tasks = [];
    }
}
