import QtQuick
import Quickshell
import Quickshell.Io
import "../shell/services"

// The wallpaper's fit (PROJECT_STRUCTURE.md, "Wallpaper"): handed to
// hyprpaper with every wallpaper, through the stand-in hyprctl
// (fixtures/WallpaperServiceTest/bin), and kept for its start in the saved
// config. With no Hyprland here there are no monitors, so only the fallback
// is named.
TestCase {
    readonly property string picture: Quickshell.env("HOME") + "/Wallpapers/whale.jpg"
    readonly property FileView asked: FileView {
        path: Quickshell.shellDir + "/../fixtures/hyprctl"
        blockAllReads: true
        printErrors: false
    }
    readonly property FileView saved: FileView {
        path: Quickshell.env("XDG_STATE_HOME") + "/quickshell/hyprpaper.conf"
        blockAllReads: true
        printErrors: false
    }
    readonly property FileView settings: FileView {
        path: Quickshell.statePath("wallpaper.json")
        blockAllReads: true
        printErrors: false
    }

    function calls(): var {
        asked.reload();
        return asked.text().split("\n").filter(line => line.startsWith("hyprpaper "));
    }

    function config(): string {
        saved.reload();
        return saved.text();
    }

    function test_aPickIsCoverUnlessToldOtherwise() {
        ignoreWarning("HYPRLAND_INSTANCE_SIGNATURE is unset");
        compare(WallpaperService.fit, "cover");
        WallpaperService.apply(picture);
        return tryVerify(() => calls().length > 0, 2000, "hyprpaper is told").then(() => {
            compare(calls()[calls().length - 1], "hyprpaper wallpaper ," + picture + ",cover");
            // The config is written asynchronously, after hyprpaper may be told.
            return tryVerify(() => config().includes("    fit_mode = cover\n"), 2000, "the saved config keeps cover");
        });
    }

    function test_aNewFitNamesTheWallpaperAgain() {
        const before = calls().length;
        WallpaperService.setFit("contain");
        compare(WallpaperService.fit, "contain");
        return tryVerify(() => calls().length > before, 2000, "hyprpaper is told again").then(() => {
            compare(calls()[calls().length - 1], "hyprpaper wallpaper ," + picture + ",contain");
            return tryVerify(() => config().includes("    path = " + picture + "\n    fit_mode = contain\n"), 2000, "the saved config keeps the wallpaper, in the new fit");
        }).then(() => {
            return tryVerify(() => {
                settings.reload();
                return settings.text().includes('"fit": "contain"');
            }, 2000, "wallpaper.json keeps the fit");
        });
    }

    function test_theNextPickKeepsTheFit() {
        WallpaperService.setFit("tile");
        const before = calls().length;
        WallpaperService.apply(picture);
        return tryVerify(() => calls().length > before, 2000, "hyprpaper is told").then(() => {
            compare(calls()[calls().length - 1], "hyprpaper wallpaper ," + picture + ",tile");
            return tryVerify(() => config().includes("    fit_mode = tile\n"), 2000, "the saved config keeps tile");
        });
    }
}
