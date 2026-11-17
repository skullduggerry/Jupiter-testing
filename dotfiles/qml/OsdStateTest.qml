import QtQuick
import "../shell/services"

// The OSD and the quick-settings surfaces:
// no OSD over a surface already showing the same panel, and a surface that
// opens just after a key press starts on that key's page.
TestCase {
    function test_aKeyShowsTheOsd() {
        OsdState.viewers = 0;
        OsdState.show(OsdState.zoneBrightness);
        verify(OsdState.showing);
        compare(OsdState.zone, "brightness");
        verify(OsdState.recentlyUsed());
    }

    function test_notOverAnOpenSurface() {
        OsdState.viewers = 0;
        OsdState.show(OsdState.zoneAudio);
        OsdState.viewers = 1;
        verify(!OsdState.showing, "a surface opening hides it");
        OsdState.show(OsdState.zoneBrightness);
        verify(!OsdState.showing, "nor shown while one is open");
        compare(OsdState.zone, "brightness", "but the key is still noted");
        OsdState.viewers = 0;
    }

    function test_onlyRecently() {
        OsdState.zoneAt = Date.now() - OsdState.timeout - 1;
        verify(!OsdState.recentlyUsed());
    }

    function test_itLingersThenGoes() {
        OsdState.viewers = 0;
        OsdState.show(OsdState.zoneAudio);
        return tryVerify(() => !OsdState.showing, OsdState.timeout + 1000, "still showing");
    }
}
