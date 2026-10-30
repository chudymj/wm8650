#!/usr/bin/env python3
"""
Generator pliku startowego U-Boot (wmt_scriptcmd) dla WonderMedia WM8650.
Zgodny w 100% z procedura autoscr w mtd2.bin (U-Boot 1.1.4 WM8650).
"""
import struct
import sys
import time
import zlib

SCRIPT_CONTENT = """\
textout 30 30 "Booting Debian GNU/Linux (WM8650)..." 00FF00
textout -1 -1 "Loading kernel 2.6.32.9 from NAND (0x1300000)..." FFFF00
nandrw r 0x1300000 0x1000000 0x800000
setenv bootargs mem=212M root=/dev/mmcblk0p2 rootwait noinitrd rootfstype=ext3 rw console=ttyS0,115200n8 console=tty0 lpj=AUTO init=/sbin/init-wm8650 wmtvo=2:1:24:800:480:60
textout -1 -1 "Starting Debian from /dev/mmcblk0p2..." 00FFFF
bootm 0x1000000
"""

def make_uboot_script(script_text: str, name: bytes = b"WM8650-Debian-Boot") -> bytes:
    script_bytes = script_text.encode("ascii")
    # Payload dla IH_TYPE_SCRIPT (6):
    # [uint32_be: dlugosc_skryptu] [uint32_be: 0 (koniec listy)] [tresc skryptu]
    payload = struct.pack(">II", len(script_bytes), 0) + script_bytes

    ih_magic = 0x27051956
    ih_hcrc = 0
    ih_time = int(time.time())
    ih_size = len(payload)
    ih_load = 0
    ih_ep = 0
    ih_dcrc = zlib.crc32(payload) & 0xFFFFFFFF
    ih_os = 5       # IH_OS_LINUX
    ih_arch = 2     # IH_ARCH_ARM
    ih_type = 6     # IH_TYPE_SCRIPT
    ih_comp = 0     # IH_COMP_NONE
    ih_name = name[:32].ljust(32, b"\x00")

    header_no_crc = struct.pack(
        ">IIIIIII4B32s",
        ih_magic, ih_hcrc, ih_time, ih_size, ih_load, ih_ep, ih_dcrc,
        ih_os, ih_arch, ih_type, ih_comp, ih_name
    )
    ih_hcrc = zlib.crc32(header_no_crc) & 0xFFFFFFFF

    header = struct.pack(
        ">IIIIIII4B32s",
        ih_magic, ih_hcrc, ih_time, ih_size, ih_load, ih_ep, ih_dcrc,
        ih_os, ih_arch, ih_type, ih_comp, ih_name
    )
    return header + payload

if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/home/chudy/Projekty/wm8650/wmt_scriptcmd"
    img = make_uboot_script(SCRIPT_CONTENT)
    with open(out_path, "wb") as f:
        f.write(img)
    print(f"Wygenerowano {out_path} ({len(img)} bajtow).")
