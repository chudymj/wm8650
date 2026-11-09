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
import datetime
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
        self.lock = threading.Lock()
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

        # LAN Hosts: dict of mac -> {"ip": str, "mac": str, "known": bool, "last_seen": str}
        self.lan_hosts = {}
        self.known_macs = set()
        self.last_arp_scan = "---"
        self.force_subnet_sweep = False

        # IDS status
        self.arp_spoof_detected = False
        self.arp_spoof_detail = "OK (MAC bramy stabilny)"
        self.evil_twin_detected = False
        self.evil_twin_detail = "OK (BSSID punktu dostepowego zgodny)"
        self.canary_stats = {
            port: {"name": name, "hits": 0, "last_ip": "---", "last_time": "---", "banner": ""}
            for port, name in CANARY_PORTS
        }

        # Security event log: list of dicts {"time", "level", "source", "msg"}
        self.event_log = collections.deque(maxlen=40)

        # Pointer / Touch feedback
        self.cursor_x = 400
        self.cursor_y = 240
        self.show_cursor = False


STATE = SharedState()


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
                    if mac in mac_to_ip and mac_to_ip[mac] != ip_addr:
                        arp_spoof_msg = f"Duplikat MAC {mac} dla {mac_to_ip[mac]} oraz {ip_addr}!"
                    mac_to_ip[mac] = ip_addr

                    if ip_addr == gw_ip:
                        STATE.gateway_mac = mac
                        if STATE.baseline_gateway_mac is None:
                            STATE.baseline_gateway_mac = mac
                        elif mac != STATE.baseline_gateway_mac:
                            arp_spoof_msg = (
                                f"Zmiana MAC bramy {gw_ip}! Byl: {STATE.baseline_gateway_mac}, jest: {mac}"
                            )

                    is_known = mac in STATE.known_macs
                    prev = STATE.lan_hosts.get(mac)
                    if prev is None and not is_known:
                        new_hosts_found.append((ip_addr, mac))
                    STATE.lan_hosts[mac] = {
                        "ip": ip_addr,
                        "mac": mac,
                        "known": is_known,
                        "last_seen": now_hm,
                    }

                STATE.last_arp_scan = now_hm
                if arp_spoof_msg:
                    STATE.arp_spoof_detected = True
                    STATE.arp_spoof_detail = arp_spoof_msg

            if arp_spoof_msg:
                add_security_event("ALERT", "ARP-GUARD", arp_spoof_msg, target_tabs=(2, 3))

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
    # Top navigation bar (height 56 px, 5 tabs x 160 px)
    if y < 56:
        tab_idx = min(4, max(0, x // 160))
        if tab_idx == 4:
            switch_to_terminal()
            return
        with STATE.lock:
            STATE.active_tab = tab_idx
            STATE.unread_warn[tab_idx] = 0
            STATE.unread_alert[tab_idx] = 0
        trigger_beep("click")
        return

    with STATE.lock:
        tab = STATE.active_tab

    # Bottom action bar buttons (y >= 418)
    if y >= 418:
        if tab == 1:
            if x < 440:
                approve_all_current_hosts()
            else:
                with STATE.lock:
                    STATE.force_subnet_sweep = True
                add_security_event("INFO", "LAN", "Wymuszono skanowanie podsieci LAN", ())
                trigger_beep("click")
        elif tab in (2, 3):
            if x < 480:
                acknowledge_all_alarms()
            else:
                with STATE.lock:
                    STATE.sound_muted = not STATE.sound_muted
                trigger_beep("click")


def input_reader_loop():
    # 1. UDP socket for VT1609 touchscreen daemon (127.0.0.1:9999)
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.setblocking(False)
    try:
        udp_sock.bind(("127.0.0.1", 9999))
    except Exception:
        pass

    # 2. Optional USB mouse (/dev/input/mice)
    mouse_fd = None
    if os.path.exists("/dev/input/mice"):
        try:
            mouse_fd = os.open("/dev/input/mice", os.O_RDONLY | os.O_NONBLOCK)
        except Exception:
            mouse_fd = None

    # 3. Optional keyboard on /dev/tty3
    tty_fd = None
    old_term = None
    if os.path.exists("/dev/tty3"):
        try:
            tty_fd = os.open("/dev/tty3", os.O_RDONLY | os.O_NONBLOCK)
            old_term = termios.tcgetattr(tty_fd)
            tty.setcbreak(tty_fd)
        except Exception:
            tty_fd = None

    try:
        while True:
            rlist = [udp_sock]
            if mouse_fd is not None:
                rlist.append(mouse_fd)
            if tty_fd is not None:
                rlist.append(tty_fd)

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

                elif r == mouse_fd:
                    try:
                        buf = os.read(mouse_fd, 3)
                        if len(buf) == 3:
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
                    except Exception:
                        pass

                elif r == tty_fd:
                    try:
                        ch = os.read(tty_fd, 8).decode("ascii", errors="ignore")
                        if not ch:
                            continue
                        c = ch[0]
                        if c in ("1", "2", "3", "4"):
                            idx = int(c) - 1
                            with STATE.lock:
                                STATE.active_tab = idx
                                STATE.unread_warn[idx] = 0
                                STATE.unread_alert[idx] = 0
                            trigger_beep("click")
                        elif c in ("5", "t", "T") or ch == "\x1b":
                            switch_to_terminal()
                        elif c in ("a", "A"):
                            approve_all_current_hosts()
                        elif c in ("s", "S"):
                            with STATE.lock:
                                STATE.force_subnet_sweep = True
                            trigger_beep("click")
                        elif c in ("c", "C"):
                            acknowledge_all_alarms()
                        elif c in ("m", "M"):
                            with STATE.lock:
                                STATE.sound_muted = not STATE.sound_muted
                            trigger_beep("click")
                        elif c == "\t":
                            with STATE.lock:
                                STATE.active_tab = (STATE.active_tab + 1) % 4
                                idx = STATE.active_tab
                                STATE.unread_warn[idx] = 0
                                STATE.unread_alert[idx] = 0
                            trigger_beep("click")
                    except Exception:
                        pass
    finally:
        if tty_fd is not None and old_term is not None:
            try:
                termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_term)
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
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return (
                    ImageFont.truetype(path, 13),
                    ImageFont.truetype(path, 16),
                    ImageFont.truetype(path, 22),
                )
            except Exception:
                pass
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
            "[5] TERMINAL >_",
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
                b_txt = "ALARM IDS! Wykryto skanowanie lub atak w sieci (Sprawdz zakladki 3 i 4)"
            elif total_warns > 0 or STATE.packet_loss_pct > 15:
                b_bg = (180, 83, 9)
                b_txt = f"OSTRZEZENIE: Nowe hosty LAN ({new_hosts_count}) / Loss {STATE.packet_loss_pct}%"
            else:
                b_bg = (21, 128, 61)
                b_txt = "STATUS SIECI: BEZPIECZNIE (Brak aktywnych zagrozen IDS)"

            d.rectangle([12, 62, 788, 106], fill=b_bg, outline=(255, 255, 255), width=1)
            d.text((24, 75), b_txt, fill=(255, 255, 255), font=f_md)
            now_clock = datetime.datetime.now().strftime("%H:%M:%S")
            d.text((700, 75), now_clock, fill=(226, 232, 240), font=f_md)

            # 3 Info Cards (y = 114..206)
            # Card 1: Interface & Wi-Fi
            d.rectangle([12, 114, 264, 206], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text((22, 120), f"INTERFEJS ({STATE.iface.upper()})", fill=(56, 189, 248), font=f_sm)
            d.text((22, 140), f"IP: {STATE.local_ip}", fill=(255, 255, 255), font=f_md)
            d.text((22, 164), f"SSID: {STATE.ssid}", fill=(203, 213, 225), font=f_sm)
            d.text(
                (22, 182),
                f"Sygnal: {STATE.wifi_dbm} dBm ({STATE.wifi_pct}%)",
                fill=(74, 222, 128) if STATE.wifi_pct >= 40 else (251, 191, 36),
                font=f_sm,
            )

            # Card 2: Gateway & ARP Lock
            d.rectangle([274, 114, 526, 206], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text((284, 120), "BRAMA DOMOWA (ROUTER)", fill=(56, 189, 248), font=f_sm)
            gw_ms_str = f"{STATE.ping_gw_ms:.1f} ms" if STATE.ping_gw_ms >= 0 else "TIMEOUT"
            d.text((284, 140), f"{STATE.gateway_ip} ({gw_ms_str})", fill=(255, 255, 255), font=f_md)
            d.text((284, 164), f"MAC: {STATE.gateway_mac}", fill=(203, 213, 225), font=f_sm)
            arp_lbl = "ARP: LOCKED (OK)" if not STATE.arp_spoof_detected else "ARP: SPOOFING!"
            arp_col = (74, 222, 128) if not STATE.arp_spoof_detected else (248, 113, 113)
            d.text((284, 182), arp_lbl, fill=arp_col, font=f_sm)

            # Card 3: Internet & Honeypot summary
            d.rectangle([536, 114, 788, 206], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text((546, 120), "INTERNET & IDS CANARY", fill=(56, 189, 248), font=f_sm)
            in_str = f"{STATE.ping_inet_ms:.1f} ms" if STATE.ping_inet_ms >= 0 else "TIMEOUT"
            dn_str = f"{STATE.ping_dns_ms:.1f} ms" if STATE.ping_dns_ms >= 0 else "TIMEOUT"
            d.text((546, 140), f"1.1.1.1: {in_str}", fill=(255, 255, 255), font=f_md)
            d.text((546, 164), f"8.8.8.8: {dn_str} | Loss: {STATE.packet_loss_pct}%", fill=(203, 213, 225), font=f_sm)
            total_hits = sum(s["hits"] for s in STATE.canary_stats.values())
            d.text(
                (546, 182),
                f"Hosty LAN: {len(STATE.lan_hosts)} | Honeypot: {total_hits}",
                fill=(74, 222, 128) if total_hits == 0 else (248, 113, 113),
                font=f_sm,
            )

            # Live Latency Chart (y = 214..396)
            d.rectangle([12, 214, 788, 396], fill=(15, 23, 42), outline=(51, 65, 85), width=1)
            d.text(
                (22, 220),
                "WYKRES OPOZNIEN NA ZYWO (60 probek: Zielony = Brama LAN, Cyjan = Internet 1.1.1.1, Czerwony = Timeout)",
                fill=(148, 163, 184),
                font=f_sm,
            )
            chart_x0, chart_y0, chart_x1, chart_y1 = 24, 244, 776, 386
            chart_h = chart_y1 - chart_y0
            for gy in (chart_y0 + chart_h // 4, chart_y0 + chart_h // 2, chart_y0 + 3 * chart_h // 4):
                d.line([(chart_x0, gy), (chart_x1, gy)], fill=(30, 41, 59), width=1)

            gw_pts = list(STATE.hist_gw)
            in_pts = list(STATE.hist_inet)
            max_ms = max(50.0, max([x for x in gw_pts + in_pts if x > 0] + [50.0]))
            step_x = (chart_x1 - chart_x0) / 59.0

            prev_gw_xy = None
            prev_in_xy = None
            for idx in range(len(in_pts)):
                px = int(chart_x0 + idx * step_x)
                v_gw = gw_pts[idx]
                v_in = in_pts[idx]
                if v_in < 0:
                    d.line([(px, chart_y0 + 10), (px, chart_y1)], fill=(220, 38, 38), width=3)
                    prev_in_xy = None
                else:
                    py_in = int(chart_y1 - min(1.0, v_in / max_ms) * chart_h)
                    if prev_in_xy is not None:
                        d.line([prev_in_xy, (px, py_in)], fill=(56, 189, 248), width=2)
                    prev_in_xy = (px, py_in)

                if v_gw >= 0:
                    py_gw = int(chart_y1 - min(1.0, v_gw / max_ms) * chart_h)
                    if prev_gw_xy is not None:
                        d.line([prev_gw_xy, (px, py_gw)], fill=(74, 222, 128), width=2)
                    prev_gw_xy = (px, py_gw)
                else:
                    prev_gw_xy = None

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
            d.rectangle([12, 62, 788, 102], fill=(17, 24, 39), outline=(51, 65, 85), width=1)
            d.text(
                (24, 73),
                f"WYKRYTE URZADZENIA W SIECI LAN: {len(STATE.lan_hosts)}  |  Nowe/Nieznane: {new_hosts_count}  |  Ostatni skan: {STATE.last_arp_scan}",
                fill=(255, 255, 255),
                font=f_md,
            )

            # Table Header
            d.rectangle([12, 110, 788, 138], fill=(30, 41, 59))
            d.text((24, 116), "ADRES IP", fill=(56, 189, 248), font=f_sm)
            d.text((195, 116), "ADRES MAC", fill=(56, 189, 248), font=f_sm)
            d.text((400, 116), "OSTATNIO WIDZIANY", fill=(56, 189, 248), font=f_sm)
            d.text((590, 116), "STATUS AUTORYZACJI", fill=(56, 189, 248), font=f_sm)

            hosts_sorted = sorted(
                STATE.lan_hosts.values(),
                key=lambda h: (h["known"], h["ip"]),
            )
            y_row = 144
            for h in hosts_sorted[:10]:
                row_bg = (69, 26, 3) if not h["known"] else (15, 23, 42)
                d.rectangle([12, y_row, 788, y_row + 25], fill=row_bg)
                d.text((24, y_row + 4), h["ip"], fill=(255, 255, 255), font=f_sm)
                d.text((195, y_row + 4), h["mac"], fill=(203, 213, 225), font=f_sm)
                d.text((400, y_row + 4), h["last_seen"], fill=(148, 163, 184), font=f_sm)
                if h["known"]:
                    d.text((590, y_row + 4), "[ ZNANY HOST ]", fill=(74, 222, 128), font=f_sm)
                else:
                    d.text((590, y_row + 4), "[ ! NOWY INTRUZ ! ]", fill=(251, 191, 36), font=f_sm)
                y_row += 27

            # Bottom Touch Buttons
            d.rectangle([12, 420, 430, 472], fill=(21, 128, 61), outline=(74, 222, 128), width=2)
            d.text((28, 437), "[A] ZATWIERDZ WSZYSTKIE NOWE JAKO ZNANE", fill=(255, 255, 255), font=f_sm)

            d.rectangle([442, 420, 788, 472], fill=(30, 58, 138), outline=(56, 189, 248), width=2)
            d.text((465, 437), "[S] WYMUS SKANOWANIE PODSIECI TERAZ", fill=(255, 255, 255), font=f_sm)

        elif active_tab == 2:
            # ================= TAB 3: IDS SENSORS & CANARY HONEYPOT =================
            # ARP Guard Card
            arp_bg = (127, 29, 29) if STATE.arp_spoof_detected else (17, 24, 39)
            d.rectangle([12, 62, 392, 152], fill=arp_bg, outline=(56, 189, 248), width=1)
            d.text((24, 70), "STRAZNIK ARP (MITM / ARP SPOOFING GUARD)", fill=(56, 189, 248), font=f_sm)
            d.text((24, 94), f"Brama: {STATE.gateway_ip} -> {STATE.gateway_mac}", fill=(255, 255, 255), font=f_sm)
            d.text((24, 118), STATE.arp_spoof_detail[:46], fill=(74, 222, 128) if not STATE.arp_spoof_detected else (254, 202, 202), font=f_sm)

            # Wi-Fi Evil Twin Card
            wifi_bg = (127, 29, 29) if STATE.evil_twin_detected else (17, 24, 39)
            d.rectangle([404, 62, 788, 152], fill=wifi_bg, outline=(56, 189, 248), width=1)
            d.text((416, 70), "STRAZNIK WI-FI (EVIL TWIN / ROGUE AP)", fill=(56, 189, 248), font=f_sm)
            d.text((416, 94), f"SSID: {STATE.ssid} | BSSID: {STATE.bssid}", fill=(255, 255, 255), font=f_sm)
            d.text((416, 118), STATE.evil_twin_detail[:46], fill=(74, 222, 128) if not STATE.evil_twin_detected else (254, 202, 202), font=f_sm)

            # Canary Honeypot Listeners Table
            d.rectangle([12, 162, 788, 410], fill=(15, 23, 42), outline=(51, 65, 85), width=1)
            d.text(
                (24, 170),
                "PULAPKI PORTOW TCP (CANARY HONEYPOT) - kazde polaczenie z LAN oznacza skaner/intruza:",
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
            d.rectangle([12, 62, 788, 96], fill=(30, 41, 59))
            d.text((24, 71), "CZAS      | POZIOM | ZRODLO     | OPIS ZDARZENIA BEZPIECZENSTWA", fill=(56, 189, 248), font=f_sm)

            y_l = 102
            if not STATE.event_log:
                d.text((24, 140), "Brak zarejestrowanych zdarzen bezpieczenstwa od uruchomienia.", fill=(148, 163, 184), font=f_md)
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
                    line_str = f"{ev['time']}  | {lvl:<6s} | {ev['source']:<10s} | {ev['msg'][:58]}"
                    d.text((20, y_l + 5), line_str, fill=txt_col, font=f_sm)
                    y_l += 28

            # Bottom Touch Buttons
            d.rectangle([12, 420, 470, 472], fill=(185, 28, 28), outline=(255, 255, 255), width=2)
            d.text((30, 437), "[C] POTWIERDZ I WYCISZ AKTYWNE ALARMY", fill=(255, 255, 255), font=f_sm)

            d.rectangle([482, 420, 788, 472], fill=(30, 41, 59), outline=(148, 163, 184), width=2)
            d.text((505, 437), f"[M] DZWIEK: {'WYLACZONY' if muted else 'WLACZONY'}", fill=(255, 255, 255), font=f_sm)

        # Draw touch/mouse cursor crosshair if active
        if STATE.show_cursor:
            cx, cy = STATE.cursor_x, STATE.cursor_y
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(250, 204, 21), width=2)

    return img


def main():
    add_security_event("INFO", "SOC", "Uruchomiono monitor sieci domowej i czujniki IDS", ())
    fonts = load_fonts()

    threading.Thread(target=monitor_ping_and_system_loop, daemon=True).start()
    threading.Thread(target=lan_and_arp_guard_loop, daemon=True).start()
    threading.Thread(target=canary_honeypot_loop, daemon=True).start()
    threading.Thread(target=input_reader_loop, daemon=True).start()

    while True:
        try:
            if is_dashboard_vt_active() and os.path.exists(FB_DEV):
                img = render_frame(fonts)
                raw565 = image_to_rgb565_bytes(img)
                with open(FB_DEV, "wb") as fb:
                    fb.write(raw565)
        except Exception:
            pass
        time.sleep(0.5)


if __name__ == "__main__":
    main()
