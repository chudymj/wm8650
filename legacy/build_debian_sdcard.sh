#!/bin/bash
set -e

# ==============================================================================
# Skrypt budujacy bootowalna karte microSD z Debianem (armel) dla tabletu
# WonderMedia WM8650 (model: puzhi_7inch_vt1609_ts, kernel 2.6.32.9-default)
# ==============================================================================

if [ "$EUID" -ne 0 ]; then
    echo "Blad: Uruchom ten skrypt z uprawnieniami roota (sudo):"
    echo "  sudo $0 /dev/sdb"
    exit 1
fi

SD_DEV="${1:-/dev/sdb}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -b "$SD_DEV" ]; then
    echo "Blad: Urzadzenie blokowe $SD_DEV nie istnieje!"
    exit 1
fi

ROOT_DISK="/dev/$(lsblk -no pkname "$(findmnt -n -o SOURCE /)" 2>/dev/null | head -n1)"
if [ "$SD_DEV" = "/dev/sda" ] || [ "$SD_DEV" = "$ROOT_DISK" ]; then
    echo "BLAD BEZPIECZENSTWA: Odmowa zapisu na dysk systemowy ($SD_DEV)!"
    exit 1
fi

echo "=================================================================="
echo " Urzadzenie docelowe : $SD_DEV"
lsblk "$SD_DEV"
echo "=================================================================="
read -p "Czy na pewno chcesz sformatowac $SD_DEV i zainstalowac Debiana? [t/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[tTyY]$ ]]; then
    echo "Anulowano."
    exit 0
fi

# 1. Instalacja wymaganych narzedzi na komputerze Hosta
echo "[1/7] Sprawdzanie narzedzi (debootstrap, qemu-user-static)..."
export PATH="/usr/local/sbin:/usr/sbin:/sbin:$PATH"
NEED_PKGS=()
command -v debootstrap >/dev/null 2>&1 || NEED_PKGS+=("debootstrap")
command -v qemu-arm-static >/dev/null 2>&1 || NEED_PKGS+=("qemu-user-static" "binfmt-support")
command -v mkfs.vfat >/dev/null 2>&1 || NEED_PKGS+=("dosfstools")
command -v mkfs.ext3 >/dev/null 2>&1 || NEED_PKGS+=("e2fsprogs")
command -v sfdisk >/dev/null 2>&1 || NEED_PKGS+=("fdisk")

