import QtQuick
import "../shell/services"

// Each monitor's block of workspace ids (PROJECT_STRUCTURE.md,
// "Workspaces"), as modules/workspaces.lua records them beside Hyprland's
// socket: fixtures/WorkspaceBlocksTest/runtime.
TestCase {
    function test_blocksFromTheFile() {
        return tryVerify(() => WorkspaceBlocks.blockOf("DP-2") !== -1).then(() => {
            compare(WorkspaceBlocks.blockOf("DP-2"), 1);
            compare(WorkspaceBlocks.blockOf("eDP-1"), 2);
            compare(WorkspaceBlocks.blockOf("HDMI-A-1"), -1, "a monitor it does not name");
        });
    }

    function test_aSpecialWorkspaceHasNoKey() {
        compare(WorkspaceBlocks.key(null), "");
    }

    // The scratchpad's tile says "magic": "special:magic" did not fit it.
    function test_aSpecialWorkspaceGoesByItsOwnName() {
        compare(WorkspaceBlocks.specialName("special:magic"), "magic");
        compare(WorkspaceBlocks.specialName("magic"), "magic");
    }
}
