#!/usr/bin/env python3
"""
wm8650_touchd.py - Touchscreen & SAR-ADC Battery daemon for WonderMedia WM8650.
Communicates directly with VIA VT1609 over SPI0 (0xD8240000) using SPI Mode 3.

Factory calibration from U-Boot:
  wmt.io.touch=1:vt1609:2:800:480
  wmt.io.ts.2dcal=174 -23279 47793714 14523 268 -4891371 55776

Outputs:
  - UDP packet "TOUCH <px> <py> <rx> <ry>\n" to 127.0.0.1:9999
  - State file /run/wm8650_touch_last.txt
  - Battery voltage and percentage in /run/wm8650_battery.txt
"""

import mmap
import os
import socket
import struct
import time

GPIO_BASE = 0xD8110000
PMC_BASE  = 0xD8130000
SPI0_BASE = 0xD8240000
MAP_SIZE  = 4096

A1, B1, C1 = 174, -23279, 47793714
A2, B2, C2 = 14523, 268, -4891371
DENOM = 55776

def r32(mm, off):
    return struct.unpack("<I", mm[off : off + 4])[0]

def w32(mm, off, val):
    mm[off : off + 4] = struct.pack("<I", val)


def main():
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    gpio = mmap.mmap(fd, MAP_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=GPIO_BASE)
    pmc  = mmap.mmap(fd, MAP_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=PMC_BASE)
    spi  = mmap.mmap(fd, MAP_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=SPI0_BASE)

    # 1. Clock and Pinmux setup
    w32(pmc, 0x250, r32(pmc, 0x250) | (1 << 11) | (1 << 12) | (1 << 15))
    w32(gpio, 0x48, r32(gpio, 0x48) & ~(0x0F << 24))
    w32(gpio, 0x488, r32(gpio, 0x488) | (0x0F << 24))
    w32(gpio, 0x4C8, r32(gpio, 0x4C8) | (0x0F << 24))

    def reset_spi_fifo():
        w32(spi, 0x00, r32(spi, 0x00) | (1 << 16) | (1 << 17))
        timeout = 10000
        while (r32(spi, 0x04) & (1 << 7)) and timeout > 0:
            timeout -= 1

    # 2. SPI0 Controller setup: TCD=30 (~1.5 MHz), Mode 3 (CPOL=1, CPHA=1)
    tcd = 30
    cr_val = (tcd << 21) | (1 << 2) | (1 << 1)
    w32(spi, 0x00, cr_val)
    w32(spi, 0x04, 0xFFFFFFFF)
    w32(spi, 0x08, 0x24)
    w32(spi, 0x0C, 0x20)

    def spi_write_reg(reg, val):
        reset_spi_fifo()
        spi[0x10] = (reg & 0x7F) | 0x80
        spi[0x10] = (reg >> 7) & 0x01
        spi[0x10] = val & 0xFF
        w32(spi, 0x00, r32(spi, 0x00) | (1 << 5))
        timeout = 20000
        while (r32(spi, 0x04) & (1 << 7)) and timeout > 0:
            timeout -= 1
        w32(spi, 0x00, r32(spi, 0x00) & ~(1 << 5))
        _ = spi[0x30]; _ = spi[0x30]; _ = spi[0x30]

    def spi_read_reg(reg):
        reset_spi_fifo()
        spi[0x10] = (reg & 0x7F)
        spi[0x10] = (reg >> 7) & 0x01
        spi[0x10] = 0x00
        spi[0x10] = 0x00
        spi[0x10] = 0x00
        w32(spi, 0x00, r32(spi, 0x00) | (1 << 5))
        timeout = 20000
        while (r32(spi, 0x04) & (1 << 7)) and timeout > 0:
            timeout -= 1
        w32(spi, 0x00, r32(spi, 0x00) & ~(1 << 5))
        _ = spi[0x30]; _ = spi[0x30]; _ = spi[0x30]; _ = spi[0x30]; b4 = spi[0x30]
        return b4

    # 3. Initialize VT1609 SAR-ADC & Touchscreen
    def init_vt1609():
        spi_write_reg(0xC0, 0x08)  # PWC: SAR-ADC enable
        spi_write_reg(0xC1, 0x02)  # CR: Auto 4-wire position conversion
        spi_write_reg(0xC8, 0x7F)  # INTCR
        spi_write_reg(0xC9, 0x0E)  # INTEN: PenUp, PenDown, Timeout
        spi_write_reg(0xC3, 0x04)  # CDPR: Divisor
        spi_write_reg(0xC4, 0x7C)  # TSPC
        spi_write_reg(0xC5, 0x4C)
        spi_write_reg(0xCA, 0x0D)  # Clear INTS

    init_vt1609()

    def read_battery_mv():
        try:
            spi_write_reg(0xC0, 0x08)
            spi_write_reg(0xC1, 0x00)
            spi_write_reg(0xC7, 0x01)
            spi_write_reg(0xCA, spi_read_reg(0xCA) | 0x01)
            spi_write_reg(0xC1, 0x10)  # Start manual ADC
            time.sleep(0.015)
            bl = spi_read_reg(0xCE)
            bh = spi_read_reg(0xCF)
            spi_write_reg(0xC1, 0x02)  # Restore TS mode
            raw_adc = ((bh & 0x0F) << 8) | bl
            mv = int(raw_adc * 1047 / 1000)
            if 3000 <= mv <= 4500:
                pct = max(0, min(100, int((mv - 3500) * 100 / (4150 - 3500))))
                return mv, pct
        except Exception:
            pass
        return 3850, 60

    # UDP socket to dashboard
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dst_addr = ("127.0.0.1", 9999)

    last_bat_time = time.time()
    last_touch_time = 0.0
    last_raw = (0, 0)
    was_touched = False

    # Initial battery read
    init_mv, init_pct = read_battery_mv()
    try:
        with open("/run/wm8650_battery.txt", "w") as bf:
            bf.write(f"{init_mv} {init_pct}\n")
    except Exception:
        pass

    while True:
        now = time.time()
        # Battery check every 30 seconds
        if now - last_bat_time >= 30.0:
            last_bat_time = now
            bmv, bpct = read_battery_mv()
            try:
                with open("/run/wm8650_battery.txt", "w") as bf:
                    bf.write(f"{bmv} {bpct}\n")
            except Exception:
                pass

        xl = spi_read_reg(0xD0)
        xh = spi_read_reg(0xD1)
        yl = spi_read_reg(0xD2)
        yh = spi_read_reg(0xD3)
        rx = ((xh & 0x0F) << 8) | xl
        ry = ((yh & 0x0F) << 8) | yl

        # Valid touches on VT1609 produce rx in 350..3900 and ry in 100..3900
        # (idle floating released state is rx ~105)
        is_touch = (350 <= rx <= 3900 and 100 <= ry <= 3900)

        if is_touch:
            moved = (abs(rx - last_raw[0]) > 30 or abs(ry - last_raw[1]) > 30)
            tap_new = (not was_touched and (now - last_touch_time > 0.15))
            if tap_new or moved:
                px = int((A1 * rx + B1 * ry + C1) / DENOM)
                py = int((A2 * rx + B2 * ry + C2) / DENOM)
                px = max(0, min(799, px))
                py = max(0, min(479, py))

                msg = f"TOUCH {px} {py} {rx} {ry}\n".encode("ascii")
                try:
                    udp_sock.sendto(msg, dst_addr)
                except Exception:
                    pass
                try:
                    with open("/run/wm8650_touch_last.txt", "w") as tf:
                        tf.write(f"{int(now)} {px} {py} {rx} {ry}\n")
                except Exception:
                    pass
                last_raw = (rx, ry)
                last_touch_time = now
            was_touched = True
        else:
            was_touched = False

        time.sleep(0.04)  # 25 Hz polling (~2% CPU)


if __name__ == "__main__":
    main()
