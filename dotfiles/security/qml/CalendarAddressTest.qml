import QtQuick
import "../shell/services"

// The Nextcloud address the calendar is set up with: the app password goes out as HTTP Basic
// auth on every request, so only https, or http that cannot leave the
// machine. nextcloud-calendar.py checks again (security/test_nextcloud.py);
// this is what the setup form says before anything is saved.
TestCase {
    function test_httpsOrLoopbackOnly() {
        compare(CalendarService.addressProblem("https://cloud.example.org"), "");
        compare(CalendarService.addressProblem("https://example.org/nextcloud"), "");
        compare(CalendarService.addressProblem("http://localhost:8080"), "");
        compare(CalendarService.addressProblem("http://localhost/nextcloud"), "");
        compare(CalendarService.addressProblem("http://127.0.0.1"), "");
        compare(CalendarService.addressProblem("http://[::1]:8080"), "", "IPv6 loopback, as the helpers take it");
        for (const address of ["http://cloud.example.org", "http://localhost.example.org", "http://127.0.0.1.example.org", "http://127.0.0.2", "http://[::2]", "http://[::1].example.org", "ftp://cloud.example.org", "cloud.example.org", ""])
            verify(CalendarService.addressProblem(address) !== "", `${address} accepted`);
    }

    // What comes before an @ is a user name, and the host is what follows.
    function test_aUserBeforeTheHostIsNoLoopback() {
        for (const address of ["http://localhost:x@cloud.example.org", "http://localhost@cloud.example.org", "http://127.0.0.1:80@cloud.example.org/", "http://localhost:@cloud.example.org"])
            verify(CalendarService.addressProblem(address) !== "", `${address} accepted`);
    }

    // The form saves what baseAddress() makes of the address: the check
    // holds for that too.
    function test_whatIsSavedIsChecked() {
        verify(CalendarService.configure("http://cloud.example.org/index.php/apps/calendar", "jane") !== "");
        verify(CalendarService.signIn("http://localhost:1@cloud.example.org/") !== "");
        compare(CalendarService.serverUrl, "", "nothing was saved");
    }
}
