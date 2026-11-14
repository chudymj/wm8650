#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wm8650_soc_dashboard.py - Home Network Monitor & Lightweight IDS (Canary Honeypot)
for WonderMedia WM8650 (800x480 16-bit RGB565 Framebuffer /dev/fb0).

Features:
  - 5 switchable tabs (Overview, LAN Hosts, IDS Sensors, Alarm Log, Terminal)
  - Non-intrusive background tab highlighting (Amber WARN / Flashing Red ALERT
    with unread counters + hardware sound/vibration via wm8650-beep)
  - Seamless coexistence with Linux console (runs on tty3, pauses /dev/fb0 writes
    when user switches to tty1/tty2)
  - Supports VT1609 Touchscreen (UDP 127.0.0.1:9999), USB mouse (/dev/input/mice),
    and USB keyboard (keys 1-5, A, S, C, M, T, Esc)
"""

import collections
import ctypes
import datetime
import glob
import json
import os
import re
import select
import socket
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
from PIL import Image, ImageDraw, ImageFont

FB_WIDTH = 800
FB_HEIGHT = 480
FB_DEV = "/dev/fb0"
ACTIVE_TTY_PATH = "/sys/class/tty/tty0/active"
DASHBOARD_TTY = "tty3"
KNOWN_HOSTS_FILE = "/etc/wm8650-soc/known_hosts.json"
BATTERY_FILE = "/run/wm8650_battery.txt"
BEEP_BIN = "/usr/local/bin/wm8650-beep"

# Fast C Framebuffer Blitter (libwm8650_rgb565.so) - ARM926EJ-S L1 cache optimized
C_BLITTER = None
for _lib_path in (
    "/usr/local/lib/libwm8650_rgb565.so",
    os.path.join(os.path.dirname(__file__), "../tools/libwm8650_rgb565.so"),
    os.path.join(os.path.dirname(__file__), "libwm8650_rgb565.so"),
    "/tmp/libwm8650_rgb565.so",
):
    if os.path.exists(_lib_path):
        try:
            _cdll = ctypes.CDLL(_lib_path)
            _cdll.fb_write_rgb888.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
            _cdll.fb_write_rgb888.restype = ctypes.c_int
            C_BLITTER = _cdll.fb_write_rgb888
            break
        except Exception:
            pass

REDRAW_EVENT = threading.Event()

# Lightweight OUI Database for popular LAN / SmartHome / Mobile devices
OUI_DATABASE = {
    "b8:27:eb": "Raspberry Pi",
    "dc:a6:32": "Raspberry Pi",
    "e4:5f:01": "Raspberry Pi",
    "28:cd:c1": "Raspberry Pi",
    "d8:3a:dd": "Raspberry Pi",
    "18:fe:34": "Espressif (IoT)",
    "24:0a:c4": "Espressif (IoT)",
    "30:ae:a4": "Espressif (IoT)",
    "3c:61:05": "Espressif (IoT)",
    "3c:71:bf": "Espressif (IoT)",
    "4c:75:25": "Espressif (IoT)",
    "5c:cf:7f": "Espressif (IoT)",
    "60:01:94": "Espressif (IoT)",
    "68:c6:3a": "Espressif (IoT)",
    "84:0d:8e": "Espressif (IoT)",
    "84:f3:eb": "Espressif (IoT)",
    "a4:cf:12": "Espressif (IoT)",
    "ac:67:b2": "Espressif (IoT)",
    "b4:e6:2d": "Espressif (IoT)",
    "bc:dd:c2": "Espressif (IoT)",
    "cc:50:e3": "Espressif (IoT)",
    "d8:bc:38": "Espressif (IoT)",
    "dc:4f:22": "Espressif (IoT)",
    "e0:98:06": "Espressif (IoT)",
    "e8:31:cd": "Espressif (IoT)",
    "ec:fa:bc": "Espressif (IoT)",
    "f0:08:d1": "Tuya Smart",
    "10:5a:17": "Tuya Smart",
    "70:89:76": "Tuya Smart",
    "d8:1f:12": "Tuya Smart",
    "00:03:93": "Apple",
    "00:05:02": "Apple",
    "00:0a:27": "Apple",
    "00:0a:95": "Apple",
    "00:0d:93": "Apple",
    "00:10:fa": "Apple",
    "00:11:24": "Apple",
    "00:14:51": "Apple",
    "00:17:f2": "Apple",
    "00:19:e3": "Apple",
    "00:1b:63": "Apple",
    "00:1c:b3": "Apple",
    "00:1d:4f": "Apple",
    "00:1e:52": "Apple",
    "00:1e:c2": "Apple",
    "00:21:e9": "Apple",
    "00:22:41": "Apple",
    "00:23:12": "Apple",
    "00:23:32": "Apple",
    "00:23:6c": "Apple",
    "00:24:36": "Apple",
    "00:25:00": "Apple",
    "00:25:4b": "Apple",
    "00:25:bc": "Apple",
    "00:26:08": "Apple",
    "00:26:4a": "Apple",
    "00:26:b0": "Apple",
    "00:26:bb": "Apple",
    "14:7d:da": "Apple",
    "38:f9:d3": "Apple",
    "8c:85:90": "Apple",
    "a4:83:e7": "Apple",
    "ac:bc:32": "Apple",
    "bc:fe:d9": "Apple",
    "f0:18:98": "Apple",
    "f4:f1:5a": "Apple",
    "00:07:ab": "Samsung",
    "00:12:fb": "Samsung",
    "00:15:99": "Samsung",
    "00:16:32": "Samsung",
    "00:17:c8": "Samsung",
    "00:1a:8a": "Samsung",
    "00:1d:25": "Samsung",
    "00:21:19": "Samsung",
    "00:23:39": "Samsung",
    "00:23:d7": "Samsung",
    "00:24:54": "Samsung",
    "00:26:37": "Samsung",
    "08:08:c2": "Samsung",
    "14:49:e0": "Samsung",
    "28:18:78": "Samsung",
    "34:c3:ac": "Samsung",
    "50:85:69": "Samsung",
    "78:47:1d": "Samsung",
    "94:65:2d": "Samsung",
    "a8:06:00": "Samsung",
    "cc:07:ab": "Samsung",
    "d0:22:be": "Samsung",
    "00:1d:0f": "TP-Link",
    "00:21:27": "TP-Link",
    "00:23:cd": "TP-Link",
    "00:25:86": "TP-Link",
    "14:cc:20": "TP-Link",
    "1c:3b:f3": "TP-Link",
    "30:b5:c2": "TP-Link",
    "50:c7:bf": "TP-Link",
    "60:e3:27": "TP-Link",
    "64:70:02": "TP-Link",
    "70:4f:57": "TP-Link",
    "74:ea:3a": "TP-Link",
    "84:16:f9": "TP-Link",
    "90:f6:52": "TP-Link",
    "a0:f3:c1": "TP-Link",
    "c0:4a:00": "TP-Link",
    "d8:07:b6": "TP-Link",
    "ec:08:6b": "TP-Link",
    "00:9e:c8": "Xiaomi",
    "14:f6:5a": "Xiaomi",
    "28:6c:07": "Xiaomi",
    "34:80:62": "Xiaomi",
    "58:44:98": "Xiaomi",
    "64:09:80": "Xiaomi",
    "74:51:ba": "Xiaomi",
    "7c:49:eb": "Xiaomi",
    "88:c3:97": "Xiaomi",
    "ac:c1:ee": "Xiaomi",
    "d4:97:0b": "Xiaomi",
    "00:02:b3": "Intel",
    "00:03:47": "Intel",
    "00:04:23": "Intel",
    "00:0e:0c": "Intel",
    "00:13:02": "Intel",
    "00:15:00": "Intel",
    "00:16:76": "Intel",
    "00:19:d1": "Intel",
    "00:1b:21": "Intel",
    "00:1c:c0": "Intel",
    "00:1e:67": "Intel",
    "00:21:6a": "Intel",
    "00:23:14": "Intel",
    "00:24:d7": "Intel",
    "08:11:96": "Intel",
    "34:13:e8": "Intel",
    "68:05:ca": "Intel",
    "a4:4c:c8": "Intel",
    "00:0c:42": "MikroTik",
    "2c:c8:1b": "MikroTik",
    "48:8f:5a": "MikroTik",
    "64:d1:54": "MikroTik",
    "b8:69:f4": "MikroTik",
    "c4:ad:34": "MikroTik",
    "cc:2d:e0": "MikroTik",
    "d4:01:c3": "MikroTik",
    "e4:8d:8c": "MikroTik",
    "00:18:82": "Huawei",
    "00:1e:10": "Huawei",
    "00:25:68": "Huawei",
    "00:46:4b": "Huawei",
    "0c:37:dc": "Huawei",
    "20:0b:c7": "Huawei",
    "24:df:6a": "Huawei",
    "48:46:fb": "Huawei",
    "70:72:3c": "Huawei",
    "00:1a:11": "Google",
    "1c:56:fe": "Google",
    "20:df:b9": "Google",
    "3c:5a:37": "Google",
    "54:60:09": "Google",
    "94:eb:2c": "Google",
    "a4:77:33": "Google",
    "e4:f0:42": "Google",
    "00:04:1f": "Sony",
    "00:13:15": "Sony",
    "00:15:c1": "Sony",
    "00:19:c5": "Sony",
    "00:24:8d": "Sony",
    "00:d9:d1": "Sony",
    "04:76:6e": "Sony",
    "70:9e:29": "Sony",
    "a8:e3:ee": "Sony",
    "00:07:0e": "Realtek",
    "00:e0:4c": "Realtek",
    "52:54:4c": "Realtek",
    "00:40:63": "WonderMedia",
    "00:02:55": "VIA Technologies",
    "84:16:f9": "TP-Link",
    "e8:b1:fc": "Tuya Smart",
    "1c:90:ff": "Xiaomi Smart",
    "88:a2:9e": "TP-Link",
    "30:cc:21": "Brama domowa",
    "10:f0:05": "Apple",
}

CANARY_PORTS = [
    (21, "FTP"),
    (23, "Telnet"),
    (80, "HTTP"),
    (445, "SMB"),
    (3389, "RDP"),
    (5900, "VNC"),
    (8080, "HTTP-Alt"),
]


class SharedState:
    def __init__(self):
        self.lock = threading.RLock()
        self.active_tab = 0  # 0: Overview, 1: LAN Hosts, 2: IDS, 3: Alarm Log
        self.unread_warn = [0, 0, 0, 0]
        self.unread_alert = [0, 0, 0, 0]
        self.sound_muted = False
        self.flash_phase = False

        # Network & Connectivity
        self.iface = "wlan0"
        self.local_ip = "---"
        self.ssid = "---"
        self.bssid = "---"
        self.baseline_bssid = None
        self.wifi_dbm = -99
        self.wifi_pct = 0
        self.gateway_ip = "---"
        self.gateway_mac = "---"
        self.baseline_gateway_mac = None

        self.ping_gw_ms = -1.0
        self.ping_inet_ms = -1.0
        self.ping_dns_ms = -1.0
        self.packet_loss_pct = 0
        self.hist_gw = collections.deque([0.0] * 60, maxlen=60)
        self.hist_inet = collections.deque([0.0] * 60, maxlen=60)

        # System resources
        self.cpu_pct = 0.0
        self.ram_used_mb = 0
        self.ram_total_mb = 231
        self.zram_used_mb = 0
        self.zram_total_mb = 80
        self.bat_mv = 4050
        self.bat_pct = 90
        self.uptime_str = "0h 00m"

        # LAN Hosts: dict of mac -> {"ip": str, "mac": str, "known": bool, "last_seen": str, "vendor": str}
        self.lan_hosts = {}
        self.known_macs = set()
        self.host_names = {}
        self.selected_host_mac = None
        self.selected_host_index = 0
        self.last_arp_scan = "---"
        self.force_subnet_sweep = False

        # IDS status
        self.arp_spoof_detected = False
        self.arp_spoof_detail = "OK (MAC bramy stabilny)"
        self.arp_spoof_detail_l1 = "OK (Brama zweryfikowana)"
        self.arp_spoof_detail_l2 = "Brak kolizji i duplikatow MAC"
        self.evil_twin_detected = False
        self.evil_twin_detail = "OK (BSSID punktu dostepowego zgodny)"
        self.canary_stats = {
            port: {"name": name, "hits": 0, "last_ip": "---", "last_time": "---", "banner": ""}
            for port, name in CANARY_PORTS
        }

        # Security event log: list of dicts {"time", "level", "source", "msg"}
        self.event_log = collections.deque(maxlen=50)

        # Pointer / Touch feedback
        self.cursor_x = 400
        self.cursor_y = 240
        self.show_cursor = False


STATE = SharedState()


def lookup_device_info(mac: str, ip: str) -> str:
    mac_lower = mac.lower()
    with STATE.lock:
        gw_ip = STATE.gateway_ip
        loc_ip = STATE.local_ip
        hostname = STATE.host_names.get(ip, "")

    if ip == gw_ip and gw_ip != "---":
        return f"Router/Brama ({hostname})" if hostname else "Router domowy (Brama)"
    if ip == loc_ip and loc_ip != "---":
        return "WM8650 SOC (Ten tablet)"

    prefix = mac_lower[:8]
    vendor = OUI_DATABASE.get(prefix)
    if vendor:
        if hostname:
            return f"{vendor} ({hostname[:12]})"
        return vendor

    # Check for IEEE 802 Locally Administered / Private Randomized MAC (bit 1 of byte 0 set)
    try:
        b0 = int(mac_lower[:2], 16)
        if b0 & 0x02:
            return f"Smartfon ({hostname})" if hostname else "Smartfon / Tablet (Pryw. MAC)"
    except Exception:
        pass

    if hostname:
        return f"Host: {hostname[:16]}"
    return "Urzadzenie LAN"


def trigger_beep(mode: str):
    with STATE.lock:
        muted = STATE.sound_muted
    if muted and mode != "click":
        return
    if os.path.exists(BEEP_BIN):
        try:
            subprocess.Popen(
                [BEEP_BIN, mode],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def add_security_event(level: str, source: str, msg: str, target_tabs=()):
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    with STATE.lock:
        STATE.event_log.appendleft(
            {"time": now_str, "level": level, "source": source, "msg": msg}
        )
        for tab in target_tabs:
            if tab != STATE.active_tab and 0 <= tab < 4:
                if level == "ALERT":
                    STATE.unread_alert[tab] += 1
                elif level == "WARN":
                    STATE.unread_warn[tab] += 1

    if level == "ALERT":
        trigger_beep("alert")
    elif level == "WARN":
        trigger_beep("warn")


def load_known_hosts():
    try:
        if os.path.exists(KNOWN_HOSTS_FILE):
            with open(KNOWN_HOSTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                with STATE.lock:
                    STATE.known_macs = set(m.lower() for m in data.get("known_macs", []))
    except Exception:
        pass


def save_known_hosts():
    try:
        os.makedirs(os.path.dirname(KNOWN_HOSTS_FILE), exist_ok=True)
        with STATE.lock:
            macs = sorted(list(STATE.known_macs))
        with open(KNOWN_HOSTS_FILE, "w", encoding="utf-8") as f:
            json.dump({"known_macs": macs}, f, indent=2)
    except Exception:
        pass


def approve_all_current_hosts():
    with STATE.lock:
        for mac, info in STATE.lan_hosts.items():
            STATE.known_macs.add(mac.lower())
            info["known"] = True
        STATE.unread_warn[1] = 0
    save_known_hosts()
    add_security_event("INFO", "LAN", "Zatwierdzono wszystkie widoczne hosty LAN jako ZNANE", ())
    trigger_beep("click")
    REDRAW_EVENT.set()


def toggle_host_known(mac: str):
    if not mac:
        return
    mac_lower = mac.lower()
    with STATE.lock:
        if mac_lower in STATE.known_macs:
            STATE.known_macs.discard(mac_lower)
            if mac_lower in STATE.lan_hosts:
                STATE.lan_hosts[mac_lower]["known"] = False
            ev_msg = f"Oznaczono urzadzenie {mac} jako NIEZNANE"
        else:
            STATE.known_macs.add(mac_lower)
            if mac_lower in STATE.lan_hosts:
                STATE.lan_hosts[mac_lower]["known"] = True
            ev_msg = f"Zatwierdzono urzadzenie {mac} jako ZNANE"
    save_known_hosts()
    add_security_event("INFO", "LAN", ev_msg, ())
    trigger_beep("click")
    REDRAW_EVENT.set()


RESOLVE_QUEUE = collections.deque()
RESOLVE_SEEN = set()


def queue_hostname_resolve(ip: str):
    if not ip or ip == "---" or ip in RESOLVE_SEEN:
        return
    RESOLVE_SEEN.add(ip)
    RESOLVE_QUEUE.append(ip)


def dns_resolver_worker():
    while True:
        ip = None
        if RESOLVE_QUEUE:
            ip = RESOLVE_QUEUE.popleft()
        if ip:
            try:
                name, _, _ = socket.gethostbyaddr(ip)
                if name:
                    clean = name.strip()
                    if not clean.replace(".", "").isdigit() and clean != ip:
                        short = clean.split(".")[0]
                        if short and not short.isdigit():
                            with STATE.lock:
                                STATE.host_names[ip] = short
                            REDRAW_EVENT.set()
            except Exception:
                pass
        time.sleep(0.5)


def acknowledge_all_alarms():
    with STATE.lock:
        for i in range(4):
            STATE.unread_warn[i] = 0
            STATE.unread_alert[i] = 0
        STATE.arp_spoof_detected = False
        STATE.evil_twin_detected = False
    add_security_event("INFO", "SOC", "Potwierdzono i wyciszono aktywne alarmy IDS", ())
    trigger_beep("click")


def switch_to_terminal():
    trigger_beep("click")
    try:
        subprocess.run(["chvt", "1"], check=False)
    except Exception:
        pass


def ping_host(ip: str) -> float:
    if not ip or ip == "---":
        return -1.0
    try:
        out = subprocess.check_output(
            ["ping", "-c", "1", "-W", "1", ip],
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        )
        m = re.search(r"time=([0-9.]+)\s*ms", out)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return -1.0


def monitor_ping_and_system_loop():
    prev_total = 0
    prev_idle = 0
    while True:
        try:
            # 1. CPU usage from /proc/stat
            with open("/proc/stat", "r") as f:
                parts = [int(x) for x in f.readline().split()[1:8]]
            idle = parts[3] + parts[4]
            total = sum(parts)
            diff_total = total - prev_total
            diff_idle = idle - prev_idle
            cpu_pct = 100.0 * (diff_total - diff_idle) / max(1, diff_total)
            prev_total, prev_idle = total, idle

            # 2. Memory & ZRAM from /proc/meminfo
            mem = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0])
            ram_total = max(1, mem.get("MemTotal", 236544) // 1024)
            ram_avail = mem.get("MemAvailable", mem.get("MemFree", 180000)) // 1024
            ram_used = max(0, ram_total - ram_avail)
            swap_total = mem.get("SwapTotal", 81920) // 1024
            swap_free = mem.get("SwapFree", 81920) // 1024
            swap_used = max(0, swap_total - swap_free)

            # 3. Uptime
            with open("/proc/uptime", "r") as f:
                up_sec = int(float(f.read().split()[0]))
            uptime_str = f"{up_sec // 3600}h {(up_sec % 3600) // 60:02d}m"

            # 4. Battery from /run/wm8650_battery.txt
            bat_mv, bat_pct = 4050, 90
            if os.path.exists(BATTERY_FILE):
                try:
                    with open(BATTERY_FILE, "r") as bf:
                        bparts = bf.read().split()
                        if len(bparts) >= 2:
                            bat_mv = int(bparts[0])
                            bat_pct = int(bparts[1])
                except Exception:
                    pass

            # 5. Active IP & Gateway
            iface = "wlan0"
            local_ip = "---"
            try:
                ip_out = subprocess.check_output(
                    ["ip", "-4", "-o", "addr", "show"], universal_newlines=True
                )
                for line in ip_out.splitlines():
                    cols = line.split()
                    if len(cols) >= 4 and cols[1] != "lo":
                        iface = cols[1]
                        local_ip = cols[3].split("/")[0]
                        if iface == "wlan0":
                            break
            except Exception:
                pass

            gw_ip = "---"
            try:
                rt_out = subprocess.check_output(
                    ["ip", "route", "show", "default"], universal_newlines=True
                )
                m = re.search(r"default via ([0-9.]+)", rt_out)
                if m:
                    gw_ip = m.group(1)
            except Exception:
                pass

            # 6. Wi-Fi Signal, SSID, BSSID
            wifi_dbm = -99
            wifi_pct = 0
            ssid = "---"
            bssid = "---"
            try:
                with open("/proc/net/wireless", "r") as wf:
                    for line in wf:
                        if "wlan0:" in line:
                            wcols = line.split()
                            qual = float(wcols[2].rstrip("."))
                            lvl = float(wcols[3].rstrip("."))
                            wifi_dbm = int(lvl) if lvl < 0 else int(lvl - 256)
                            wifi_pct = max(0, min(100, int(qual * 100 / 70.0)))
                iw_out = subprocess.check_output(
                    ["iwgetid", "wlan0", "-r"],
                    stderr=subprocess.DEVNULL,
                    universal_newlines=True,
                ).strip()
                if iw_out:
                    ssid = iw_out
                ap_out = subprocess.check_output(
                    ["iwgetid", "wlan0", "-a", "-r"],
                    stderr=subprocess.DEVNULL,
                    universal_newlines=True,
                ).strip()
                if ap_out:
                    bssid = ap_out.lower()
            except Exception:
                pass

            # Check Wi-Fi Evil Twin (BSSID change on same SSID)
            evil_alert = False
            with STATE.lock:
                if bssid != "---" and bssid != "00:00:00:00:00:00":
                    if STATE.baseline_bssid is None:
                        STATE.baseline_bssid = bssid
                    elif bssid != STATE.baseline_bssid:
                        STATE.evil_twin_detected = True
                        STATE.evil_twin_detail = f"ZMIANA BSSID! Byl: {STATE.baseline_bssid}, jest: {bssid}"
                        evil_alert = True
            if evil_alert:
                add_security_event(
                    "ALERT",
                    "WIFI",
                    f"Wykryto zmiane BSSID AP ({bssid}) dla sieci {ssid}!",
                    target_tabs=(2, 3),
                )

            # 7. Pings
            p_gw = ping_host(gw_ip)
            p_inet = ping_host("1.1.1.1")
            p_dns = ping_host("8.8.8.8")

            with STATE.lock:
                STATE.cpu_pct = cpu_pct
                STATE.ram_used_mb = ram_used
                STATE.ram_total_mb = ram_total
                STATE.zram_used_mb = swap_used
                STATE.zram_total_mb = max(1, swap_total)
                STATE.uptime_str = uptime_str
                STATE.bat_mv = bat_mv
                STATE.bat_pct = bat_pct
                STATE.iface = iface
                STATE.local_ip = local_ip
                STATE.gateway_ip = gw_ip
                STATE.ssid = ssid
                STATE.bssid = bssid
                STATE.wifi_dbm = wifi_dbm
                STATE.wifi_pct = wifi_pct
                STATE.ping_gw_ms = p_gw
                STATE.ping_inet_ms = p_inet
                STATE.ping_dns_ms = p_dns
                STATE.hist_gw.append(p_gw)
                STATE.hist_inet.append(p_inet)
                losses = sum(1 for x in STATE.hist_inet if x < 0)
                STATE.packet_loss_pct = int(losses * 100 / max(1, len(STATE.hist_inet)))
        except Exception:
            pass

        time.sleep(2.0)


def trigger_udp_subnet_sweep(local_ip: str):
    if not local_ip or local_ip == "---" or "." not in local_ip:
        return
    prefix = ".".join(local_ip.split(".")[:3])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    for host_id in range(1, 255):
        target = f"{prefix}.{host_id}"
        if target == local_ip:
            continue
        try:
            sock.sendto(b"\x00", (target, 9))
        except Exception:
            pass
    sock.close()


def lan_and_arp_guard_loop():
    load_known_hosts()
    last_sweep = 0.0
    first_run = True
    last_arp_alert_msg = None

    while True:
        try:
            now = time.time()
            with STATE.lock:
                local_ip = STATE.local_ip
                gw_ip = STATE.gateway_ip
                force_sweep = STATE.force_subnet_sweep
                STATE.force_subnet_sweep = False

            if force_sweep or (now - last_sweep >= 60.0 and local_ip != "---"):
                trigger_udp_subnet_sweep(local_ip)
                last_sweep = now
                time.sleep(1.2)

            arp_entries = []
            with open("/proc/net/arp", "r") as f:
                lines = f.readlines()[1:]
            for line in lines:
                cols = line.split()
                if len(cols) >= 6:
                    ip_addr, hw_type, flags, mac, mask, dev = cols[:6]
                    mac = mac.lower()
                    if flags != "0x0" and mac != "00:00:00:00:00:00":
                        arp_entries.append((ip_addr, mac, dev))

            now_hm = datetime.datetime.now().strftime("%H:%M:%S")
            new_hosts_found = []
            arp_spoof_msg = None

            with STATE.lock:
                # If known_macs is completely empty on very first boot, seed with initial ARP table
                if first_run and not STATE.known_macs and arp_entries:
                    for _, mac, _ in arp_entries:
                        STATE.known_macs.add(mac)
                    save_known_hosts()
                first_run = False

                mac_to_ip = {}
                for ip_addr, mac, _ in arp_entries:
                    queue_hostname_resolve(ip_addr)

                    if mac in mac_to_ip and mac_to_ip[mac] != ip_addr:
                        ip1 = mac_to_ip[mac]
                        ip2 = ip_addr
                        arp_spoof_msg = f"Duplikat MAC {mac} na IP {ip1} oraz {ip2}"
                        STATE.arp_spoof_detail_l1 = f"Duplikat MAC: {mac}"
                        STATE.arp_spoof_detail_l2 = f"IP: {ip1} oraz {ip2}"
                    mac_to_ip[mac] = ip_addr

                    if ip_addr == gw_ip:
                        STATE.gateway_mac = mac
                        if STATE.baseline_gateway_mac is None:
                            STATE.baseline_gateway_mac = mac
                        elif mac != STATE.baseline_gateway_mac:
                            arp_spoof_msg = (
                                f"Zmiana MAC bramy {gw_ip}! Poprzedni: {STATE.baseline_gateway_mac}, nowy: {mac}"
                            )
                            STATE.arp_spoof_detail_l1 = f"Zmiana MAC bramy {gw_ip}!"
                            STATE.arp_spoof_detail_l2 = f"Byl: {STATE.baseline_gateway_mac} -> {mac}"

                    is_known = mac in STATE.known_macs
                    prev = STATE.lan_hosts.get(mac)
                    if prev is None and not is_known:
                        new_hosts_found.append((ip_addr, mac))
                    vendor_str = lookup_device_info(mac, ip_addr)
                    STATE.lan_hosts[mac] = {
                        "ip": ip_addr,
                        "mac": mac,
                        "known": is_known,
                        "last_seen": now_hm,
                        "vendor": vendor_str,
                    }

                STATE.last_arp_scan = now_hm
                if arp_spoof_msg:
                    STATE.arp_spoof_detected = True
                    STATE.arp_spoof_detail = arp_spoof_msg
                else:
                    STATE.arp_spoof_detected = False
                    STATE.arp_spoof_detail = "OK (MAC bramy stabilny)"
                    STATE.arp_spoof_detail_l1 = "OK (Brama zweryfikowana)"
                    STATE.arp_spoof_detail_l2 = "Brak kolizji i duplikatow MAC"

            if arp_spoof_msg != last_arp_alert_msg:
                if arp_spoof_msg:
                    add_security_event("ALERT", "ARP-GUARD", arp_spoof_msg, target_tabs=(2, 3))
                last_arp_alert_msg = arp_spoof_msg

            for ip_addr, mac in new_hosts_found:
                add_security_event(
                    "WARN",
                    "LAN-HOST",
                    f"Nowe urzadzenie w sieci LAN: IP {ip_addr} (MAC {mac})",
                    target_tabs=(1, 3),
                )

        except Exception:
            pass

        time.sleep(8.0)


def canary_honeypot_loop():
    listeners = {}
    for port, name in CANARY_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setblocking(False)
            s.bind(("0.0.0.0", port))
            s.listen(5)
            listeners[s] = (port, name)
        except Exception as e:
            add_security_event("INFO", "HONEYPOT", f"Port {port}/{name} pominiety ({e})", ())

    if not listeners:
        return

    while True:
        try:
            readable, _, _ = select.select(list(listeners.keys()), [], [], 1.0)
            for s in readable:
                port, name = listeners[s]
                try:
                    conn, addr = s.accept()
                    peer_ip = addr[0]
                    conn.settimeout(0.25)
                    banner = ""
                    try:
                        data = conn.recv(64)
                        if data:
                            banner = data.decode("latin1", errors="replace").strip()[:32]
                    except Exception:
                        pass
                    conn.close()

                    now_hm = datetime.datetime.now().strftime("%H:%M:%S")
                    with STATE.lock:
                        st = STATE.canary_stats[port]
                        st["hits"] += 1
                        st["last_ip"] = peer_ip
                        st["last_time"] = now_hm
                        if banner:
                            st["banner"] = banner

                    add_security_event(
                        "ALERT",
                        f"PORT-{port}",
                        f"Skanowanie/polaczenie na port {port} ({name}) z IP {peer_ip}!",
                        target_tabs=(2, 3),
                    )
                except Exception:
                    pass
        except Exception:
            time.sleep(1.0)


def handle_click(x: int, y: int):
    # If user is currently in Linux text console (tty1/tty2) and taps the top bar,
    # switch back to the graphical dashboard (tty3) so keyboard is not required to return!
    if not is_dashboard_vt_active():
        if y < 70:
            trigger_beep("click")
            try:
                subprocess.run(["chvt", "3"], check=False)
            except Exception:
                pass
        return

    # Check if Device Detail Modal is open
    with STATE.lock:
        sel_mac = STATE.selected_host_mac
        tab = STATE.active_tab

    if sel_mac is not None:
        # Modal Box coordinates: [120, 75, 680, 420]
        # Toggle button: [140, 355, 385, 405]
        # Close button: [440, 355, 660, 405]
        if 350 <= y <= 410 and 140 <= x <= 390:
            toggle_host_known(sel_mac)
            return
        elif (350 <= y <= 410 and 430 <= x <= 670) or not (120 <= x <= 680 and 75 <= y <= 420):
            with STATE.lock:
                STATE.selected_host_mac = None
            trigger_beep("click")
            REDRAW_EVENT.set()
            return
        return

    # Top navigation bar (height ~56 px, generous touch hit area up to 70 px, 5 tabs x 160 px)
    if y < 70:
        tab_idx = min(4, max(0, x // 160))
        if tab_idx == 4:
            switch_to_terminal()
            return
        with STATE.lock:
            STATE.active_tab = tab_idx
            STATE.selected_host_mac = None
            STATE.unread_warn[tab_idx] = 0
            STATE.unread_alert[tab_idx] = 0
        trigger_beep("click")
        REDRAW_EVENT.set()
        return

    # Tab 2 (LAN Hosts): Row clicks to inspect device
    if tab == 1:
        if 140 <= y < 410:
            row_idx = (y - 140) // 27
            with STATE.lock:
                hosts_sorted = sorted(
                    STATE.lan_hosts.values(),
                    key=lambda h: (h["known"], h["ip"]),
                )
                if 0 <= row_idx < len(hosts_sorted):
                    STATE.selected_host_mac = hosts_sorted[row_idx]["mac"]
                    STATE.selected_host_index = row_idx
                    trigger_beep("click")
                    REDRAW_EVENT.set()
                    return

    # Bottom action bar buttons (y >= 418)
    if y >= 418:
        if tab == 1:
            if x < 400:
                approve_all_current_hosts()
            else:
                with STATE.lock:
                    STATE.force_subnet_sweep = True
                add_security_event("INFO", "LAN", "Wymuszono skanowanie podsieci LAN", ())
                trigger_beep("click")
                REDRAW_EVENT.set()
        elif tab in (2, 3):
            if x < 480:
                acknowledge_all_alarms()
            else:
                with STATE.lock:
                    STATE.sound_muted = not STATE.sound_muted
                trigger_beep("click")
                REDRAW_EVENT.set()


def _handle_evdev_key(code: int):
    # Standard Linux evdev keycodes:
    # 2=1, 3=2, 4=3, 5=4, 6=5
    # 1=ESC, 45=X, 28=ENTER, 57=SPACE, 30=A, 44=Z, 24=O, 31=S, 46=C, 50=M, 15=TAB
    # 103=UP, 108=DOWN, 20=T, 37=K, 36=J
    if code in (2, 3, 4, 5):
        idx = code - 2
        with STATE.lock:
            STATE.active_tab = idx
            STATE.selected_host_mac = None
            STATE.unread_warn[idx] = 0
            STATE.unread_alert[idx] = 0
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif code in (6, 20):  # 5 or T
        switch_to_terminal()
    elif code in (1, 45):  # ESC or X
        with STATE.lock:
            if STATE.selected_host_mac is not None:
                STATE.selected_host_mac = None
                REDRAW_EVENT.set()
                trigger_beep("click")
                return
        if code == 1:
            switch_to_terminal()
    elif code in (103, 37):  # UP or K
        with STATE.lock:
            STATE.selected_host_index = max(0, STATE.selected_host_index - 1)
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif code in (108, 36):  # DOWN or J
        with STATE.lock:
            total_h = len(STATE.lan_hosts)
            STATE.selected_host_index = min(max(0, total_h - 1), STATE.selected_host_index + 1)
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif code in (28, 57):  # ENTER or SPACE
        with STATE.lock:
            sel_m = STATE.selected_host_mac
            cur_tab = STATE.active_tab
        if cur_tab == 1:
            if sel_m is not None:
                toggle_host_known(sel_m)
            else:
                with STATE.lock:
                    hosts_s = sorted(
                        STATE.lan_hosts.values(),
                        key=lambda h: (h["known"], h["ip"]),
                    )
                    s_idx = STATE.selected_host_index
                    if 0 <= s_idx < len(hosts_s):
                        STATE.selected_host_mac = hosts_s[s_idx]["mac"]
                        REDRAW_EVENT.set()
                        trigger_beep("click")
    elif code in (44, 24):  # Z or O
        with STATE.lock:
            sel_m = STATE.selected_host_mac
            if sel_m is None and STATE.lan_hosts:
                hosts_s = sorted(
                    STATE.lan_hosts.values(),
                    key=lambda h: (h["known"], h["ip"]),
                )
                s_idx = STATE.selected_host_index
                if 0 <= s_idx < len(hosts_s):
                    sel_m = hosts_s[s_idx]["mac"]
        if sel_m:
            toggle_host_known(sel_m)
    elif code == 30:  # A
        approve_all_current_hosts()
    elif code == 31:  # S
        with STATE.lock:
            STATE.force_subnet_sweep = True
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif code == 46:  # C
        acknowledge_all_alarms()
        REDRAW_EVENT.set()
    elif code == 50:  # M
        with STATE.lock:
            STATE.sound_muted = not STATE.sound_muted
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif code == 15:  # TAB
        with STATE.lock:
            STATE.active_tab = (STATE.active_tab + 1) % 4
            STATE.selected_host_mac = None
            idx = STATE.active_tab
            STATE.unread_warn[idx] = 0
            STATE.unread_alert[idx] = 0
        trigger_beep("click")
        REDRAW_EVENT.set()


def input_reader_loop():
    # 1. UDP socket for VT1609 touchscreen daemon (127.0.0.1:9999)
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.setblocking(False)
    try:
        udp_sock.bind(("127.0.0.1", 9999))
    except Exception:
        pass

    # 2. Legacy mouse device (/dev/input/mice) if present
    mouse_fd = None
    if os.path.exists("/dev/input/mice"):
        try:
            mouse_fd = os.open("/dev/input/mice", os.O_RDONLY | os.O_NONBLOCK)
        except Exception:
            mouse_fd = None

    # 3. Virtual terminal keyboard on /dev/tty3
    tty_fd = None
    old_term = None
    if os.path.exists("/dev/tty3"):
        try:
            tty_fd = os.open("/dev/tty3", os.O_RDONLY | os.O_NONBLOCK)
            old_term = termios.tcgetattr(tty_fd)
            tty.setcbreak(tty_fd)
        except Exception:
            tty_fd = None

    # 4. Modern Linux evdev devices (/dev/input/event*) for USB/wireless mice, keyboards, touchscreens
    evdev_fds = {}  # path -> fd
    last_evdev_scan = 0.0
    last_mouse_redraw = 0.0
    EV_FORMAT = "llHHi"
    EV_SIZE = struct.calcsize(EV_FORMAT)

    try:
        while True:
            now = time.time()
            if now - last_evdev_scan >= 3.0:
                last_evdev_scan = now
                current_devs = set(glob.glob("/dev/input/event*"))
                for path in list(evdev_fds.keys()):
                    if path not in current_devs:
                        try:
                            os.close(evdev_fds[path])
                        except Exception:
                            pass
                        del evdev_fds[path]
                for path in current_devs:
                    if path not in evdev_fds:
                        try:
                            evdev_fds[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                        except Exception:
                            pass

            rlist = [udp_sock]
            if mouse_fd is not None:
                rlist.append(mouse_fd)
            if tty_fd is not None:
                rlist.append(tty_fd)
            rlist.extend(evdev_fds.values())

            readable, _, _ = select.select(rlist, [], [], 0.2)
            for r in readable:
                if r == udp_sock:
                    try:
                        data, _ = udp_sock.recvfrom(128)
                        text = data.decode("ascii", errors="ignore").strip()
                        parts = text.split()
                        if len(parts) >= 3 and parts[0] == "TOUCH":
                            tx = int(parts[1])
                            ty = int(parts[2])
                            with STATE.lock:
                                STATE.cursor_x = tx
                                STATE.cursor_y = ty
                                STATE.show_cursor = True
                            handle_click(tx, ty)
                    except Exception:
                        pass

                elif mouse_fd is not None and r == mouse_fd:
                    try:
                        buf = os.read(mouse_fd, 3)
                        if len(buf) == 3 and not evdev_fds:
                            btns = buf[0]
                            dx = struct.unpack("b", bytes([buf[1]]))[0]
                            dy = struct.unpack("b", bytes([buf[2]]))[0]
                            with STATE.lock:
                                STATE.cursor_x = max(0, min(799, STATE.cursor_x + dx))
                                STATE.cursor_y = max(0, min(479, STATE.cursor_y - dy))
                                STATE.show_cursor = True
                                cx, cy = STATE.cursor_x, STATE.cursor_y
                            if btns & 0x01:
                                handle_click(cx, cy)
                            else:
                                now_m = time.time()
                                if now_m - last_mouse_redraw >= 0.1:
                                    last_mouse_redraw = now_m
                                    REDRAW_EVENT.set()
                    except Exception:
                        pass

                elif r in evdev_fds.values():
                    try:
                        buf = os.read(r, EV_SIZE * 16)
                        for offset in range(0, len(buf) - EV_SIZE + 1, EV_SIZE):
                            _, _, ev_type, ev_code, ev_val = struct.unpack(EV_FORMAT, buf[offset : offset + EV_SIZE])
                            if ev_type == 2:  # EV_REL (Mouse relative movement & wheel)
                                if ev_code == 0:  # REL_X
                                    with STATE.lock:
                                        STATE.cursor_x = max(0, min(799, STATE.cursor_x + ev_val))
                                        STATE.show_cursor = True
                                    now_m = time.time()
                                    if now_m - last_mouse_redraw >= 0.1:
                                        last_mouse_redraw = now_m
                                        REDRAW_EVENT.set()
                                elif ev_code == 1:  # REL_Y
                                    with STATE.lock:
                                        STATE.cursor_y = max(0, min(479, STATE.cursor_y + ev_val))
                                        STATE.show_cursor = True
                                    now_m = time.time()
                                    if now_m - last_mouse_redraw >= 0.1:
                                        last_mouse_redraw = now_m
                                        REDRAW_EVENT.set()
                                elif ev_code == 8:  # REL_WHEEL
                                    with STATE.lock:
                                        if ev_val > 0:
                                            STATE.selected_host_index = max(0, STATE.selected_host_index - 1)
                                        elif ev_val < 0:
                                            total_h = len(STATE.lan_hosts)
                                            STATE.selected_host_index = min(max(0, total_h - 1), STATE.selected_host_index + 1)
                                    trigger_beep("click")
                                    REDRAW_EVENT.set()
                            elif ev_type == 1:  # EV_KEY (Buttons & Keys)
                                if ev_code in (272, 330):  # BTN_LEFT or BTN_TOUCH
                                    if ev_val == 1:  # Pressed
                                        with STATE.lock:
                                            cx, cy = STATE.cursor_x, STATE.cursor_y
                                        handle_click(cx, cy)
                                elif ev_code == 273:  # BTN_RIGHT
                                    if ev_val == 1:
                                        with STATE.lock:
                                            if STATE.selected_host_mac is not None:
                                                STATE.selected_host_mac = None
                                                trigger_beep("click")
                                                REDRAW_EVENT.set()
                                elif ev_val == 1:  # Keyboard key pressed
                                    _handle_evdev_key(ev_code)
                            elif ev_type == 3:  # EV_ABS (Absolute touchscreen coords)
                                if ev_code == 0:  # ABS_X
                                    with STATE.lock:
                                        STATE.cursor_x = max(0, min(799, ev_val))
                                        STATE.show_cursor = True
                                elif ev_code == 1:  # ABS_Y
                                    with STATE.lock:
                                        STATE.cursor_y = max(0, min(479, ev_val))
                                        STATE.show_cursor = True
                    except (OSError, IOError):
                        for p, f in list(evdev_fds.items()):
                            if f == r:
                                try:
                                    os.close(f)
                                except Exception:
                                    pass
                                del evdev_fds[p]

                elif r == tty_fd:
                    try:
                        seq = os.read(tty_fd, 16).decode("ascii", errors="ignore")
                        if not seq:
                            continue

                        # Handle escape sequences (Arrows)
                        if seq == "\x1b[A" or seq == "k" or seq == "K":  # Up arrow
                            with STATE.lock:
                                STATE.selected_host_index = max(0, STATE.selected_host_index - 1)
                            trigger_beep("click")
                            REDRAW_EVENT.set()
                            continue
                        elif seq == "\x1b[B" or seq == "j" or seq == "J":  # Down arrow
                            with STATE.lock:
                                total_h = len(STATE.lan_hosts)
                                STATE.selected_host_index = min(max(0, total_h - 1), STATE.selected_host_index + 1)
                            trigger_beep("click")
                            REDRAW_EVENT.set()
                            continue

                        c = seq[0]
                        if seq == "\x1b" or c in ("x", "X"):  # ESC or X
                            with STATE.lock:
                                if STATE.selected_host_mac is not None:
                                    STATE.selected_host_mac = None
                                    REDRAW_EVENT.set()
                                    trigger_beep("click")
                                    continue
                            if seq == "\x1b":
                                switch_to_terminal()
                            continue

                        if c in ("1", "2", "3", "4"):
                            idx = int(c) - 1
                            with STATE.lock:
                                STATE.active_tab = idx
                                STATE.selected_host_mac = None
                                STATE.unread_warn[idx] = 0
                                STATE.unread_alert[idx] = 0
                            trigger_beep("click")
                            REDRAW_EVENT.set()
                        elif c in ("5", "t", "T"):
                            switch_to_terminal()
                        elif c in ("\r", "\n", " "):  # Enter or Space
                            with STATE.lock:
                                sel_m = STATE.selected_host_mac
                                cur_tab = STATE.active_tab
                            if cur_tab == 1:
                                if sel_m is not None:
                                    toggle_host_known(sel_m)
                                else:
                                    with STATE.lock:
                                        hosts_s = sorted(
                                            STATE.lan_hosts.values(),
                                            key=lambda h: (h["known"], h["ip"]),
                                        )
                                        s_idx = STATE.selected_host_index
                                        if 0 <= s_idx < len(hosts_s):
                                            STATE.selected_host_mac = hosts_s[s_idx]["mac"]
                                            REDRAW_EVENT.set()
                                            trigger_beep("click")
                        elif c in ("z", "Z", "o", "O"):
                            with STATE.lock:
                                sel_m = STATE.selected_host_mac
                                if sel_m is None and STATE.lan_hosts:
                                    hosts_s = sorted(
                                        STATE.lan_hosts.values(),
                                        key=lambda h: (h["known"], h["ip"]),
                                    )
                                    s_idx = STATE.selected_host_index
                                    if 0 <= s_idx < len(hosts_s):
                                        sel_m = hosts_s[s_idx]["mac"]
                            if sel_m:
                                toggle_host_known(sel_m)
                        elif c in ("a", "A"):
                            approve_all_current_hosts()
                        elif c in ("s", "S"):
                            with STATE.lock:
                                STATE.force_subnet_sweep = True
                            trigger_beep("click")
                            REDRAW_EVENT.set()
                        elif c in ("c", "C"):
                            acknowledge_all_alarms()
                            REDRAW_EVENT.set()
                        elif c in ("m", "M"):
                            with STATE.lock:
                                STATE.sound_muted = not STATE.sound_muted
                            trigger_beep("click")
                            REDRAW_EVENT.set()
                        elif c == "\t":
                            with STATE.lock:
                                STATE.active_tab = (STATE.active_tab + 1) % 4
                                STATE.selected_host_mac = None
                                idx = STATE.active_tab
                                STATE.unread_warn[idx] = 0
                                STATE.unread_alert[idx] = 0
                            trigger_beep("click")
                            REDRAW_EVENT.set()
                    except Exception:
                        pass
    finally:
        if tty_fd is not None and old_term is not None:
            try:
                termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_term)
            except Exception:
                pass
        for f in list(evdev_fds.values()):
            try:
                os.close(f)
            except Exception:
                pass


def is_dashboard_vt_active() -> bool:
    try:
        with open(ACTIVE_TTY_PATH, "r") as f:
            return f.read().strip() == DASHBOARD_TTY
    except Exception:
        return True


def image_to_rgb565_bytes(img: Image.Image) -> bytes:
    try:
        return img.tobytes("raw", "BGR;16")
    except Exception:
        # Pure-Python fallback if Pillow raw BGR;16 packer is unavailable
        raw = img.tobytes()
        out = bytearray(FB_WIDTH * FB_HEIGHT * 2)
        idx = 0
        for i in range(0, len(raw), 3):
            r = raw[i]
            g = raw[i + 1]
            b = raw[i + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[idx] = v & 0xFF
            out[idx + 1] = (v >> 8) & 0xFF
            idx += 2
        return bytes(out)


def load_fonts():
    # Use fast bitmap fonts: ARM926EJ-S lacks hardware FPU, FreeType TTF takes 3.1s / 50 lines.
    # Built-in bitmap font takes only ~6 ms per line and avoids 100% CPU lockup.
    default_f = ImageFont.load_default()
    return default_f, default_f, default_f


def render_frame(fonts) -> Image.Image:
    f_sm, f_md, f_lg = fonts
    img = Image.new("RGB", (FB_WIDTH, FB_HEIGHT), (11, 15, 25))
    d = ImageDraw.Draw(img)

    with STATE.lock:
        active_tab = STATE.active_tab
        unread_w = list(STATE.unread_warn)
        unread_a = list(STATE.unread_alert)
        flash = STATE.flash_phase
        STATE.flash_phase = not STATE.flash_phase
        muted = STATE.sound_muted

        # Draw Top Tab Bar (y = 0..54)
        tab_titles = [
            "[1] PRZEGLAD",
            "[2] HOSTY LAN",
            "[3] CZUJNIKI IDS",
            "[4] ALARM LOG",
            "[5] KONSOLA >_",
        ]
        for i, title in enumerate(tab_titles):
            x0 = i * 160 + 2
            x1 = (i + 1) * 160 - 2
            y0, y1 = 2, 52

            label = title
            if i < 4:
                if unread_a[i] > 0 and i != active_tab:
                    bg = (220, 38, 38) if flash else (127, 29, 29)
                    border = (255, 255, 255)
                    label = f"{title} (!!{unread_a[i]})"
                elif unread_w[i] > 0 and i != active_tab:
                    bg = (180, 83, 9)
                    border = (251, 191, 36)
                    label = f"{title} (!{unread_w[i]})"
                elif i == active_tab:
                    bg = (30, 58, 138)
                    border = (56, 189, 248)
                else:
                    bg = (30, 41, 59)
                    border = (71, 85, 105)
            else:
                bg = (15, 118, 110)
                border = (45, 212, 191)

            d.rectangle([x0, y0, x1, y1], fill=bg, outline=border, width=2)
            d.text((x0 + 8, y0 + 17), label, fill=(255, 255, 255), font=f_sm)

        # Determine overall security status
        total_alerts = sum(unread_a) + (1 if STATE.arp_spoof_detected or STATE.evil_twin_detected else 0)
        new_hosts_count = sum(1 for h in STATE.lan_hosts.values() if not h["known"])
        total_warns = sum(unread_w) + new_hosts_count

        if active_tab == 0:
            # ================= TAB 1: OVERVIEW =================
            if total_alerts > 0:
                b_bg = (185, 28, 28) if flash else (127, 29, 29)
                b_txt = "ALARM IDS! Wykryto atak lub skanowanie (Zakladki 3 i 4)"
            elif total_warns > 0 or STATE.packet_loss_pct > 15:
                b_bg = (180, 83, 9)
                b_txt = f"OSTRZEZENIE: Nowe hosty ({new_hosts_count}) / Loss {STATE.packet_loss_pct}%"
            else:
                b_bg = (21, 128, 61)
                b_txt = "STATUS SIECI: BEZPIECZNIE (Brak zagrozen IDS)"

            d.rectangle([12, 60, 788, 104], fill=b_bg, outline=(255, 255, 255), width=1)
            # Use smaller font if text is long to prevent overflowing
            if len(b_txt) > 42:
                d.text((22, 75), b_txt, fill=(255, 255, 255), font=f_sm)
            else:
                d.text((22, 73), b_txt, fill=(255, 255, 255), font=f_md)
            now_clock = datetime.datetime.now().strftime("%H:%M:%S")
            d.text((700, 73), now_clock, fill=(226, 232, 240), font=f_md)

            # 3 Info Cards (y = 112..204)
            # Card 1: Interface & Wi-Fi
            d.rectangle([12, 112, 264, 204], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text((22, 118), f"INTERFEJS ({STATE.iface.upper()})", fill=(56, 189, 248), font=f_sm)
            d.text((22, 138), f"IP: {STATE.local_ip}", fill=(255, 255, 255), font=f_md)
            d.text((22, 162), f"SSID: {STATE.ssid[:18]}", fill=(203, 213, 225), font=f_sm)
            d.text(
                (22, 180),
                f"Sygnal: {STATE.wifi_dbm} dBm ({STATE.wifi_pct}%)",
                fill=(74, 222, 128) if STATE.wifi_pct >= 40 else (251, 191, 36),
                font=f_sm,
            )

            # Card 2: Gateway & ARP Lock
            d.rectangle([274, 112, 526, 204], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text((284, 118), "BRAMA DOMOWA (ROUTER)", fill=(56, 189, 248), font=f_sm)
            gw_ms_str = f"{STATE.ping_gw_ms:.1f} ms" if STATE.ping_gw_ms >= 0 else "TIMEOUT"
            d.text((284, 138), f"{STATE.gateway_ip} ({gw_ms_str})", fill=(255, 255, 255), font=f_md)
            d.text((284, 162), f"MAC: {STATE.gateway_mac}", fill=(203, 213, 225), font=f_sm)
            arp_lbl = "ARP: LOCKED (OK)" if not STATE.arp_spoof_detected else "ARP: SPOOFING!"
            arp_col = (74, 222, 128) if not STATE.arp_spoof_detected else (248, 113, 113)
            d.text((284, 180), arp_lbl, fill=arp_col, font=f_sm)

            # Card 3: Internet & Honeypot summary
            d.rectangle([536, 112, 788, 204], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text((546, 118), "INTERNET & IDS CANARY", fill=(56, 189, 248), font=f_sm)
            in_str = f"{STATE.ping_inet_ms:.1f} ms" if STATE.ping_inet_ms >= 0 else "TIMEOUT"
            dn_str = f"{STATE.ping_dns_ms:.1f} ms" if STATE.ping_dns_ms >= 0 else "TIMEOUT"
            d.text((546, 138), f"1.1.1.1: {in_str}", fill=(255, 255, 255), font=f_md)
            d.text((546, 162), f"8.8.8.8: {dn_str} | Loss: {STATE.packet_loss_pct}%", fill=(203, 213, 225), font=f_sm)
            total_hits = sum(s["hits"] for s in STATE.canary_stats.values())
            d.text(
                (546, 180),
                f"Hosty LAN: {len(STATE.lan_hosts)} | Honeypot: {total_hits}",
                fill=(74, 222, 128) if total_hits == 0 else (248, 113, 113),
                font=f_sm,
            )

            # Detailed Gateway & Internet Latency Telemetry (y = 212..396)
            gw_valid = [x for x in STATE.hist_gw if x >= 0]
            gw_loss_count = sum(1 for x in STATE.hist_gw if x < 0)
            gw_loss_pct = int(gw_loss_count * 100 / max(1, len(STATE.hist_gw)))
            gw_last = STATE.ping_gw_ms
            gw_min = min(gw_valid) if gw_valid else 0.0
            gw_max = max(gw_valid) if gw_valid else 0.0
            gw_avg = (sum(gw_valid) / len(gw_valid)) if gw_valid else 0.0

            in_valid = [x for x in STATE.hist_inet if x >= 0]
            in_last = STATE.ping_inet_ms
            in_min = min(in_valid) if in_valid else 0.0
            in_max = max(in_valid) if in_valid else 0.0
            in_avg = (sum(in_valid) / len(in_valid)) if in_valid else 0.0

            # Card 1: Ping Brama Domowa (Router LAN) - left [12, 212, 394, 396]
            d.rectangle([12, 212, 394, 396], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.rectangle([12, 212, 394, 240], fill=(30, 41, 59))
            d.text((22, 218), f"PING BRAMA LAN ({STATE.gateway_ip})", fill=(74, 222, 128), font=f_sm)

            last_gw_str = f"{gw_last:.1f} ms" if gw_last >= 0 else "TIMEOUT"
            last_gw_col = (74, 222, 128) if (gw_last >= 0 and gw_last < 20) else ((251, 191, 36) if gw_last >= 0 else (248, 113, 113))
            d.text((24, 248), "Biezacy (last):", fill=(148, 163, 184), font=f_sm)
            d.text((150, 246), last_gw_str, fill=last_gw_col, font=f_lg)

            d.text((24, 282), f"Min:  {gw_min:5.1f} ms", fill=(226, 232, 240), font=f_sm)
            d.text((210, 282), f"Sredni: {gw_avg:5.1f} ms", fill=(56, 189, 248), font=f_sm)
            d.text((24, 310), f"Max:  {gw_max:5.1f} ms", fill=(226, 232, 240), font=f_sm)
            d.text((210, 310), f"Utrata: {gw_loss_pct}% ({gw_loss_count} pkt)", fill=(248, 113, 113) if gw_loss_pct > 0 else (74, 222, 128), font=f_sm)

            # Local gateway status strip
            gw_st_bg = (21, 128, 61) if gw_loss_pct == 0 and gw_last >= 0 else ((180, 83, 9) if gw_last >= 0 else (185, 28, 28))
            gw_st_msg = "POLACZENIE Z BRAMA: STABILNE" if (gw_loss_pct == 0 and gw_last >= 0) else ("OPUSZCZANIE PAKIETOW!" if gw_last >= 0 else "BRAK LACZNOSCI Z ROUTEREM!")
            d.rectangle([20, 344, 386, 384], fill=gw_st_bg)
            d.text((30, 355), gw_st_msg, fill=(255, 255, 255), font=f_sm)

            # Card 2: Ping Internet (Cloudflare / Google WAN) - right [406, 212, 788, 396]
            d.rectangle([406, 212, 788, 396], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.rectangle([406, 212, 788, 240], fill=(30, 41, 59))
            d.text((416, 218), "PING INTERNET (WAN 1.1.1.1 / 8.8.8.8)", fill=(56, 189, 248), font=f_sm)

            last_in_str = f"{in_last:.1f} ms" if in_last >= 0 else "TIMEOUT"
            last_in_col = (74, 222, 128) if (in_last >= 0 and in_last < 60) else ((251, 191, 36) if in_last >= 0 else (248, 113, 113))
            d.text((418, 248), "Biezacy (last):", fill=(148, 163, 184), font=f_sm)
            d.text((544, 246), last_in_str, fill=last_in_col, font=f_lg)

            d.text((418, 282), f"Min:  {in_min:5.1f} ms", fill=(226, 232, 240), font=f_sm)
            d.text((604, 282), f"Sredni: {in_avg:5.1f} ms", fill=(56, 189, 248), font=f_sm)
            d.text((418, 310), f"Max:  {in_max:5.1f} ms", fill=(226, 232, 240), font=f_sm)
            d.text((604, 310), f"Loss: {STATE.packet_loss_pct}% | DNS {STATE.ping_dns_ms:.0f}ms", fill=(248, 113, 113) if STATE.packet_loss_pct > 10 else (74, 222, 128), font=f_sm)

            # WAN status strip
            in_st_bg = (21, 128, 61) if STATE.packet_loss_pct < 10 and in_last >= 0 else ((180, 83, 9) if in_last >= 0 else (185, 28, 28))
            in_st_msg = "INTERNET: DOSTEPNY (ONLINE)" if (STATE.packet_loss_pct < 10 and in_last >= 0) else ("WYSOKIE OPOZNIENIA / LOSS" if in_last >= 0 else "AWARIA INTERNETU (OFFLINE)!")
            d.rectangle([414, 344, 780, 384], fill=in_st_bg)
            d.text((424, 355), in_st_msg, fill=(255, 255, 255), font=f_sm)

            # Bottom Telemetry Bar (y = 404..472)
            d.rectangle([12, 404, 788, 472], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text(
                (24, 414),
                f"CPU: {STATE.cpu_pct:4.1f}%   |   RAM: {STATE.ram_used_mb}/{STATE.ram_total_mb} MB   |   ZRAM: {STATE.zram_used_mb}/{STATE.zram_total_mb} MB",
                fill=(226, 232, 240),
                font=f_md,
            )
            d.text(
                (24, 442),
                f"Bateria: {STATE.bat_mv} mV ({STATE.bat_pct}%)   |   Uptime: {STATE.uptime_str}   |   Dzwiek: {'WYL (MUTE)' if muted else 'WLACZONY'}",
                fill=(148, 163, 184),
                font=f_sm,
            )

        elif active_tab == 1:
            # ================= TAB 2: LAN HOSTS =================
            d.rectangle([12, 60, 788, 100], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text(
                (22, 72),
                f"HOSTY LAN: {len(STATE.lan_hosts)}  |  Nowe/Nieznane: {new_hosts_count}  |  Ostatni skan: {STATE.last_arp_scan}",
                fill=(255, 255, 255),
                font=f_sm,
            )
            d.text((585, 72), "[Dotknij wiersza by zbadac]", fill=(148, 163, 184), font=f_sm)

            # Table Header
            d.rectangle([12, 106, 788, 134], fill=(30, 41, 59))
            d.text((22, 112), "ADRES IP", fill=(56, 189, 248), font=f_sm)
            d.text((160, 112), "PRODUCENT / URZADZENIE", fill=(56, 189, 248), font=f_sm)
            d.text((395, 112), "ADRES MAC", fill=(56, 189, 248), font=f_sm)
            d.text((575, 112), "STATUS / DETEKCJA", fill=(56, 189, 248), font=f_sm)

            hosts_sorted = sorted(
                STATE.lan_hosts.values(),
                key=lambda h: (h["known"], h["ip"]),
            )
            y_row = 140
            for row_i, h in enumerate(hosts_sorted[:10]):
                is_sel = (STATE.selected_host_index == row_i)
                if h["known"]:
                    # Known host: Green theme
                    row_bg = (13, 33, 23) if not is_sel else (20, 52, 36)
                    txt_col = (74, 222, 128)
                    status_str = f"[ ZNANY ] {h['last_seen']}"
                    status_col = (74, 222, 128)
                else:
                    # Unknown host: Red theme
                    row_bg = (60, 18, 18) if not is_sel else (88, 26, 26)
                    txt_col = (248, 113, 113)
                    status_str = f"[ ! NIEZNANY ! ] {h['last_seen']}"
                    status_col = (252, 165, 165)

                d.rectangle(
                    [12, y_row, 788, y_row + 25],
                    fill=row_bg,
                    outline=(250, 204, 21) if is_sel else None,
                    width=2 if is_sel else 1,
                )
                d.text((22, y_row + 4), h["ip"], fill=txt_col, font=f_sm)
                vendor_txt = h.get("vendor", lookup_device_info(h["mac"], h["ip"]))
                d.text((160, y_row + 4), vendor_txt[:26], fill=txt_col, font=f_sm)
                d.text((395, y_row + 4), h["mac"], fill=(203, 213, 225), font=f_sm)
                d.text((575, y_row + 4), status_str, fill=status_col, font=f_sm)
                y_row += 27

            # Bottom Touch Buttons
            d.rectangle([12, 420, 395, 472], fill=(21, 128, 61), outline=(74, 222, 128), width=2)
            d.text((24, 437), "[A] ZATWIERDZ WSZYSTKIE JAKO ZNANE", fill=(255, 255, 255), font=f_sm)

            d.rectangle([405, 420, 788, 472], fill=(30, 58, 138), outline=(56, 189, 248), width=2)
            d.text((435, 437), "[S] WYMUS SKANOWANIE PODSIECI", fill=(255, 255, 255), font=f_sm)

        elif active_tab == 2:
            # ================= TAB 3: IDS SENSORS & CANARY HONEYPOT =================
            # ARP Guard Card
            arp_bg = (127, 29, 29) if STATE.arp_spoof_detected else (17, 24, 39)
            d.rectangle([12, 60, 392, 156], fill=arp_bg, outline=(56, 189, 248), width=1)
            d.text((22, 68), "STRAZNIK ARP (MITM / ARP SPOOFING)", fill=(56, 189, 248), font=f_sm)
            d.text((22, 90), f"Brama: {STATE.gateway_ip} -> {STATE.gateway_mac}", fill=(255, 255, 255), font=f_sm)
            col_arp = (254, 202, 202) if STATE.arp_spoof_detected else (74, 222, 128)
            d.text((22, 112), STATE.arp_spoof_detail_l1[:46], fill=col_arp, font=f_sm)
            d.text((22, 132), STATE.arp_spoof_detail_l2[:46], fill=col_arp, font=f_sm)

            # Wi-Fi Evil Twin Card
            wifi_bg = (127, 29, 29) if STATE.evil_twin_detected else (17, 24, 39)
            d.rectangle([404, 60, 788, 156], fill=wifi_bg, outline=(56, 189, 248), width=1)
            d.text((414, 68), "STRAZNIK WI-FI (EVIL TWIN / ROGUE AP)", fill=(56, 189, 248), font=f_sm)
            d.text((414, 90), f"SSID: {STATE.ssid} | BSSID: {STATE.bssid}", fill=(255, 255, 255), font=f_sm)
            col_wifi = (254, 202, 202) if STATE.evil_twin_detected else (74, 222, 128)
            d.text((414, 112), STATE.evil_twin_detail[:46], fill=col_wifi, font=f_sm)

            # Canary Honeypot Listeners Table
            d.rectangle([12, 164, 788, 410], fill=(15, 23, 42), outline=(51, 65, 85), width=1)
            d.text(
                (22, 172),
                "PULAPKI PORTOW TCP (CANARY HONEYPOT) - skaner / intruz w sieci:",
                fill=(251, 191, 36),
                font=f_sm,
            )
            y_p = 198
            for port, name in CANARY_PORTS:
                st = STATE.canary_stats[port]
                hit = st["hits"] > 0
                r_bg = (127, 29, 29) if hit else (30, 41, 59)
                d.rectangle([22, y_p, 778, y_p + 26], fill=r_bg)
                d.text((32, y_p + 5), f"Port {port:<4d} ({name})", fill=(255, 255, 255), font=f_sm)
                status_txt = "TRAFIONY (ALARM!)" if hit else "CZUWANIE (0)"
                d.text((230, y_p + 5), status_txt, fill=(248, 113, 113) if hit else (74, 222, 128), font=f_sm)
                d.text((410, y_p + 5), f"Hits: {st['hits']}", fill=(255, 255, 255), font=f_sm)
                d.text((520, y_p + 5), f"Ostatnie IP: {st['last_ip']} ({st['last_time']})", fill=(203, 213, 225), font=f_sm)
                y_p += 29

            # Bottom Touch Buttons
            d.rectangle([12, 420, 470, 472], fill=(185, 28, 28), outline=(255, 255, 255), width=2)
            d.text((30, 437), "[C] POTWIERDZ I WYCISZ AKTYWNE ALARMY", fill=(255, 255, 255), font=f_sm)

            d.rectangle([482, 420, 788, 472], fill=(30, 41, 59), outline=(148, 163, 184), width=2)
            d.text((505, 437), f"[M] DZWIEK: {'WYLACZONY' if muted else 'WLACZONY'}", fill=(255, 255, 255), font=f_sm)

        elif active_tab == 3:
            # ================= TAB 4: ALARM LOG =================
            d.rectangle([12, 60, 788, 94], fill=(30, 41, 59))
            d.text((22, 69), "CZAS     | POZ   | ZRODLO    | OPIS ZDARZENIA BEZPIECZENSTWA", fill=(56, 189, 248), font=f_sm)

            y_l = 100
            if not STATE.event_log:
                d.text((22, 140), "Brak zarejestrowanych zdarzen bezpieczenstwa od uruchomienia.", fill=(148, 163, 184), font=f_md)
            else:
                for ev in list(STATE.event_log)[:11]:
                    lvl = ev["level"]
                    if lvl == "ALERT":
                        row_bg = (95, 20, 20)
                        txt_col = (254, 202, 202)
                    elif lvl == "WARN":
                        row_bg = (75, 35, 5)
                        txt_col = (253, 230, 138)
                    else:
                        row_bg = (17, 24, 39)
                        txt_col = (203, 213, 225)
                    d.rectangle([12, y_l, 788, y_l + 26], fill=row_bg)
                    line_str = f"{ev['time']} | {lvl:<5s} | {ev['source']:<9s} | {ev['msg'][:78]}"
                    d.text((18, y_l + 5), line_str, fill=txt_col, font=f_sm)
                    y_l += 28

            # Bottom Touch Buttons
            d.rectangle([12, 420, 470, 472], fill=(185, 28, 28), outline=(255, 255, 255), width=2)
            d.text((30, 437), "[C] POTWIERDZ I WYCISZ AKTYWNE ALARMY", fill=(255, 255, 255), font=f_sm)

            d.rectangle([482, 420, 788, 472], fill=(30, 41, 59), outline=(148, 163, 184), width=2)
            d.text((505, 437), f"[M] DZWIEK: {'WYLACZONY' if muted else 'WLACZONY'}", fill=(255, 255, 255), font=f_sm)

        # Modal Popup for Device Details if selected
        if STATE.selected_host_mac:
            sh = STATE.lan_hosts.get(STATE.selected_host_mac.lower())
            if sh is not None:
                mx0, my0, mx1, my1 = 120, 75, 680, 420
            # Dim outer region
            d.rectangle([mx0 - 4, my0 - 4, mx1 + 4, my1 + 4], fill=(11, 15, 25), outline=(56, 189, 248), width=3)
            d.rectangle([mx0, my0, mx1, my1], fill=(15, 23, 42))
            d.rectangle([mx0, my0, mx1, my0 + 36], fill=(30, 58, 138))
            d.text((mx0 + 16, my0 + 9), "SZCZEGOLY URZADZENIA W SIECI LAN", fill=(255, 255, 255), font=f_md)

            sy = my0 + 50
            d.text((mx0 + 20, sy), f"Adres IP:      {sh['ip']}", fill=(255, 255, 255), font=f_md)
            sy += 28
            d.text((mx0 + 20, sy), f"Adres MAC:     {sh['mac']}", fill=(203, 213, 225), font=f_md)
            sy += 28
            vendor_full = sh.get('vendor', lookup_device_info(sh['mac'], sh['ip']))
            d.text((mx0 + 20, sy), f"Identyfikator: {vendor_full}", fill=(56, 189, 248), font=f_md)
            sy += 28
            h_name = STATE.host_names.get(sh['ip'], "Brak nazwy mDNS/DNS")
            d.text((mx0 + 20, sy), f"Nazwa hosta:   {h_name}", fill=(203, 213, 225), font=f_sm)
            sy += 24
            d.text((mx0 + 20, sy), f"Ostatnio widz: {sh['last_seen']}", fill=(148, 163, 184), font=f_sm)
            sy += 24
            st_txt = "ZNANY (Zaufane urzadzenie domowe)" if sh['known'] else "NIEZNANY / NOWY (Wymaga uwagi!)"
            st_col = (74, 222, 128) if sh['known'] else (248, 113, 113)
            d.text((mx0 + 20, sy), f"Status:        {st_txt}", fill=st_col, font=f_md)

            # Modal Action Buttons
            btn_toggle_txt = "[O] OZNACZ JAKO NIEZNANE" if sh['known'] else "[Z] ZATWIERDZ JAKO ZNANE"
            btn_toggle_bg = (185, 28, 28) if sh['known'] else (21, 128, 61)
            d.rectangle([mx0 + 20, my1 - 60, mx0 + 265, my1 - 15], fill=btn_toggle_bg, outline=(255, 255, 255), width=2)
            d.text((mx0 + 30, my1 - 44), btn_toggle_txt, fill=(255, 255, 255), font=f_sm)

            d.rectangle([mx1 - 240, my1 - 60, mx1 - 20, my1 - 15], fill=(71, 85, 105), outline=(255, 255, 255), width=2)
            d.text((mx1 - 195, my1 - 44), "[ESC / X] ZAMKNIJ", fill=(255, 255, 255), font=f_sm)

        # Draw touch/mouse cursor crosshair if active
        if STATE.show_cursor:
            cx, cy = STATE.cursor_x, STATE.cursor_y
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(250, 204, 21), width=2)

    return img


def main():
    add_security_event("INFO", "SOC", "Uruchomiono monitor sieci domowej i czujniki IDS", ())
    fonts = load_fonts()

    # Silence kernel printk console messages so they do not write over /dev/fb0
    try:
        subprocess.run(["sysctl", "-w", "kernel.printk=1 4 1 7"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    threading.Thread(target=monitor_ping_and_system_loop, daemon=True).start()
    threading.Thread(target=lan_and_arp_guard_loop, daemon=True).start()
    threading.Thread(target=canary_honeypot_loop, daemon=True).start()
    threading.Thread(target=input_reader_loop, daemon=True).start()
    threading.Thread(target=dns_resolver_worker, daemon=True).start()

    fb_fd = None
    prev_vt_active = False
    last_render_time = 0.0
    MIN_FRAME_INTERVAL = 0.3  # Max ~3.3 FPS na ARM926EJ-S aby zachowac CPU < 10%

    while True:
        try:
            if fb_fd is None and os.path.exists(FB_DEV):
                try:
                    fb_fd = os.open(FB_DEV, os.O_RDWR)
                except Exception:
                    fb_fd = None

            vt_active = is_dashboard_vt_active()
            # If user just switched back to dashboard VT (chvt 3 / soc), trigger immediate frame redraw
            if vt_active and not prev_vt_active:
                REDRAW_EVENT.set()
            prev_vt_active = vt_active

            if vt_active and fb_fd is not None:
                now = time.time()
                elapsed = now - last_render_time
                if elapsed < MIN_FRAME_INTERVAL:
                    time.sleep(MIN_FRAME_INTERVAL - elapsed)

                img = render_frame(fonts)
                written = -1
                if C_BLITTER is not None:
                    try:
                        raw_rgb = img.tobytes()
                        written = C_BLITTER(fb_fd, raw_rgb, FB_WIDTH * FB_HEIGHT)
                    except Exception as be:
                        written = -1
                if written < 0:
                    raw565 = image_to_rgb565_bytes(img)
                    try:
                        os.pwrite(fb_fd, raw565, 0)
                    except Exception:
                        os.lseek(fb_fd, 0, os.SEEK_SET)
                        os.write(fb_fd, raw565)

                last_render_time = time.time()
        except Exception as e:
            try:
                with open("/run/wm8650_dashboard_err.log", "a") as ef:
                    ef.write(f"Frame render error: {e}\n")
            except Exception:
                pass

        REDRAW_EVENT.wait(timeout=1.5)
        REDRAW_EVENT.clear()


if __name__ == "__main__":
    main()
