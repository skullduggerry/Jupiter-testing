import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The calendar dropdown's grid (CalendarService, set in Settings → Calendar):
// the day each week starts on, and the month or a few weeks from a day's,
// paged by as many, kept in the state folder.
TestCase {
    readonly property FileView written: FileView {
        path: Quickshell.statePath("calendar.json")
        blockAllReads: true
        printErrors: false
    }

    function kept(): var {
        written.reload();
        const text = written.text();
        return text === "" ? null : JSON.parse(text);
    }

    function day(year: int, month: int, date: int): date {
        return new Date(year, month - 1, date);
    }

    function sameDay(actual: date, expected: date) {
        compare(CalendarService.dayKey(actual), CalendarService.dayKey(expected));
    }

    function test_theLocaleUntilOneIsPicked() {
        compare(CalendarService.weekStart, -1);
        compare(CalendarService.shownWeeks, 0);
        compare(CalendarService.firstDayOfWeek, Qt.locale().firstDayOfWeek);
        compare(CalendarService.weekStartChoices.length, 8);
        compare(CalendarService.weekStartChoices[0].value, -1);
    }

    // November 2026 starts on a Sunday and has 30 days.
    function test_theMonthFollowsTheWeekStart() {
        const november = day(2026, 11, 13);
        CalendarService.setWeekStart(1);
        sameDay(CalendarService.gridStart(november), day(2026, 10, 26));
        compare(CalendarService.weekCount(november), 6);
        CalendarService.setWeekStart(0);
        sameDay(CalendarService.gridStart(november), day(2026, 11, 1));
        compare(CalendarService.weekCount(november), 5);
        CalendarService.setWeekStart(6);
        sameDay(CalendarService.gridStart(november), day(2026, 10, 31));
        compare(CalendarService.weekCount(november), 5);
        sameDay(CalendarService.page(november, 1), day(2026, 12, 1));
        sameDay(CalendarService.page(day(2026, 1, 31), -1), day(2025, 12, 1));
        compare(CalendarService.gridTitle(november), Qt.formatDate(november, "MMMM yyyy"));
    }

    function test_aFewWeeksFromTheDaysOwn() {
        CalendarService.setWeekStart(1);
        CalendarService.setShownWeeks(2);
        const friday = day(2026, 11, 13);
        sameDay(CalendarService.gridStart(friday), day(2026, 11, 9));
        compare(CalendarService.weekCount(friday), 2);
        compare(CalendarService.gridTitle(friday), "9 – 22 " + Qt.formatDate(friday, "MMMM yyyy"));
        const next = CalendarService.page(friday, 1);
        sameDay(next, day(2026, 11, 27));
        sameDay(CalendarService.gridStart(next), day(2026, 11, 23));
        compare(CalendarService.gridTitle(next), Qt.formatDate(day(2026, 11, 23), "d MMM") + " – " + Qt.formatDate(day(2026, 12, 6), "d MMM yyyy"));
        sameDay(CalendarService.page(friday, -1), day(2026, 10, 30));
        CalendarService.setShownWeeks(1);
        compare(CalendarService.gridTitle(day(2026, 12, 30)), Qt.formatDate(day(2026, 12, 28), "d MMM yyyy") + " – " + Qt.formatDate(day(2027, 1, 3), "d MMM yyyy"));
    }

    // Paging by the most weeks offered stays inside what a fetch covers, so
    // it never waits on the network.
    function test_pagingStaysInsideTheFetch() {
        const most = Math.max(...CalendarService.weekChoices.map(choice => choice.value));
        verify(most * 7 * 2 < CalendarService.prefetchDays);
    }

    function test_anythingElseIsTheDefault() {
        CalendarService.setShownWeeks(5);
        compare(CalendarService.shownWeeks, 0);
        CalendarService.setWeekStart(9);
        compare(CalendarService.weekStart, -1);
        compare(CalendarService.firstDayOfWeek, Qt.locale().firstDayOfWeek);
        CalendarService.setWeekStart(1);
        CalendarService.setShownWeeks(3);
    }

    function test_keptInTheStateFolder() {
        return tryVerify(() => kept() !== null && kept().shownWeeks === 3).then(() => {
            compare(kept().weekStart, 1);
        });
    }
}
