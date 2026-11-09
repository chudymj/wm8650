#!/bin/bash
set -e

# ==============================================================================
# Skrypt instalujący oficjalnego Debiana 12 (Bookworm) armel z sysvinit-core
# dla tabletu WonderMedia WM8650 (Linux 6.1 LTS)
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "Błąd: Uruchom ten skrypt z uprawnieniami roota (sudo):"
    echo "  sudo $0 /dev/mmcblk0"
    exit 1
fi

SD_DEV="${1:-/dev/mmcblk0}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -b "$SD_DEV" ]; then
    echo "Błąd: Urządzenie blokowe $SD_DEV nie istnieje!"
    echo "Podłącz kartę SD i podaj właściwą ścieżkę (np. /dev/mmcblk0 lub /dev/sdb)."
    exit 1
fi

ROOT_DISK="/dev/$(lsblk -no pkname "$(findmnt -n -o SOURCE /)" 2>/dev/null | head -n1)"
if [ "$SD_DEV" = "/dev/sda" ] || [ "$SD_DEV" = "$ROOT_DISK" ]; then
    echo "BŁĄD BEZPIECZEŃSTWA: Odmowa zapisu na dysk systemowy ($SD_DEV)!"
    exit 1
fi

if [[ "$SD_DEV" =~ [0-9]$ ]]; then
    PART_BOOT="${SD_DEV}p1"
    PART_ROOT="${SD_DEV}p2"
else
    PART_BOOT="${SD_DEV}1"
    PART_ROOT="${SD_DEV}2"
fi

if [ ! -b "$PART_ROOT" ]; then
    echo "Błąd: Partycja główna $PART_ROOT nie istnieje!"
    echo "Upewnij się, że karta SD posiada 2 partycje (1: FAT32, 2: Linux)."
    exit 1
fi

echo "=================================================================="
echo "  Instalacja Debiana 12 (Bookworm) armel na $SD_DEV"
echo "  Partycja boot  : $PART_BOOT (FAT32, uImage + wmt_scriptcmd)"
echo "  Partycja root  : $PART_ROOT (ext4, Debian 12 Bookworm)"
echo "=================================================================="
lsblk "$SD_DEV"
echo "=================================================================="
read -p "Czy na pewno chcesz zainstalować Debian 12 na $PART_ROOT? [t/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[tTyY]$ ]]; then
    echo "Anulowano."
    exit 0
fi

# 1. Sprawdzenie narzędzi na hoście
echo "[1/6] Sprawdzanie narzędzi hosta..."
export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH"
NEED_PKGS=()
command -v debootstrap >/dev/null 2>&1 || NEED_PKGS+=("debootstrap")
command -v qemu-arm-static >/dev/null 2>&1 || NEED_PKGS+=("qemu-user-static" "binfmt-support")
command -v mkfs.ext4 >/dev/null 2>&1 || NEED_PKGS+=("e2fsprogs")