if [ ${#NEED_PKGS[@]} -gt 0 ]; then
    echo "Instalowanie brakujacych pakietow: ${NEED_PKGS[*]}..."
    apt-get update
    apt-get install -y "${NEED_PKGS[@]}"
fi

# 2. Odmontowanie partycji karty SD
echo "[2/7] Odmontowywanie istniejacych partycji na $SD_DEV..."
for part in "${SD_DEV}"*; do
    umount "$part" 2>/dev/null || true
done

# 3. Partycjonowanie karty SD (MBR: p1 = 64MB FAT32, p2 = reszta EXT3)
echo "[3/7] Partycjonowanie karty $SD_DEV..."
dd if=/dev/zero of="$SD_DEV" bs=1M count=4 status=none
sfdisk "$SD_DEV" <<EOF
label: dos
,64M,0c,*
,,83,-
EOF

partprobe "$SD_DEV" 2>/dev/null || true
sleep 2

if [[ "$SD_DEV" =~ [0-9]$ ]]; then
    PART_BOOT="${SD_DEV}p1"
    PART_ROOT="${SD_DEV}p2"
else
    PART_BOOT="${SD_DEV}1"
    PART_ROOT="${SD_DEV}2"
fi

echo "[4/7] Formatowanie partycji ($PART_BOOT -> FAT32, $PART_ROOT -> EXT3 dla jądra 2.6.32)..."
mkfs.vfat -F 32 -n "WMTBOOT" "$PART_BOOT"
# Inode 128 bajtow oraz wylaczenie flag z ext4 zapewnia 100% kompatybilnosci z jadrem 2.6.32.9
mkfs.ext3 -F -L "debian_rootfs" -I 128 -O ^64bit,^metadata_csum "$PART_ROOT" 2>/dev/null || \
    mkfs.ext3 -F -L "debian_rootfs" -I 128 "$PART_ROOT"

# 5. Przygotowanie partycji startowej FAT32 (wmt_scriptcmd)
echo "[5/7] Generowanie i kopiowanie skryptu U-Boot (wmt_scriptcmd)..."
MNT_BOOT="/mnt/wm8650_boot"
MNT_ROOT="/mnt/wm8650_root"
mkdir -p "$MNT_BOOT" "$MNT_ROOT"

mount "$PART_BOOT" "$MNT_BOOT"
python3 "$SCRIPT_DIR/make_wmt_scriptcmd.py" "$MNT_BOOT/wmt_scriptcmd"
mkdir -p "$MNT_BOOT/script"
cp "$MNT_BOOT/wmt_scriptcmd" "$MNT_BOOT/script/wmt_scriptcmd"
cp "$MNT_BOOT/wmt_scriptcmd" "$MNT_BOOT/script/scriptcmd"
sync
umount "$MNT_BOOT"

# 6. Pobieranie i instalacja systemu Debian Wheezy (armel)
echo "[6/7] Pobieranie systemu bazowego Debian 7 (Wheezy) armel przez debootstrap..."
mount "$PART_ROOT" "$MNT_ROOT"

CACHE_TAR="$SCRIPT_DIR/debian_wheezy_armel_cache.tar"
debootstrap --arch=armel --foreign --no-check-gpg \
    --include=openssh-server,wireless-tools,wpasupplicant,fbset,kbd,nano,htop,usbutils,alsa-utils,net-tools,isc-dhcp-client,iproute,iputils-ping \
    wheezy "$MNT_ROOT" http://archive.debian.org/debian/

cp /usr/bin/qemu-arm-static "$MNT_ROOT/usr/bin/"

echo "Uruchamianie drugiego etapu instalacji (debootstrap --second-stage w QEMU ARM)..."
chroot "$MNT_ROOT" /debootstrap/debootstrap --second-stage

# 7. Konfiguracja systemu pod sprzęt WonderMedia WM8650
echo "[7/7] Konfiguracja urzadzen, ekranu LCD (boot-splash fix), sieci i modulow NAND..."

# Statyczne węzły /dev wymagane przez jądro 2.6.32 przed uruchomieniem udev
mknod -m 600 "$MNT_ROOT/dev/console" c 5 1 2>/dev/null || true
mknod -m 666 "$MNT_ROOT/dev/null"    c 1 3 2>/dev/null || true
mknod -m 666 "$MNT_ROOT/dev/zero"    c 1 5 2>/dev/null || true
mknod -m 666 "$MNT_ROOT/dev/tty"     c 5 0 2>/dev/null || true
for i in 0 1 2 3 4 5 6; do
    mknod -m 620 "$MNT_ROOT/dev/tty$i" c 4 $i 2>/dev/null || true
done
mknod -m 660 "$MNT_ROOT/dev/ttyS0"     c 4 64  2>/dev/null || true
mknod -m 660 "$MNT_ROOT/dev/fb0"       c 29 0  2>/dev/null || true
mknod -m 660 "$MNT_ROOT/dev/wmtgpio"   c 253 0 2>/dev/null || true
mknod -m 660 "$MNT_ROOT/dev/mmcblk0"   b 179 0 2>/dev/null || true
mknod -m 660 "$MNT_ROOT/dev/mmcblk0p1" b 179 1 2>/dev/null || true
mknod -m 660 "$MNT_ROOT/dev/mmcblk0p2" b 179 2 2>/dev/null || true
for i in $(seq 0 16); do
    mknod -m 660 "$MNT_ROOT/dev/mtdblock$i" b 31 $i 2>/dev/null || true
done

# Wrapper /sbin/init-wm8650 wylaczajacy animacje paska postepu jadra (/proc/boot-splash)
# i przelaczajacy kontroler obrazu WM8650 z YUV444 (logo) na RGB (/dev/fb0 - konsola tekstowa)
cat > "$MNT_ROOT/sbin/init-wm8650" <<'EOF'
#!/bin/sh
/bin/mount -t proc proc /proc 2>/dev/null
if [ -e /proc/boot-splash ]; then
    echo 0 > /proc/boot-splash
fi
/bin/umount /proc 2>/dev/null

# Reset palety i wymuszenie bialej czcionki na czarnym tle dla fbcon
echo -en "\033]P7ffffff\033]P0000000\033[37;40m\033[2J\033[H" > /dev/tty0 2>/dev/null || true
echo -en "\033]P7ffffff\033]P0000000\033[37;40m\033[2J\033[H" > /dev/console 2>/dev/null || true

exec /sbin/init "$@"
EOF
chmod +x "$MNT_ROOT/sbin/init-wm8650"

# Wymuszenie bialej czcionki na ekranie logowania
cat > "$MNT_ROOT/etc/issue" <<'EOF'
\033]P7ffffff\033]P0000000\033[37;40m\033[2J\033[H
Debian GNU/Linux 7 (WM8650) \n \l

EOF

# Wylaczenie udevd - jądro 2.6.32 na ARM nie posiada wywolania accept4(),
# przez co udevd wpada w petle bledow zabierajac 100% CPU i blokujac system.
# Wszystkie wezly /dev sa juz wygenerowane statycznie.
sed -i '2i exit 0' "$MNT_ROOT/etc/init.d/udev" 2>/dev/null || true
sed -i '2i exit 0' "$MNT_ROOT/etc/init.d/udev-mtab" 2>/dev/null || true

# Nazwa hosta
echo "wm8650-debian" > "$MNT_ROOT/etc/hostname"
cat > "$MNT_ROOT/etc/hosts" <<'EOF'
127.0.0.1   localhost wm8650-debian
EOF

# /etc/fstab
mkdir -p "$MNT_ROOT/boot/wmt" "$MNT_ROOT/mnt/nand"
cat > "$MNT_ROOT/etc/fstab" <<'EOF'
/dev/mmcblk0p2  /           ext3    errors=remount-ro,noatime  0 1
/dev/mmcblk0p1  /boot/wmt   vfat    defaults,noatime           0 0
proc            /proc       proc    defaults                   0 0
tmpfs           /tmp        tmpfs   defaults,size=32M          0 0
EOF

# Konfiguracja sieci (automatyczne DHCP na porcie Ethernet w przejsciowce + przygotowanie Wi-Fi ra0)
cat > "$MNT_ROOT/etc/network/interfaces" <<'EOF'
auto lo
iface lo inet loopback

auto eth0
allow-hotplug eth0
iface eth0 inet dhcp

# Wbudowane Wi-Fi Ralink RT3070 (interfejs ra0):
# Odblokuj ponizsze linie i wpisz dane swojej sieci Wi-Fi, jesli chcesz laczyc sie bezprzewodowo:
# allow-hotplug ra0
# iface ra0 inet dhcp
#     wpa-ssid "Twoja_Nazwa_WiFi"
#     wpa-psk "Twoje_Haslo_WiFi"
EOF

# Repozytoria archiwalne Debiana Wheezy
cat > "$MNT_ROOT/etc/apt/sources.list" <<'EOF'
deb http://archive.debian.org/debian/ wheezy main contrib non-free
EOF

cat > "$MNT_ROOT/etc/apt/apt.conf.d/99archive" <<'EOF'
Acquire::Check-Valid-Until "false";
APT::Get::AllowUnauthenticated "true";
EOF

# Dodanie konsoli szeregowej ttyS0 obok konsol na ekranie LCD (tty1..tty6)
if ! grep -q "ttyS0" "$MNT_ROOT/etc/inittab"; then
    echo "T0:23:respawn:/sbin/getty -L ttyS0 115200 vt100" >> "$MNT_ROOT/etc/inittab"
fi

# Skrypt /etc/rc.local:
# 1. Upewnia sie, ze boot-splash jest wylaczony.
# 2. Przy pierwszym uruchomieniu montuje partycje NAND Androida (/dev/mtdblock11)
#    i automatycznie kopiuje oryginalne moduly jadra (.ko) oraz konfiguracje Wi-Fi Ralink!
cat > "$MNT_ROOT/etc/rc.local" <<'EOF'
#!/bin/sh -e
if [ -e /proc/boot-splash ]; then
    echo 0 > /proc/boot-splash
fi

MODULES_DIR="/lib/modules/2.6.32.9-default"
if [ ! -d "$MODULES_DIR" ] || [ -z "$(ls -A "$MODULES_DIR" 2>/dev/null)" ]; then
    echo "[WM8650] Pierwsze uruchomienie: importowanie modulow jadra z pamieci NAND (mtdblock11)..."
    mkdir -p /mnt/nand "$MODULES_DIR"
    if mount -t yaffs2 -o ro /dev/mtdblock11 /mnt/nand 2>/dev/null; then
        if [ -d /mnt/nand/lib/modules ]; then
            cp -a /mnt/nand/lib/modules/* /lib/modules/ 2>/dev/null || true
        fi
        find /mnt/nand -name "*.ko" -exec cp -a {} "$MODULES_DIR/" \; 2>/dev/null || true
        if [ -d /mnt/nand/etc/Wireless ]; then
            mkdir -p /etc/Wireless
            cp -a /mnt/nand/etc/Wireless/* /etc/Wireless/ 2>/dev/null || true
        fi
        umount /mnt/nand 2>/dev/null || true
        depmod -a 2>/dev/null || true
        echo "[WM8650] Zaimportowano moduly jadra z pamieci NAND."
    fi
fi

# Ladowanie modulow sprzetowych tabletu WM8650 (przyciski fizyczne, bateria, Wi-Fi)
for mod in kpad wmt_battery_md rt3070sta; do
    insmod "/lib/modules/2.6.32.9-default/${mod}.ko" 2>/dev/null || modprobe "$mod" 2>/dev/null || true
done

# Kopia logow dmesg na partycje startowa FAT32 do diagnostyki
mkdir -p /boot/wmt
dmesg > /boot/wmt/boot_dmesg.txt 2>/dev/null || true
echo "Debian uruchomiony: $(date)" > /boot/wmt/status.txt 2>/dev/null || true

exit 0
EOF
chmod +x "$MNT_ROOT/etc/rc.local"

# Ustawienie hasla root = debian oraz wlaczenie logowania root przez SSH
chroot "$MNT_ROOT" /bin/sh -c '
    echo "root:debian" | chpasswd
    if [ -f /etc/ssh/sshd_config ]; then
        sed -i "s/^#*PermitRootLogin.*/PermitRootLogin yes/" /etc/ssh/sshd_config
    fi
'

sync
umount -R "$MNT_ROOT" 2>/dev/null || (umount "$MNT_ROOT/proc" 2>/dev/null || true; umount "$MNT_ROOT" 2>/dev/null || true)
rmdir "$MNT_BOOT" "$MNT_ROOT" 2>/dev/null || true

echo "=================================================================="
echo " GOTOWE! Karta microSD ($SD_DEV) z Debianem dla WM8650 jest gotowa!"
echo "=================================================================="
echo " Dane logowania w Debianie:"
echo "   Login : root"
echo "   Haslo : debian"
echo "=================================================================="
