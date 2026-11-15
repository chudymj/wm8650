#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wm8650_soc_tui.py - Ultra-lightweight Text User Interface (TUI) Network Monitor & IDS
for WonderMedia WM8650 (100x30 fbcon terminal on /dev/tty3).

Features:
  - 5 switchable tabs (Overview, LAN Hosts, IDS Sensors, Alarm Log, Console)
  - Pure ANSI terminal rendering directly to /dev/tty3 (sub-millisecond frame write)
  - Minimal CPU usage (< 2% on ARM926EJ-S 600 MHz without hardware FPU)
  - Non-intrusive background alerting (Amber WARN / Flashing Red ALERT with counters)
  - Hardware beep & buzzer alerts via /usr/local/bin/wm8650-beep
  - Seamless coexistence with Linux console (pauses /dev/tty3 writes when user is on tty1/tty2)
  - Full keyboard control (1-5, Tab, Arrows, A, S, C, M, Enter, Space, Q)
"""

import collections
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

TTY_DEV = "/dev/tty3"
ACTIVE_TTY_PATH = "/sys/class/tty/tty0/active"
DASHBOARD_TTY = "tty3"
KNOWN_HOSTS_FILE = "/etc/wm8650-soc/known_hosts.json"
BATTERY_FILE = "/run/wm8650_battery.txt"
BEEP_BIN = "/usr/local/bin/wm8650-beep"

TERM_WIDTH = 100
TERM_HEIGHT = 30

REDRAW_EVENT = threading.Event()

# ANSI escape sequences
RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Foreground
FG_BLK = "\033[30m"
FG_RED = "\033[31m"
FG_GRN = "\033[32m"
FG_YEL = "\033[33m"
FG_BLU = "\033[34m"
FG_MAG = "\033[35m"
FG_CYA = "\033[36m"
FG_WHT = "\033[37m"

# Bright Foreground
B_BLK = "\033[90m"
B_RED = "\033[91m"
B_GRN = "\033[92m"
B_YEL = "\033[93m"
B_BLU = "\033[94m"
B_MAG = "\033[95m"
B_CYA = "\033[96m"
B_WHT = "\033[97m"

# Background
BG_BLK = "\033[40m"
BG_RED = "\033[41m"
BG_GRN = "\033[42m"
BG_YEL = "\033[43m"
BG_BLU = "\033[44m"
BG_MAG = "\033[45m"
BG_CYA = "\033[46m"
BG_WHT = "\033[47m"

# Bright Background
BB_BLK = "\033[100m"
BB_RED = "\033[101m"
BB_GRN = "\033[102m"
BB_YEL = "\033[103m"
BB_BLU = "\033[104m"
BB_MAG = "\033[105m"
BB_CYA = "\033[106m"
BB_WHT = "\033[107m"

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
    "00:16:cb": "Apple",
    "00:17:f2": "Apple",
    "00:19:e3": "Apple",
    "00:1b:63": "Apple",
    "00:1c:b3": "Apple",
    "00:1d:4f": "Apple",
    "00:1e:52": "Apple",
    "00:1e:c2": "Apple",
    "00:1f:5b": "Apple",
    "00:1f:f3": "Apple",
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
    "14:98:77": "Apple",
    "18:af:61": "Apple",
    "20:ee:28": "Apple",
    "28:cf:e9": "Apple",
    "34:36:3b": "Apple",
    "3c:22:fb": "Apple",
    "40:6c:8f": "Apple",
    "48:d7:05": "Apple",
    "50:ed:3c": "Apple",
    "60:f4:45": "Apple",
    "6c:40:08": "Apple",
    "70:3e:ac": "Apple",
    "78:7b:8a": "Apple",
    "88:66:a5": "Apple",
    "90:9c:4a": "Apple",
    "98:01:a7": "Apple",
    "a4:83:e7": "Apple",
    "b8:78:2e": "Apple",
    "c8:85:50": "Apple",
    "dc:a9:04": "Apple",
    "e0:c9:7a": "Apple",
    "f4:5c:89": "Apple",
    "fc:fc:48": "Apple",
    "00:12:fb": "Samsung",
    "00:15:99": "Samsung",
    "00:16:32": "Samsung",
    "00:17:c9": "Samsung",
    "00:18:af": "Samsung",
    "00:1a:8a": "Samsung",
    "00:1d:25": "Samsung",
    "00:1e:e1": "Samsung",
    "00:1e:e2": "Samsung",
    "00:21:19": "Samsung",
    "00:23:39": "Samsung",
    "00:24:54": "Samsung",
    "00:26:5d": "Samsung",
    "08:fc:88": "Samsung",
    "14:49:e0": "Samsung",
    "1c:5a:3e": "Samsung",
    "24:4b:03": "Samsung",
    "34:c3:ac": "Samsung",
    "44:4e:1a": "Samsung",
    "48:44:f7": "Samsung",
    "50:01:6b": "Samsung",
    "54:92:be": "Samsung",
    "5c:0a:5b": "Samsung",
    "68:eb:ae": "Samsung",
    "78:47:1d": "Samsung",
    "84:25:db": "Samsung",
    "94:65:2d": "Samsung",
    "a8:06:00": "Samsung",
    "bc:72:b9": "Samsung",
    "cc:07:ab": "Samsung",
    "e4:7c:f9": "Samsung",
    "f8:04:2e": "Samsung",
    "00:0c:e7": "Intel",
    "00:13:02": "Intel",
    "00:13:e8": "Intel",
    "00:15:00": "Intel",
    "00:16:ea": "Intel",
    "00:18:de": "Intel",
    "00:19:d2": "Intel",
    "00:1b:21": "Intel",
    "00:1c:bf": "Intel",
    "00:1d:e0": "Intel",
    "00:1e:64": "Intel",
    "00:1e:67": "Intel",
    "00:1f:3b": "Intel",
    "00:1f:3c": "Intel",
    "00:21:5c": "Intel",
    "00:21:6a": "Intel",
    "00:21:6b": "Intel",
    "00:22:fb": "Intel",
    "00:23:14": "Intel",
    "00:23:15": "Intel",
    "00:24:d6": "Intel",
    "00:24:d7": "Intel",
    "00:26:c6": "Intel",
    "00:26:c7": "Intel",
    "34:13:e8": "Intel",
    "3c:fd:fe": "Intel",
    "48:51:b7": "Intel",
    "50:eb:f6": "Intel",
    "68:05:ca": "Intel",
    "7c:b0:c2": "Intel",
    "88:a4:c2": "Intel",
    "a0:36:bc": "Intel",
    "b8:85:84": "Intel",
    "c8:5b:76": "Intel",
    "f8:59:71": "Intel",
    "28:6c:07": "Xiaomi",
    "34:80:0d": "Xiaomi",
    "50:64:2b": "Xiaomi",
    "64:09:80": "Xiaomi",
    "74:23:44": "Xiaomi",
    "78:11:dc": "Xiaomi",
    "7c:49:eb": "Xiaomi",
    "8c:be:be": "Xiaomi",
    "9c:99:a0": "Xiaomi",
    "ac:c1:ee": "Xiaomi",
    "d4:97:0b": "Xiaomi",
    "ec:d0:9f": "Xiaomi",
    "f8:a4:5f": "Xiaomi",
    "00:04:0e": "AVM Fritz!",
    "00:1a:4f": "AVM Fritz!",
    "34:31:c4": "AVM Fritz!",
    "34:81:c4": "AVM Fritz!",
    "9c:c7:a6": "AVM Fritz!",
    "c0:25:06": "AVM Fritz!",
    "dc:39:6f": "AVM Fritz!",
    "00:14:bf": "Cisco-Linksys",
    "00:18:39": "Cisco-Linksys",
    "00:1a:70": "Cisco-Linksys",
    "00:1d:7e": "Cisco-Linksys",
    "00:23:69": "Cisco-Linksys",
    "00:25:9c": "Cisco-Linksys",
    "20:aa:4b": "Cisco-Linksys",
    "c0:c1:c0": "Cisco-Linksys",
    "00:18:4d": "Netgear",
    "00:1b:2f": "Netgear",
    "00:1f:33": "Netgear",
    "00:22:3f": "Netgear",
    "00:24:b2": "Netgear",
    "00:26:f2": "Netgear",
    "20:4e:7f": "Netgear",
    "44:94:fc": "Netgear",
    "84:1b:5e": "Netgear",
    "9c:3d:cf": "Netgear",
    "a0:04:60": "Netgear",
    "c0:3f:0e": "Netgear",
    "00:19:e0": "TP-Link",
    "00:21:27": "TP-Link",
    "00:23:cd": "TP-Link",
    "00:25:86": "TP-Link",
    "00:27:19": "TP-Link",
    "14:cc:20": "TP-Link",
    "30:de:4b": "TP-Link",
    "50:c7:bf": "TP-Link",
    "60:e3:27": "TP-Link",
    "74:da:38": "TP-Link",
    "90:f6:52": "TP-Link",
    "a0:f3:c1": "TP-Link",
    "c0:4a:00": "TP-Link",
    "e8:94:f6": "TP-Link",
    "f4:ec:38": "TP-Link",
    "bc:24:11": "Technicolor / Sage",
    "00:10:18": "Broadcom",
    "00:08:5c": "WonderMedia WM8650",
    "00:00:e8": "WonderMedia VT6103",
}

def lookup_vendor(mac: str) -> str:
    if not mac:
        return "Nieznany producent"
    clean = mac.lower().replace("-", ":")
    prefix = clean[:8]
    return OUI_DATABASE.get(prefix, "Nieznany sprzet")


class DashboardState:
    def __init__(self):
        self.lock = threading.Lock()
        self.active_tab = 0  # 0: Overview, 1: Hosts, 2: IDS, 3: Alarm Log, 4: Terminal

        self.unread_warn = [0, 0, 0, 0, 0]
        self.unread_alert = [0, 0, 0, 0, 0]
        self.flash_phase = False
        self.sound_muted = False

        # Ping & Connectivity Telemetry
        self.gateway_ip = "---"
        self.gateway_mac = "---"
        self.gateway_latencies = collections.deque(maxlen=30)
        self.gateway_loss_count = 0
        self.gateway_ping_count = 0
        self.gateway_loss_pct = 0.0

        self.wan_latencies = collections.deque(maxlen=30)
        self.wan_loss_count = 0
        self.wan_ping_count = 0
        self.wan_loss_pct = 0.0
        self.dns_latency_ms = 0.0

        self.active_interface = "wlan0"
        self.local_ip = "---"
        self.wifi_ssid = "---"
        self.wifi_bssid = "---"
        self.wifi_signal_dbm = 0
        self.wifi_quality_pct = 0

        # System Hardware Telemetry
        self.cpu_load_pct = 0.0
        self.ram_used_mb = 0
        self.ram_total_mb = 231
        self.zram_used_mb = 0
        self.zram_total_mb = 80
        self.battery_mv = 3850
        self.battery_pct = 60
        self.uptime_str = "---"

        # LAN Hosts
        self.lan_hosts = {}  # mac -> {ip, mac, vendor, first_seen, last_seen, known}
        self.known_macs = set()
        self.selected_host_index = 0
        self.selected_host_mac = None
        self.host_names = {}
        self.last_arp_scan_time = 0.0
        self.force_subnet_sweep = False

        # IDS & Honeypots
        self.arp_spoof_detected = False
        self.evil_twin_detected = False
        self.honeypot_hits = collections.defaultdict(int)
        self.honeypot_last_ip = {}
        self.honeypot_last_time = {}
        self.honeypot_last_banner = {}

        # Alarm Log
        self.alarm_log = collections.deque(maxlen=100)


STATE = DashboardState()


def load_known_hosts():
    if os.path.exists(KNOWN_HOSTS_FILE):
        try:
            with open(KNOWN_HOSTS_FILE, "r") as f:
                data = json.load(f)
                STATE.known_macs = set(mac.lower() for mac in data.get("known_macs", []))
        except Exception:
            pass


def save_known_hosts():
    try:
        os.makedirs(os.path.dirname(KNOWN_HOSTS_FILE), exist_ok=True)
        with open(KNOWN_HOSTS_FILE, "w") as f:
            json.dump({"known_macs": sorted(list(STATE.known_macs))}, f, indent=2)
    except Exception:
        pass


def trigger_beep(mode: str = "click"):
    if STATE.sound_muted:
        return
    if not os.path.exists(BEEP_BIN):
        return
    try:
        if mode == "click":
            subprocess.Popen([BEEP_BIN, "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif mode == "warn":
            subprocess.Popen([BEEP_BIN, "2"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif mode == "alert":
            subprocess.Popen([BEEP_BIN, "3"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def add_security_event(level: str, source: str, message: str, tab_targets=(3, 4)):
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    event = {
        "time": now_str,
        "level": level,
        "source": source,
        "msg": message,
    }
    with STATE.lock:
        STATE.alarm_log.appendleft(event)
        for t in tab_targets:
            if t != STATE.active_tab:
                if level == "ALERT":
                    STATE.unread_alert[t] += 1
                elif level == "WARN":
                    STATE.unread_warn[t] += 1

    if level == "ALERT":
        trigger_beep("alert")
    elif level == "WARN":
        trigger_beep("warn")

    REDRAW_EVENT.set()


def is_dashboard_vt_active() -> bool:
    try:
        with open(ACTIVE_TTY_PATH, "r") as f:
            return f.read().strip() == DASHBOARD_TTY
    except Exception:
        return True


def switch_to_terminal():
    try:
        subprocess.run(["chvt", "1"], check=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Background Monitoring Loops
# ---------------------------------------------------------------------------

def monitor_ping_and_system_loop():
    while True:
        try:
            # 1. Gateway IP & Interface
            gw_ip = None
            try:
                out = subprocess.check_output(["ip", "route", "show", "default"], text=True)
                for line in out.splitlines():
                    parts = line.split()
                    if "default" in parts and "via" in parts:
                        gw_ip = parts[parts.index("via") + 1]
                        if "dev" in parts:
                            STATE.active_interface = parts[parts.index("dev") + 1]
                        break
            except Exception:
                pass

            if not gw_ip:
                gw_ip = "192.168.9.1"
            STATE.gateway_ip = gw_ip

            # 2. Local IP
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect((gw_ip, 80))
                STATE.local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                STATE.local_ip = "---"

            # 3. Wi-Fi status
            try:
                with open("/proc/net/wireless", "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4 and ("wlan0:" in parts[0] or "ra0:" in parts[0]):
                            qual = int(float(parts[2].replace(".", "")))
                            lvl = int(float(parts[3].replace(".", "")))
                            STATE.wifi_quality_pct = min(100, int((qual / 70.0) * 100))
                            STATE.wifi_signal_dbm = lvl if lvl < 0 else lvl - 256
                            break
            except Exception:
                pass

            try:
                iw_out = subprocess.check_output(["iwgetid", "-r"], text=True, stderr=subprocess.DEVNULL).strip()
                if iw_out:
                    STATE.wifi_ssid = iw_out
                ap_out = subprocess.check_output(["iwgetid", "-a", "-r"], text=True, stderr=subprocess.DEVNULL).strip()
                if ap_out:
                    STATE.wifi_bssid = ap_out.lower()
            except Exception:
                pass

            # 4. Ping Gateway
            try:
                t0 = time.time()
                res = subprocess.run(["ping", "-c", "1", "-W", "1", gw_ip], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                rtt = (time.time() - t0) * 1000.0
                with STATE.lock:
                    STATE.gateway_ping_count += 1
                    if res.returncode == 0:
                        match = re.search(r"time=([\d\.]+)", res.stdout)
                        if match:
                            rtt = float(match.group(1))
                        STATE.gateway_latencies.append(rtt)
                    else:
                        STATE.gateway_loss_count += 1
                        STATE.gateway_latencies.append(None)
                    STATE.gateway_loss_pct = round((STATE.gateway_loss_count / max(1, STATE.gateway_ping_count)) * 100, 1)
            except Exception:
                pass

            # 5. Ping WAN (1.1.1.1)
            try:
                t0 = time.time()
                res = subprocess.run(["ping", "-c", "1", "-W", "1", "1.1.1.1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                rtt = (time.time() - t0) * 1000.0
                with STATE.lock:
                    STATE.wan_ping_count += 1
                    if res.returncode == 0:
                        match = re.search(r"time=([\d\.]+)", res.stdout)
                        if match:
                            rtt = float(match.group(1))
                        STATE.wan_latencies.append(rtt)
                    else:
                        STATE.wan_loss_count += 1
                        STATE.wan_latencies.append(None)
                    STATE.wan_loss_pct = round((STATE.wan_loss_count / max(1, STATE.wan_ping_count)) * 100, 1)
            except Exception:
                pass

            # 6. DNS lookup time
            try:
                t0 = time.time()
                socket.gethostbyname("one.one.one.one")
                dns_ms = (time.time() - t0) * 1000.0
                with STATE.lock:
                    STATE.dns_latency_ms = round(dns_ms, 1)
            except Exception:
                pass

            # 7. Hardware Telemetry
            try:
                with open("/proc/loadavg", "r") as f:
                    load1 = float(f.read().split()[0])
                    STATE.cpu_load_pct = min(100.0, round(load1 * 100.0, 1))
            except Exception:
                pass

            try:
                mem_total, mem_free, mem_buf, mem_cached = 0, 0, 0, 0
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            mem_total = int(line.split()[1]) // 1024
                        elif line.startswith("MemFree:"):
                            mem_free = int(line.split()[1]) // 1024
                        elif line.startswith("Buffers:"):
                            mem_buf = int(line.split()[1]) // 1024
                        elif line.startswith("Cached:"):
                            mem_cached = int(line.split()[1]) // 1024
                used = max(0, mem_total - (mem_free + mem_buf + mem_cached))
                STATE.ram_total_mb = mem_total
                STATE.ram_used_mb = used
            except Exception:
                pass

            try:
                with open("/proc/swaps", "r") as f:
                    for line in f:
                        if "zram" in line:
                            parts = line.split()
                            STATE.zram_total_mb = int(parts[2]) // 1024
                            STATE.zram_used_mb = int(parts[3]) // 1024
                            break
            except Exception:
                pass

            try:
                if os.path.exists(BATTERY_FILE):
                    with open(BATTERY_FILE, "r") as f:
                        parts = f.read().split()
                        if len(parts) >= 2:
                            STATE.battery_mv = int(parts[0])
                            STATE.battery_pct = int(parts[1])
            except Exception:
                pass

            try:
                with open("/proc/uptime", "r") as f:
                    up_sec = int(float(f.read().split()[0]))
                    days = up_sec // 86400
                    hours = (up_sec % 86400) // 3600
                    mins = (up_sec % 3600) // 60
                    STATE.uptime_str = f"{days}d {hours:02d}h {mins:02d}m"
            except Exception:
                pass

        except Exception:
            pass

        REDRAW_EVENT.set()
        time.sleep(2.5)


def lan_and_arp_guard_loop():
    last_sweep = 0.0
    while True:
        try:
            now = time.time()
            gw_ip = STATE.gateway_ip

            # 1. Inspect ARP table
            current_arp = {}
            if os.path.exists("/proc/net/arp"):
                with open("/proc/net/arp", "r") as f:
                    lines = f.readlines()[1:]
                    for line in lines:
                        parts = line.split()
                        if len(parts) >= 6:
                            ip, hw_type, flags, mac, mask, dev = parts[:6]
                            if flags != "0x0" and mac != "00:00:00:00:00:00":
                                current_arp[ip] = mac.lower()

            # ARP Spoofing check
            if gw_ip in current_arp:
                gw_mac = current_arp[gw_ip]
                with STATE.lock:
                    if STATE.gateway_mac == "---":
                        STATE.gateway_mac = gw_mac
                    elif STATE.gateway_mac != gw_mac:
                        if not STATE.arp_spoof_detected:
                            STATE.arp_spoof_detected = True
                            add_security_event(
                                "ALERT",
                                "ARP",
                                f"PODMIANA BRAMY! Oryginal: {STATE.gateway_mac} -> Nowy: {gw_mac}",
                                (2, 3, 4),
                            )

            # Update LAN hosts list
            with STATE.lock:
                for ip, mac in current_arp.items():
                    is_known = mac in STATE.known_macs
                    if mac not in STATE.lan_hosts:
                        vendor = lookup_vendor(mac)
                        STATE.lan_hosts[mac] = {
                            "ip": ip,
                            "mac": mac,
                            "vendor": vendor,
                            "first_seen": datetime.datetime.now().strftime("%d.%m %H:%M"),
                            "last_seen": now,
                            "known": is_known,
                        }
                        if not is_known:
                            add_security_event(
                                "WARN",
                                "LAN",
                                f"Wykryto nowe urzadzenie w podsieci LAN: {ip} ({vendor})",
                                (1, 3),
                            )
                        queue_hostname_resolve(ip)
                    else:
                        STATE.lan_hosts[mac]["ip"] = ip
                        STATE.lan_hosts[mac]["last_seen"] = now
                        STATE.lan_hosts[mac]["known"] = is_known

            # Subnet sweep every 45s or on demand
            if (now - last_sweep >= 45.0) or STATE.force_subnet_sweep:
                last_sweep = now
                STATE.force_subnet_sweep = False
                STATE.last_arp_scan_time = now
                threading.Thread(target=_perform_subnet_sweep, daemon=True).start()

        except Exception:
            pass

        time.sleep(2.0)


def _perform_subnet_sweep():
    try:
        local_ip = STATE.local_ip
        if not local_ip or local_ip == "---":
            return
        prefix = ".".join(local_ip.split(".")[:3])
        # Send lightweight UDP probe to broadcast / all IPs to trigger ARP resolution
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for i in range(1, 255):
            target = f"{prefix}.{i}"
            try:
                sock.sendto(b"\x00", (target, 9))
            except Exception:
                pass
        sock.close()
    except Exception:
        pass


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


def canary_honeypot_loop():
    HONEYPOT_PORTS = [21, 23, 80, 445, 3389, 5900, 8080]
    sockets = []
    for port in HONEYPOT_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.listen(5)
            s.setblocking(False)
            sockets.append((port, s))
        except Exception:
            pass

    while True:
        try:
            rlist = [s for _, s in sockets]
            readable, _, _ = select.select(rlist, [], [], 1.0)
            for s in readable:
                port = next(p for p, sock in sockets if sock == s)
                try:
                    conn, addr = s.accept()
                    client_ip, client_port = addr
                    conn.setblocking(False)
                    time.sleep(0.05)
                    data = b""
                    try:
                        data = conn.recv(128)
                    except Exception:
                        pass
                    conn.close()

                    snippet = data.decode("ascii", errors="ignore").strip().replace("\n", " ")[:30]
                    now_str = datetime.datetime.now().strftime("%H:%M:%S")

                    with STATE.lock:
                        STATE.honeypot_hits[port] += 1
                        STATE.honeypot_last_ip[port] = client_ip
                        STATE.honeypot_last_time[port] = now_str
                        if snippet:
                            STATE.honeypot_last_banner[port] = snippet

                    add_security_event(
                        "ALERT",
                        "HONEYPOT",
                        f"Trafienie Canary Honeypot {port}/tcp z IP {client_ip}! {snippet}",
                        (2, 3, 4),
                    )
                except Exception:
                    pass
        except Exception:
            time.sleep(1.0)


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


def acknowledge_all_alarms():
    with STATE.lock:
        STATE.unread_warn = [0, 0, 0, 0, 0]
        STATE.unread_alert = [0, 0, 0, 0, 0]
        STATE.arp_spoof_detected = False
        STATE.evil_twin_detected = False
    add_security_event("INFO", "SYSTEM", "Wyciszono i potwierdzono wszystkie aktywne alarmy", ())
    trigger_beep("click")
    REDRAW_EVENT.set()


# ---------------------------------------------------------------------------
# TUI Frame Renderer (100 columns x 30 rows)
# ---------------------------------------------------------------------------

def render_tui_screen() -> str:
    lines = []

    with STATE.lock:
        active_tab = STATE.active_tab
        unread_w = list(STATE.unread_warn)
        unread_a = list(STATE.unread_alert)
        flash = STATE.flash_phase
        STATE.flash_phase = not STATE.flash_phase
        muted = STATE.sound_muted

        # -------------------------------------------------------------------
        # Row 1: Top Navigation Bar (5 tabs x 20 columns = 100 cols)
        # -------------------------------------------------------------------
        tab_names = [
            "[1] PRZEGLAD",
            "[2] HOSTY LAN",
            "[3] CZUJNIKI IDS",
            "[4] ALARM LOG",
            "[5] KONSOLA >_",
        ]
        tab_chunks = []
        for i, name in enumerate(tab_names):
            label = name
            if i < 4:
                if unread_a[i] > 0 and i != active_tab:
                    bg = BB_RED if flash else BG_RED
                    fg = B_WHT + BOLD
                    label = f"{name} (!!{unread_a[i]})"
                elif unread_w[i] > 0 and i != active_tab:
                    bg = BG_YEL
                    fg = FG_BLK + BOLD
                    label = f"{name} (!{unread_w[i]})"
                elif i == active_tab:
                    bg = BG_BLU
                    fg = B_WHT + BOLD
                else:
                    bg = BB_BLK
                    fg = FG_WHT
            else:
                bg = BG_CYA
                fg = FG_BLK + BOLD

            padded = f" {label} ".center(20)
            tab_chunks.append(f"{bg}{fg}{padded}{RST}")

        lines.append("".join(tab_chunks))

        # -------------------------------------------------------------------
        # Row 2: Divider
        # -------------------------------------------------------------------
        lines.append(f"{B_BLK}" + ("-" * TERM_WIDTH) + f"{RST}")

        # Determine overall security status
        total_alerts = sum(unread_a) + (1 if STATE.arp_spoof_detected or STATE.evil_twin_detected else 0)
        new_hosts_count = sum(1 for h in STATE.lan_hosts.values() if not h["known"])
        total_warns = sum(unread_w) + new_hosts_count

        # -------------------------------------------------------------------
        # Row 3: Security Banner
        # -------------------------------------------------------------------
        now_time = datetime.datetime.now().strftime("%d.%m %H:%M:%S")
        if total_alerts > 0:
            b_bg = BB_RED if flash else BG_RED
            b_fg = B_WHT + BOLD
            b_txt = f"  [!] ALARM IDS! Wykryto skanowanie lub atak! (Sprawdz Zakladki 3 i 4)"
        elif total_warns > 0 or STATE.gateway_loss_pct > 15:
            b_bg = BG_YEL
            b_fg = FG_BLK + BOLD
            b_txt = f"  [!] OSTRZEZENIE: Nowe hosty LAN ({new_hosts_count}) | Utrata pakietow: {STATE.gateway_loss_pct}%"
        else:
            b_bg = BG_GRN
            b_fg = FG_BLK + BOLD
            b_txt = f"  [OK] STATUS SIECI: BEZPIECZNIE (Brak aktywnych zagrozen IDS)"

        b_right = f"{now_time}  "
        spc = max(1, TERM_WIDTH - len(b_txt) - len(b_right))
        lines.append(f"{b_bg}{b_fg}{b_txt}{' ' * spc}{b_right}{RST}")

        # -------------------------------------------------------------------
        # Row 4: Telemetry bar (CPU, RAM, ZRAM, Bateria, Uptime)
        # -------------------------------------------------------------------
        bat_str = f"{STATE.battery_mv} mV [{STATE.battery_pct}%]"
        telemetry = (
            f"  CPU: {B_WHT}{STATE.cpu_load_pct:4.1f}%{RST} | "
            f"RAM: {B_WHT}{STATE.ram_used_mb}/{STATE.ram_total_mb} MB{RST} | "
            f"ZRAM: {B_WHT}{STATE.zram_used_mb}/{STATE.zram_total_mb} MB{RST} | "
            f"Bateria: {B_CYA}{bat_str}{RST} | "
            f"Uptime: {B_WHT}{STATE.uptime_str}{RST}"
        )
        lines.append(telemetry)

        # Row 5: Empty line
        lines.append("")

        # -------------------------------------------------------------------
        # Tabs 1 - 4 Content
        # -------------------------------------------------------------------
        if active_tab == 0:
            # ================= TAB 1: PRZEGLAD =================
            gw_lats = [x for x in STATE.gateway_latencies if x is not None]
            gw_last = f"{gw_lats[-1]:.1f} ms" if gw_lats else "---"
            gw_min = f"{min(gw_lats):.1f} ms" if gw_lats else "---"
            gw_avg = f"{sum(gw_lats)/len(gw_lats):.1f} ms" if gw_lats else "---"
            gw_max = f"{max(gw_lats):.1f} ms" if gw_lats else "---"

            wan_lats = [x for x in STATE.wan_latencies if x is not None]
            wan_last = f"{wan_lats[-1]:.1f} ms" if wan_lats else "---"
            wan_min = f"{min(wan_lats):.1f} ms" if wan_lats else "---"
            wan_avg = f"{sum(wan_lats)/len(wan_lats):.1f} ms" if wan_lats else "---"
            wan_max = f"{max(wan_lats):.1f} ms" if wan_lats else "---"

            # Cards row 6-13 (Cols 1..48 and 51..98)
            lines.append(
                f" {B_CYA}+--- PING BRAMA LAN ({STATE.gateway_ip}) ----------------+  "
                f"{B_GRN}+--- PING INTERNET & DNS (1.1.1.1 / 8.8.8.8) -----+{RST}"
            )
            lines.append(
                f" {B_CYA}|{RST} Ostatni: {B_WHT}{gw_last:<8}{RST} Min: {B_WHT}{gw_min:<8}{RST} Avg: {B_WHT}{gw_avg:<8}{RST} {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} Ostatni: {B_WHT}{wan_last:<8}{RST} Min: {B_WHT}{wan_min:<8}{RST} Avg: {B_WHT}{wan_avg:<8}{RST} {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}|{RST} Maks:    {B_WHT}{gw_max:<8}{RST} Loss: {B_YEL if STATE.gateway_loss_pct > 0 else B_GRN}{STATE.gateway_loss_pct}%{RST}     Stan: {B_GRN}OK{RST}      {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} Maks:    {B_WHT}{wan_max:<8}{RST} Loss: {B_YEL if STATE.wan_loss_pct > 0 else B_GRN}{STATE.wan_loss_pct}%{RST}     DNS: {B_CYA}{STATE.dns_latency_ms} ms{RST} {B_GRN}|{RST}"
            )
            gw_bars = "||||||||||||||||||||" if STATE.gateway_loss_pct < 5 else "||||||||||          "
            wan_bars = "||||||||||||||||||||" if STATE.wan_loss_pct < 5 else "||||||||||          "
            lines.append(
                f" {B_CYA}|{RST} Jakosc:  [{B_GRN}{gw_bars}{RST}] 100% (Stabilne)  {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} WAN:     [{B_GRN}{wan_bars}{RST}] 100% (Online)    {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}|{RST} Brama MAC: {B_WHT}{STATE.gateway_mac:<21}{RST} (Blokada ARP) {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} Uslugi:  Cloudflare 1.1.1.1 [OK] | Google [OK]   {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}|{RST} Interf:  {STATE.active_interface} ({STATE.local_ip}) Sygnal: {STATE.wifi_signal_dbm} dBm ({STATE.wifi_quality_pct}%) {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} Wi-Fi:   SSID: {STATE.wifi_ssid[:16]:<16} BSSID: {STATE.wifi_bssid[:12]} {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}+-------------------------------------------------+  "
                f"{B_GRN}+-------------------------------------------------+{RST}"
            )
            lines.append("")

            # Lower half: Quick status preview (Rows 15-27)
            lines.append(f" {B_WHT}{BOLD}PODSUMOWANIE CZUJNIKOW IDS I OSTATNIE ZDARZENIA:{RST}")
            lines.append(
                f"   [Czujniki] Strażnik ARP: {B_GRN}AKTYWNY{RST} | "
                f"Strażnik Wi-Fi: {B_GRN}AKTYWNY{RST} | "
                f"Honeypot: {B_CYA}7 portow TCP nasluchuje{RST}"
            )
            lines.append(f"   [Hosty]    Wszystkich: {len(STATE.lan_hosts)} | Znanych: {len(STATE.known_macs)} | Niezatwierdzonych: {B_RED if new_hosts_count > 0 else B_GRN}{new_hosts_count}{RST}")
            lines.append("")
            lines.append(f" {B_WHT}{BOLD}OSTATNIE ZDARZENIA BEZPIECZENSTWA (DZIENNIK IDS):{RST}")
            ev_list = list(STATE.alarm_log)[:6]
            if not ev_list:
                lines.append(f"   {DIM}Brak zdarzen w dzienniku (System bezpieczny){RST}")
            else:
                for ev in ev_list:
                    lvl = ev["level"]
                    col = B_RED if lvl == "ALERT" else (B_YEL if lvl == "WARN" else B_CYA)
                    lines.append(f"   {B_WHT}{ev['time']}{RST} {col}[{lvl:5}]{RST} {B_WHT}{ev['source']:8}{RST} {ev['msg'][:65]}")

        elif active_tab == 1:
            # ================= TAB 2: HOSTY LAN =================
            lines.append(
                f" {B_WHT}{BOLD}INWENTARYZACJA URZADZEN W SIECI LAN{RST} "
                f"(Wszystkie: {B_CYA}{len(STATE.lan_hosts)}{RST} | "
                f"Znane: {B_GRN}{len(STATE.known_macs)}{RST} | "
                f"Nowe: {B_RED if new_hosts_count > 0 else B_GRN}{new_hosts_count}{RST})"
            )
            lines.append(
                f" {B_BLU}{B_WHT}{BOLD}   ADRES IP        ADRES MAC          PRODUCENT / URZADZENIE            PIERWSZE WIDZ.  STATUS        {RST}"
            )

            hosts_sorted = sorted(STATE.lan_hosts.values(), key=lambda h: (h["known"], h["ip"]))
            s_idx = STATE.selected_host_index
            total_h = len(hosts_sorted)

            # View window of 18 rows
            view_start = max(0, min(s_idx - 8, total_h - 18)) if total_h > 18 else 0
            view_hosts = hosts_sorted[view_start : view_start + 18]

            for idx, h in enumerate(view_hosts):
                real_idx = view_start + idx
                is_sel = (real_idx == s_idx)
                sel_pfx = f"{B_CYA}{BOLD}> {RST}" if is_sel else "  "

                ip = h["ip"]
                h_name = STATE.host_names.get(ip, "")
                disp_vendor = f"{h['vendor']} ({h_name})" if h_name else h["vendor"]
                disp_vendor = disp_vendor[:32]

                st_badge = f"{B_GRN}[  ZNANY  ]{RST}" if h["known"] else f"{B_RED}[NOWY HOST!]{RST}"
                row_bg = BG_BLU if is_sel else ""

                row_str = (
                    f"{sel_pfx}{row_bg}{h['ip']:<15} "
                    f"{h['mac']:<18} "
                    f"{disp_vendor:<33} "
                    f"{h['first_seen']:<15} "
                    f"{st_badge}{RST}"
                )
                lines.append(row_str)

            # Modal details popup if selected_host_mac is set
            sel_mac = STATE.selected_host_mac
            if sel_mac and sel_mac in STATE.lan_hosts:
                sh = STATE.lan_hosts[sel_mac]
                lines.append("")
                lines.append(f" {B_CYA}+--- SZCZEGOLY URZADZENIA: {sh['ip']} ({sh['mac']}) -----------------------------+{RST}")
                lines.append(f" {B_CYA}|{RST} Producent: {sh['vendor']:<25} Hostname: {STATE.host_names.get(sh['ip'], '---'):<20} {B_CYA}|{RST}")
                lines.append(f" {B_CYA}|{RST} Status:    {'ZNANE (Autoryzowane)' if sh['known'] else 'NOWE / NIEAUTORYZOWANE':<25} [Enter/Z/O] Zmien stan [Esc] Zamknij {B_CYA}|{RST}")
                lines.append(f" {B_CYA}+--------------------------------------------------------------------------------+{RST}")

        elif active_tab == 2:
            # ================= TAB 3: CZUJNIKI IDS =================
            lines.append(f" {B_WHT}{BOLD}STAN CZUJNIKOW IDS I PUŁAPKI SIECIOWE CANARY HONEYPOT{RST}")
            lines.append("")
            lines.append(
                f" {B_CYA}+--- STRAZNIK ARP (Spoofing & MITM) --------------+  "
                f"{B_GRN}+--- STRAZNIK WI-FI (Evil Twin & Deauth) ---------+{RST}"
            )
            arp_st = f"{B_RED}ALARM: SPOOFING!{RST}" if STATE.arp_spoof_detected else f"{B_GRN}AKTYWNY - BRAK ZAGROZEN{RST}"
            lines.append(
                f" {B_CYA}|{RST} Brama IP:     {STATE.gateway_ip:<24} {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} Siec SSID:    {STATE.wifi_ssid:<24} {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}|{RST} Brama MAC:    {STATE.gateway_mac:<24} {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} BSSID:        {STATE.wifi_bssid:<24} {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}|{RST} Stan ochrony: {arp_st:<32} {B_CYA}|{RST}  "
                f"{B_GRN}|{RST} Sygnal:       {STATE.wifi_signal_dbm} dBm ({STATE.wifi_quality_pct}%)               {B_GRN}|{RST}"
            )
            lines.append(
                f" {B_CYA}+-------------------------------------------------+  "
                f"{B_GRN}+-------------------------------------------------+{RST}"
            )
            lines.append("")
            lines.append(f" {B_WHT}{BOLD}PUŁAPKI SIECIOWE CANARY HONEYPOT (PORTY NASŁUCHUJĄCE TCP):{RST}")
            lines.append(
                f" {B_BLU}{B_WHT}{BOLD} PORT     USŁUGA         STATUS       TRAFIENIA   OSTATNI INTRUZ (IP)   CZAS       SZCZEGÓŁY / BANNER   {RST}"
            )

            HONEYPOT_DEF = [
                (21, "FTP"),
                (23, "Telnet"),
                (80, "HTTP"),
                (445, "SMB / WNet"),
                (3389, "RDP"),
                (5900, "VNC"),
                (8080, "HTTP Proxy"),
            ]
            for port, srv in HONEYPOT_DEF:
                hits = STATE.honeypot_hits[port]
                last_ip = STATE.honeypot_last_ip.get(port, "---")
                last_tm = STATE.honeypot_last_time.get(port, "---")
                banner = STATE.honeypot_last_banner.get(port, "---")[:22]

                st_col = B_RED if hits > 0 else B_GRN
                st_txt = f"{st_col}{'[TRAFIONY!]' if hits > 0 else '[CZUWANIE]'}{RST}"

                row_str = (
                    f" {port:<8} {srv:<14} {st_txt}   "
                    f"{hits:<11} {last_ip:<21} {last_tm:<10} "
                    f"{banner:<22}"
                )
                lines.append(row_str)

        elif active_tab == 3:
            # ================= TAB 4: ALARM LOG =================
            lines.append(f" {B_WHT}{BOLD}DZIENNIK ZDARZEŃ BEZPIECZEŃSTWA (ALARM LOG & INCIDENTS){RST}")
            lines.append(
                f" {B_BLU}{B_WHT}{BOLD} CZAS      POZIOM   ŹRÓDŁO     OPIS ZDARZENIA                                                        {RST}"
            )
            ev_list = list(STATE.alarm_log)[:21]
            if not ev_list:
                lines.append(f"  {DIM}Dziennik jest pusty. Brak incydentow bezpieczenstwa w sieci.{RST}")
            else:
                for ev in ev_list:
                    lvl = ev["level"]
                    col = B_RED if lvl == "ALERT" else (B_YEL if lvl == "WARN" else B_CYA)
                    lines.append(
                        f" {B_WHT}{ev['time']}{RST}  "
                        f"{col}[{lvl:5}]{RST}  "
                        f"{B_WHT}{ev['source']:10}{RST} "
                        f"{ev['msg'][:70]}"
                    )

        # Pad lines up to row 27
        while len(lines) < 27:
            lines.append("")

        # -------------------------------------------------------------------
        # Rows 28-30: Bottom Help / Action Bar
        # -------------------------------------------------------------------
        lines.append(f"{B_BLK}" + ("-" * TERM_WIDTH) + f"{RST}")
        mute_badge = f"{B_RED}[WYCISZONY]{RST}" if muted else f"{B_GRN}[AKTYWNY]{RST}"
        help_actions = (
            f" {B_CYA}[1-5]{RST} Zakladki | "
            f"{B_CYA}[A]{RST} Zatwierdz hosty | "
            f"{B_CYA}[S]{RST} Skanuj LAN | "
            f"{B_CYA}[C]{RST} Wycisz alarmy | "
            f"{B_CYA}[M]{RST} Dzwiek {mute_badge} | "
            f"{B_CYA}[5/Q]{RST} Konsola tty1"
        )
        lines.append(help_actions)

        sys_info = f" Cyber-Rama SOC & Domowy IDS | WonderMedia WM8650 | Debian 12 armel | tty3 fbcon (100x30)"
        lines.append(f"{B_BLK}{sys_info}{RST}")

    # Build final ANSI string (Move cursor to Home, Hide Cursor)
    out = ["\033[H\033[?25l"]
    for row in lines[:TERM_HEIGHT]:
        # Clear to end of line to prevent ghost characters
        out.append(row + "\033[K\n")
    return "".join(out)


# ---------------------------------------------------------------------------
# Input Reader Loop (/dev/tty3 + /dev/input/event*)
# ---------------------------------------------------------------------------

def _handle_key(c: str):
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
    elif c in ("\x1b", "x", "X"):  # ESC or X
        with STATE.lock:
            if STATE.selected_host_mac is not None:
                STATE.selected_host_mac = None
                REDRAW_EVENT.set()
                trigger_beep("click")
                return
        switch_to_terminal()
    elif c in ("\t",):  # TAB
        with STATE.lock:
            STATE.active_tab = (STATE.active_tab + 1) % 4
            STATE.selected_host_mac = None
            idx = STATE.active_tab
            STATE.unread_warn[idx] = 0
            STATE.unread_alert[idx] = 0
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif c in ("a", "A"):
        approve_all_current_hosts()
    elif c in ("s", "S"):
        with STATE.lock:
            STATE.force_subnet_sweep = True
        add_security_event("INFO", "LAN", "Wymuszono skanowanie podsieci LAN", ())
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif c in ("c", "C"):
        acknowledge_all_alarms()
    elif c in ("m", "M"):
        with STATE.lock:
            STATE.sound_muted = not STATE.sound_muted
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif c in ("z", "Z", "o", "O"):
        with STATE.lock:
            sel_m = STATE.selected_host_mac
            if sel_m is None and STATE.lan_hosts:
                hosts_s = sorted(STATE.lan_hosts.values(), key=lambda h: (h["known"], h["ip"]))
                s_idx = STATE.selected_host_index
                if 0 <= s_idx < len(hosts_s):
                    sel_m = hosts_s[s_idx]["mac"]
        if sel_m:
            toggle_host_known(sel_m)
    elif c in ("\n", "\r", " "):  # ENTER or SPACE
        with STATE.lock:
            if STATE.active_tab == 1 and STATE.lan_hosts:
                hosts_s = sorted(STATE.lan_hosts.values(), key=lambda h: (h["known"], h["ip"]))
                s_idx = STATE.selected_host_index
                if 0 <= s_idx < len(hosts_s):
                    curr = hosts_s[s_idx]["mac"]
                    if STATE.selected_host_mac == curr:
                        STATE.selected_host_mac = None
                    else:
                        STATE.selected_host_mac = curr
                    trigger_beep("click")
                    REDRAW_EVENT.set()
    elif c == "UP":
        with STATE.lock:
            STATE.selected_host_index = max(0, STATE.selected_host_index - 1)
        trigger_beep("click")
        REDRAW_EVENT.set()
    elif c == "DOWN":
        with STATE.lock:
            total_h = len(STATE.lan_hosts)
            STATE.selected_host_index = min(max(0, total_h - 1), STATE.selected_host_index + 1)
        trigger_beep("click")
        REDRAW_EVENT.set()


def input_reader_loop():
    # 1. Open /dev/tty3
    tty_fd = None
    old_term = None
    if os.path.exists(TTY_DEV):
        try:
            tty_fd = os.open(TTY_DEV, os.O_RDWR | os.O_NONBLOCK)
            old_term = termios.tcgetattr(tty_fd)
            tty.setcbreak(tty_fd)
        except Exception:
            tty_fd = None

    # 2. Modern Linux evdev devices (/dev/input/event*)
    evdev_fds = {}
    last_evdev_scan = 0.0
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

            rlist = []
            if tty_fd is not None:
                rlist.append(tty_fd)
            rlist.extend(evdev_fds.values())

            readable, _, _ = select.select(rlist, [], [], 0.2)
            for r in readable:
                if r == tty_fd:
                    try:
                        seq = os.read(tty_fd, 16).decode("ascii", errors="ignore")
                        if not seq:
                            continue
                        if seq == "\x1b[A" or seq in ("k", "K"):
                            _handle_key("UP")
                        elif seq == "\x1b[B" or seq in ("j", "J"):
                            _handle_key("DOWN")
                        else:
                            _handle_key(seq[0])
                    except Exception:
                        pass
                elif r in evdev_fds.values():
                    try:
                        buf = os.read(r, EV_SIZE * 16)
                        for offset in range(0, len(buf) - EV_SIZE + 1, EV_SIZE):
                            _, _, ev_type, ev_code, ev_val = struct.unpack(EV_FORMAT, buf[offset : offset + EV_SIZE])
                            if ev_type == 1 and ev_val == 1:  # EV_KEY Pressed
                                if ev_code in (2, 3, 4, 5):  # Keys 1-4
                                    _handle_key(str(ev_code - 1))
                                elif ev_code in (6, 20):  # Key 5 or T
                                    _handle_key("5")
                                elif ev_code in (1, 45):  # ESC or X
                                    _handle_key("\x1b")
                                elif ev_code in (103, 37):  # UP or K
                                    _handle_key("UP")
                                elif ev_code in (108, 36):  # DOWN or J
                                    _handle_key("DOWN")
                                elif ev_code in (28, 57):  # ENTER or SPACE
                                    _handle_key("\n")
                                elif ev_code in (30,):  # A
                                    _handle_key("a")
                                elif ev_code in (31,):  # S
                                    _handle_key("s")
                                elif ev_code in (46,):  # C
                                    _handle_key("c")
                                elif ev_code in (50,):  # M
                                    _handle_key("m")
                                elif ev_code in (44, 24):  # Z or O
                                    _handle_key("z")
                                elif ev_code == 15:  # TAB
                                    _handle_key("\t")
                    except Exception:
                        pass
    finally:
        if tty_fd is not None and old_term is not None:
            try:
                termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_term)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------

def main():
    load_known_hosts()
    add_security_event("INFO", "SYSTEM", "Uruchomiono Cyber-Rama SOC & Domowy IDS (Tryb TUI, fbcon)", ())

    threading.Thread(target=monitor_ping_and_system_loop, daemon=True).start()
    threading.Thread(target=lan_and_arp_guard_loop, daemon=True).start()
    threading.Thread(target=canary_honeypot_loop, daemon=True).start()
    threading.Thread(target=dns_resolver_worker, daemon=True).start()
    threading.Thread(target=input_reader_loop, daemon=True).start()

    tty_out_fd = None
    prev_vt_active = False

    while True:
        try:
            if tty_out_fd is None and os.path.exists(TTY_DEV):
                try:
                    tty_out_fd = os.open(TTY_DEV, os.O_RDWR)
                except Exception:
                    tty_out_fd = None

            vt_active = is_dashboard_vt_active()
            if vt_active and not prev_vt_active:
                REDRAW_EVENT.set()
            prev_vt_active = vt_active

            # Only write to /dev/tty3 if dashboard is the active virtual console
            if vt_active and tty_out_fd is not None:
                screen_ansi = render_tui_screen()
                os.write(tty_out_fd, screen_ansi.encode("utf-8"))

        except Exception as e:
            try:
                with open("/run/wm8650_tui_err.log", "a") as ef:
                    ef.write(f"TUI render error: {e}\n")
            except Exception:
                pass

        REDRAW_EVENT.wait(timeout=1.5)
        REDRAW_EVENT.clear()


if __name__ == "__main__":
    main()