if [ ${#NEED_PKGS[@]} -gt 0 ]; then
    echo "Instalowanie brakujących pakietów: ${NEED_PKGS[*]}..."
    apt-get update
    apt-get install -y "${NEED_PKGS[@]}"
fi

# 2. Odmontowanie partycji karty SD
echo "[2/6] Odmontowywanie partycji na $SD_DEV..."
umount "$PART_BOOT" 2>/dev/null || true
umount "$PART_ROOT" 2>/dev/null || true

# 3. Kopiowanie bootloadera i jądra na partycję BOOT (jeśli dostępne)
MNT_BOOT="/mnt/wm8650_boot"
mkdir -p "$MNT_BOOT"
if mount "$PART_BOOT" "$MNT_BOOT" 2>/dev/null; then
    echo "Aktualizowanie plików startowych na partycji BOOT ($PART_BOOT)..."
    [ -f "$SCRIPT_DIR/uImage" ] && cp -v "$SCRIPT_DIR/uImage" "$MNT_BOOT/"
    [ -f "$SCRIPT_DIR/wmt_scriptcmd" ] && cp -v "$SCRIPT_DIR/wmt_scriptcmd" "$MNT_BOOT/"
    sync
    umount "$MNT_BOOT"
fi
rmdir "$MNT_BOOT" 2>/dev/null || true

# 4. Formatowanie partycji rootfs (ext4)
echo "[3/6] Formatowanie partycji $PART_ROOT (ext4)..."
mkfs.ext4 -F -L "debian_rootfs" "$PART_ROOT"

# 5. Bootstrap Debiana 12 (Bookworm) armel
MNT_ROOT="/mnt/wm8650_root"
mkdir -p "$MNT_ROOT"

cleanup() {
    umount -l "$MNT_ROOT/proc" 2>/dev/null || true
    umount -l "$MNT_ROOT/sys" 2>/dev/null || true
    umount -l "$MNT_ROOT/dev/pts" 2>/dev/null || true
    umount -l "$MNT_ROOT/dev" 2>/dev/null || true
    umount -l "$MNT_ROOT" 2>/dev/null || true
}
trap cleanup EXIT

mount "$PART_ROOT" "$MNT_ROOT"

echo "[4/6] Pobieranie systemu bazowego Debian 12 (Bookworm) armel..."
debootstrap --arch=armel --foreign \
    bookworm "$MNT_ROOT" http://deb.debian.org/debian/

cp /usr/bin/qemu-arm-static "$MNT_ROOT/usr/bin/"
cp /etc/resolv.conf "$MNT_ROOT/etc/resolv.conf"

echo "Uruchamianie drugiego etapu instalacji (debootstrap --second-stage w QEMU ARM)..."
mount -t proc proc "$MNT_ROOT/proc"
mount -t sysfs sys "$MNT_ROOT/sys"
mount -o bind /dev "$MNT_ROOT/dev"
mount -o bind /dev/pts "$MNT_ROOT/dev/pts"

chroot "$MNT_ROOT" /debootstrap/debootstrap --second-stage

# 6. Konfiguracja repozytoriów i instalacja pakietów dodatkowych
echo "[5/6] Konfiguracja repozytoriów, sysvinit-core, sieci i narzędzi..."

cat <<'EOF' > "$MNT_ROOT/etc/apt/sources.list"
deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware
deb http://deb.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware
EOF

# Wymuszenie usunięcia systemd i instalacja sysvinit-core oraz narzędzi
chroot "$MNT_ROOT" bash -c "
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends sysvinit-core sysv-rc sysvinit-utils
apt-get remove -y --purge systemd systemd-sysv libpam-systemd 2>/dev/null || true
apt-get install -y --no-install-recommends \
    udev procps kmod net-tools iproute2 iputils-ping wireless-tools wpasupplicant iw whiptail \
    nano curl wget ca-certificates openssh-server locales tzdata htop sudo rfkill \
    firmware-misc-nonfree wireless-regdb \
    python3-minimal python3-pil fonts-dejavu-core kbd
apt-get clean
"

# Kopiowanie modułów jądra Linux 6.1
if [ -d "$SCRIPT_DIR/modules_wm8650/lib/modules" ]; then
    echo "Kopiowanie modułów jądra 6.1..."
    mkdir -p "$MNT_ROOT/lib/modules"
    cp -r "$SCRIPT_DIR"/modules_wm8650/lib/modules/* "$MNT_ROOT/lib/modules/"
    chroot "$MNT_ROOT" depmod -a 6.1.191 2>/dev/null || true
fi

# Konfiguracja hosta i użytkowników
echo "wm8650" > "$MNT_ROOT/etc/hostname"
cat <<'EOF' > "$MNT_ROOT/etc/hosts"
127.0.0.1	localhost
127.0.1.1	wm8650
EOF

# Hasło roota: root, użytkownik: user / user
echo "root:root" | chroot "$MNT_ROOT" chpasswd
chroot "$MNT_ROOT" useradd -m -s /bin/bash -G sudo user 2>/dev/null || true
echo "user:user" | chroot "$MNT_ROOT" chpasswd

# /etc/fstab
cat <<'EOF' > "$MNT_ROOT/etc/fstab"
/dev/mmcblk0p2  /           ext4    errors=remount-ro,noatime  0 1
/dev/mmcblk0p1  /boot/wmt   vfat    defaults,noatime           0 0
proc            /proc       proc    defaults                   0 0
tmpfs           /tmp        tmpfs   defaults,size=64M          0 0
EOF
mkdir -p "$MNT_ROOT/boot/wmt"

# Konsola i logowanie w /etc/inittab
cat <<'EOF' > "$MNT_ROOT/etc/inittab"
id:2:initdefault:
si::sysinit:/etc/init.d/rcS
~~:S:wait:/sbin/sulogin
l0:0:wait:/etc/init.d/rc 0
l1:1:wait:/etc/init.d/rc 1
l2:2:wait:/etc/init.d/rc 2
l3:3:wait:/etc/init.d/rc 3
l4:4:wait:/etc/init.d/rc 4
l5:5:wait:/etc/init.d/rc 5
l6:6:wait:/etc/init.d/rc 6
z6:6:respawn:/sbin/sulogin
1:2345:respawn:/sbin/getty --noclear 38400 tty1
2:23:respawn:/sbin/getty 38400 tty2
EOF
mkdir -p "$MNT_ROOT/etc/inittab.d"

# Konfiguracja sieci
cat <<'EOF' > "$MNT_ROOT/etc/network/interfaces"
auto lo
iface lo inet loopback

allow-hotplug eth0
iface eth0 inet dhcp

allow-hotplug wlan0
iface wlan0 inet dhcp
    wpa-conf /etc/wpa_supplicant/wpa_supplicant.conf
EOF

mkdir -p "$MNT_ROOT/etc/wpa_supplicant"
cat <<'EOF' > "$MNT_ROOT/etc/wpa_supplicant/wpa_supplicant.conf"
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
EOF
chmod 600 "$MNT_ROOT/etc/wpa_supplicant/wpa_supplicant.conf"

# Trwałe nazewnictwo interfejsów (wyłączenie net_setup_link, zachowanie wlan0)
ln -sf /dev/null "$MNT_ROOT/etc/udev/rules.d/80-net-setup-link.rules"

# Narzędzia Wi-Fi, zasilania sprzętowego, dotyku, dźwięku oraz SOC/IDS Dashboard
mkdir -p "$MNT_ROOT/usr/local/bin" "$MNT_ROOT/etc/wm8650-soc"
if [ -f "$SCRIPT_DIR/tools/wm8650_wifi_on.c" ]; then
    arm-linux-gnueabi-gcc -O2 "$SCRIPT_DIR/tools/wm8650_wifi_on.c" -o "$MNT_ROOT/usr/local/bin/wifi-power-on" 2>/dev/null || \
    cp "$SCRIPT_DIR/tools/wm8650_wifi_on" "$MNT_ROOT/usr/local/bin/wifi-power-on" 2>/dev/null || true
fi
if [ -f "$SCRIPT_DIR/tools/wm8650_beep.c" ]; then
    arm-linux-gnueabi-gcc -O2 "$SCRIPT_DIR/tools/wm8650_beep.c" -o "$MNT_ROOT/usr/local/bin/wm8650-beep" 2>/dev/null || \
    cp "$SCRIPT_DIR/tools/wm8650_beep" "$MNT_ROOT/usr/local/bin/wm8650-beep" 2>/dev/null || true
fi
if [ -f "$SCRIPT_DIR/tools/wm8650_touchd.c" ]; then
    arm-linux-gnueabi-gcc -O2 "$SCRIPT_DIR/tools/wm8650_touchd.c" -o "$MNT_ROOT/usr/local/bin/wm8650-touchd" 2>/dev/null || \
    cp "$SCRIPT_DIR/tools/wm8650_touchd" "$MNT_ROOT/usr/local/bin/wm8650-touchd" 2>/dev/null || true
fi
[ -f "$SCRIPT_DIR/tools/wifi-menu" ] && cp "$SCRIPT_DIR/tools/wifi-menu" "$MNT_ROOT/usr/local/bin/wifi-menu"
[ -f "$SCRIPT_DIR/tools/soc" ] && cp "$SCRIPT_DIR/tools/soc" "$MNT_ROOT/usr/local/bin/soc"
[ -f "$SCRIPT_DIR/soc_dashboard/wm8650_soc_dashboard.py" ] && \
    cp "$SCRIPT_DIR/soc_dashboard/wm8650_soc_dashboard.py" "$MNT_ROOT/usr/local/bin/wm8650-soc-dashboard"
chmod 755 "$MNT_ROOT/usr/local/bin/"* 2>/dev/null || true

if [ -f "$SCRIPT_DIR/soc_dashboard/wm8650-soc.init" ]; then
    cp "$SCRIPT_DIR/soc_dashboard/wm8650-soc.init" "$MNT_ROOT/etc/init.d/wm8650-soc"
    chmod 755 "$MNT_ROOT/etc/init.d/wm8650-soc"
    chroot "$MNT_ROOT" update-rc.d wm8650-soc defaults 99 2>/dev/null || true
fi

cat <<'EOF' > "$MNT_ROOT/etc/motd"

======================================================================
  WonderMedia WM8650 - Debian 12 (Bookworm) & Linux 6.1 LTS
  - Wpisz 'soc'       aby wrocic na ekran graficzny SOC/IDS (tty3)
  - Wpisz 'wifi-menu' aby skonfigurowac polaczenie Wi-Fi
======================================================================

EOF

# Usługa wczesnego startu sprzętu (ZRAM + GPIO 6 Wi-Fi)
cat <<'EOF' > "$MNT_ROOT/etc/init.d/wm8650-boot"
#!/bin/sh
### BEGIN INIT INFO
# Provides:          wm8650-boot
# Required-Start:    $local_fs
# Required-Stop:
# Default-Start:     S
# Default-Stop:
# Short-Description: WM8650 early hardware init (WiFi power & ZRAM)
### END INIT INFO

case "$1" in
    start)
        echo "WM8650: Inicjalizacja ZRAM..."
        if [ -b /dev/zram0 ]; then
            echo lz4 > /sys/block/zram0/comp_algorithm 2>/dev/null || true
            echo 80M > /sys/block/zram0/disksize 2>/dev/null || true
            mkswap /dev/zram0 >/dev/null 2>&1 || true
            swapon -p 100 /dev/zram0 >/dev/null 2>&1 || true
        fi

        echo "WM8650: Wlaczanie zasilania karty Wi-Fi (GPIO 6)..."
        if [ -x /usr/local/bin/wifi-power-on ]; then
            /usr/local/bin/wifi-power-on >/dev/null 2>&1 || true
        fi
        ;;
    *)
        ;;
esac
exit 0
EOF
chmod 755 "$MNT_ROOT/etc/init.d/wm8650-boot"
ln -sf ../init.d/wm8650-boot "$MNT_ROOT/etc/rcS.d/S01wm8650-boot"

# Generowanie kluczy SSH
chroot "$MNT_ROOT" dpkg-reconfigure openssh-server 2>/dev/null || true

# 7. Finalizacja i bezpieczne odmontowanie
echo "[6/6] Finalizacja i odmontowywanie..."
sync
cleanup
trap - EXIT
rmdir "$MNT_ROOT" 2>/dev/null || true

echo "=================================================================="
echo "  Debian 12 (Bookworm) armel został pomyślnie zainstalowany!"
echo "  Konta:"
echo "    - root: root"
echo "    - user: user (sudo)"
echo "  Sprzęt i usługi:"
echo "    - sysvinit-core (~25 MB RAM idle, ~185 MB wolnej pamięci!)"
echo "    - ZRAM 80 MB (kompresja LZ4)"
echo "    - Wi-Fi Ralink RT3070 (GPIO 6 auto-power + wifi-menu)"
echo "    - Fast Ethernet VIA Rhine III"
echo "=================================================================="
