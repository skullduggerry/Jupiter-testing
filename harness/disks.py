"""The machine both installers' phase 1 tests install on: its disks, as
lsblk --json --bytes lists them, and systemd's kbd-model-map line for the
keymap they choose.
"""

GIB = 2**30
LSBLK = {
    "blockdevices": [
        {
            "name": "/dev/vdy",
            "size": 32 * GIB,
            "model": "Other",
            "type": "disk",
            "mountpoints": [None],
        },
        {
            "name": "/dev/vdz",
            "size": 64 * GIB,
            "model": "Target",
            "type": "disk",
            "mountpoints": [None],
        },
        # An empty disk too small for the system, offered for data.
        {
            "name": "/dev/vdx",
            "size": 8 * GIB,
            "model": "Data",
            "type": "disk",
            "mountpoints": [None],
            "fstype": None,
            "pttype": None,
        },
        # Windows' disk on a desktop that dual-boots: never offered for data.
        {
            "name": "/dev/vdw",
            "size": 500 * GIB,
            "model": "Windows",
            "type": "disk",
            "mountpoints": [None],
            "pttype": "gpt",
            "children": [
                {
                    "name": "/dev/vdw1",
                    "size": 100 * 2**20,
                    "type": "part",
                    "mountpoints": [None],
                    "fstype": "vfat",
                },
                {
                    "name": "/dev/vdw2",
                    "size": 499 * GIB,
                    "type": "part",
                    "mountpoints": [None],
                    "fstype": "ntfs",
                },
            ],
        },
        # The USB stick the ISO booted from.
        {
            "name": "/dev/sda",
            "size": 32 * GIB,
            "model": "Stick",
            "type": "disk",
            "mountpoints": [None],
            "pttype": "dos",
            "children": [
                {
                    "name": "/dev/sda1",
                    "size": 2 * GIB,
                    "type": "part",
                    "mountpoints": ["/run/archiso/bootmnt"],
                    "fstype": "iso9660",
                }
            ],
        },
        {
            "name": "/dev/sr0",
            "size": 2 * GIB,
            "model": "DVD",
            "type": "rom",
            "mountpoints": [None],
        },
    ]
}
KBD_MODEL_MAP = "de-latin1\tde\tpc105\t-\tterminate:ctrl_alt_bksp\t-\n"
