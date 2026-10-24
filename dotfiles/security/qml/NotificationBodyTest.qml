import QtQuick
import "../shell/services"

// A notification's body is shown with its basic markup (StyledText) but no
// image, because Qt fetches an <img> from wherever it points: any app, or
// whoever sends a message an app passes on, would learn when and from where
// it was read.
TestCase {
    function test_noImageIsLeft() {
        // The service owns the notification bus name and a shortcut, and
        // there is no D-Bus or Hyprland here.
        ignoreWarning("Could not connect to DBus|Failed to create wl_display|hyprland_global_shortcuts_v1|GlobalShortcut will not work");
        for (const body of ['<img src="https://tracker.example/p.gif">', '<IMG SRC=https://tracker.example/p.gif>', "<img/src=https://tracker.example/p.gif>", "<img\nsrc=https://tracker.example/p.gif>", '<im<img src="x">g src="https://tracker.example/p.gif">', "<i<img>mg src=https://tracker.example/p.gif>", "text <img src=https://tracker.example/p.gif"])
            verify(!/<img/i.test(NotificationService.withoutImages(body)), `an image left in ${JSON.stringify(body)}: ${NotificationService.withoutImages(body)}`);
    }

    function test_theRestIsKept() {
        compare(NotificationService.withoutImages("<b>Build</b> passed <i>at last</i>"), "<b>Build</b> passed <i>at last</i>");
        compare(NotificationService.withoutImages('Look: <img src="cat.png"> nice'), "Look:  nice");
        compare(NotificationService.withoutImages("an imagery of 2 < 3"), "an imagery of 2 < 3");
    }
}
