#!/bin/bash
set -e

# ==============================================================================
# Szybka aktualizacja / instalacja pakietu WM8650 SOC & IDS Dashboard
# BEZ formatowania karty SD i bez reinstalacji systemu Debian 12!
#
# Obsługuje dwa tryby pracy:
#   Tryb 1 (karta SD w czytniku PC):
#     sudo ./update_soc_dashboard.sh /dev/mmcblk0   (lub /dev/sdX)
#
#   Tryb 2 (przez SSH na włączony tablet w sieci LAN):
#     ./update_soc_dashboard.sh root@192.168.1.XX
# ==============================================================================

TARGET="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$TARGET" ]; then
    echo "Użycie:"
    echo "  1) Aktualizacja istniejącej karty SD w czytniku (bez formatowania):"
    echo "     sudo $0 /dev/mmcblk0   (lub /dev/sdb)"
    echo ""
    echo "  2) Aktualizacja przez SSH na działający tablet:"
    echo "     $0 root@<IP_TABLETU>"
    exit 1
fi

echo "[1/4] Kompilacja narzędzi sprzętowych C (wm8650_wifi_on, wm8650_beep, wm8650_touchd)..."
if ! command -v arm-linux-gnueabi-gcc >/dev/null 2>&1; then
    echo "Brak kompilatora arm-linux-gnueabi-gcc. Instalowanie gcc-arm-linux-gnueabi..."
    sudo apt-get update && sudo apt-get install -y gcc-arm-linux-gnueabi
fi
make -C "$SCRIPT_DIR/tools"

# ------------------------------------------------------------------------------
# TRYB 1: Urządzenie blokowe karty SD (/dev/sdX lub /dev/mmcblk0)
# ------------------------------------------------------------------------------
if [[ "$TARGET" == /dev/* ]]; then
    if [ "$EUID" -ne 0 ]; then
        echo "Błąd: Aktualizacja karty SD w czytniku wymaga uprawnień roota (sudo):"
        echo "  sudo $0 $TARGET"
        exit 1
    fi

    if [[ "$TARGET" =~ [0-9]$ ]]; then
        PART_ROOT="${TARGET}p2"
    else
        PART_ROOT="${TARGET}2"
    fi

    # Jeśli użytkownik podał bezpośrednio partycję np. /dev/sdb2
    if [ ! -b "$PART_ROOT" ] && [ -b "$TARGET" ]; then
        PART_ROOT="$TARGET"
    fi

    if [ ! -b "$PART_ROOT" ]; then
        echo "Błąd: Partycja Linuksa $PART_ROOT nie istnieje!"
        exit 1
    fi

    MNT_ROOT="/mnt/wm8650_update"
    mkdir -p "$MNT_ROOT"

    cleanup() {
        umount -l "$MNT_ROOT/proc" 2>/dev/null || true
        umount -l "$MNT_ROOT/sys" 2>/dev/null || true
        umount -l "$MNT_ROOT/dev/pts" 2>/dev/null || true
        umount -l "$MNT_ROOT/dev" 2>/dev/null || true
        umount -l "$MNT_ROOT" 2>/dev/null || true
        rmdir "$MNT_ROOT" 2>/dev/null || true
    }
    trap cleanup EXIT

    echo "[2/4] Montowanie partycji $PART_ROOT (bez formatowania)..."
    umount "$PART_ROOT" 2>/dev/null || true
    mount "$PART_ROOT" "$MNT_ROOT"

    echo "[3/4] Kopiowanie binarek, dashboardu SOC/IDS oraz usługi startowej..."
    mkdir -p "$MNT_ROOT/usr/local/bin" "$MNT_ROOT/etc/wm8650-soc"
    cp -v "$SCRIPT_DIR/tools/wm8650_wifi_on" "$MNT_ROOT/usr/local/bin/wifi-power-on"
    cp -v "$SCRIPT_DIR/tools/wm8650_beep" "$MNT_ROOT/usr/local/bin/wm8650-beep"
    cp -v "$SCRIPT_DIR/tools/wm8650_touchd" "$MNT_ROOT/usr/local/bin/wm8650-touchd"
    cp -v "$SCRIPT_DIR/tools/wifi-menu" "$MNT_ROOT/usr/local/bin/wifi-menu"
    cp -v "$SCRIPT_DIR/tools/soc" "$MNT_ROOT/usr/local/bin/soc"
    cp -v "$SCRIPT_DIR/soc_dashboard/wm8650_soc_dashboard.py" "$MNT_ROOT/usr/local/bin/wm8650-soc-dashboard"
    chmod 755 "$MNT_ROOT/usr/local/bin/"*

    cp -v "$SCRIPT_DIR/soc_dashboard/wm8650-soc.init" "$MNT_ROOT/etc/init.d/wm8650-soc"
    chmod 755 "$MNT_ROOT/etc/init.d/wm8650-soc"

    cat <<'EOF' > "$MNT_ROOT/etc/motd"

======================================================================
  WonderMedia WM8650 - Debian 12 (Bookworm) & Linux 6.1 LTS
  - Wpisz 'soc'       aby wrocic na ekran graficzny SOC/IDS (tty3)
  - Wpisz 'wifi-menu' aby skonfigurowac polaczenie Wi-Fi
======================================================================

EOF

    echo "[4/4] Sprawdzanie pakietów Python/Pillow/kbd wewnątrz chroot i aktywacja usługi..."
    [ -f /usr/bin/qemu-arm-static ] && cp /usr/bin/qemu-arm-static "$MNT_ROOT/usr/bin/"
    cp /etc/resolv.conf "$MNT_ROOT/etc/resolv.conf" 2>/dev/null || true
    mount -t proc proc "$MNT_ROOT/proc"
    mount -t sysfs sys "$MNT_ROOT/sys"
    mount -o bind /dev "$MNT_ROOT/dev"
    mount -o bind /dev/pts "$MNT_ROOT/dev/pts"

    chroot "$MNT_ROOT" bash -c "
        export DEBIAN_FRONTEND=noninteractive
        if ! dpkg -s python3-pil fonts-dejavu-core kbd iputils-ping >/dev/null 2>&1; then
            apt-get update
            apt-get install -y --no-install-recommends python3-minimal python3-pil fonts-dejavu-core kbd iputils-ping
            apt-get clean
        fi
        update-rc.d wm8650-soc defaults 99
    "

    sync
    cleanup
    trap - EXIT
    echo "=================================================================="
    echo " Gotowe! Karta SD została zaktualizowana o SOC/IDS Dashboard."
    echo " Możesz przełożyć ją do tabletu i uruchomić urządzenie."
    echo "=================================================================="
    exit 0
fi

# ------------------------------------------------------------------------------
# TRYB 2: Wdrożenie przez SSH na działający tablet (np. root@192.168.1.50)
# ------------------------------------------------------------------------------
if [[ "$TARGET" != *@* ]]; then
    SSH_TARGET="root@$TARGET"
else
    SSH_TARGET="$TARGET"
fi

echo "[2/4] Przesyłanie plików przez SCP do $SSH_TARGET:/tmp/..."
scp "$SCRIPT_DIR/tools/wm8650_wifi_on" \
    "$SCRIPT_DIR/tools/wm8650_beep" \
    "$SCRIPT_DIR/tools/wm8650_touchd" \
    "$SCRIPT_DIR/tools/wifi-menu" \
    "$SCRIPT_DIR/tools/soc" \
    "$SCRIPT_DIR/soc_dashboard/wm8650_soc_dashboard.py" \
    "$SCRIPT_DIR/soc_dashboard/wm8650-soc.init" \
    "$SSH_TARGET:/tmp/"

echo "[3/4] Instalacja plików i zależności na tablecie..."
ssh "$SSH_TARGET" "sh -e -c '
    if [ \"\$(id -u)\" -ne 0 ]; then
        SUDO=\"sudo\"
    else
        SUDO=\"\"
    fi
    \$SUDO mkdir -p /usr/local/bin /etc/wm8650-soc
    \$SUDO mv /tmp/wm8650_wifi_on /usr/local/bin/wifi-power-on
    \$SUDO mv /tmp/wm8650_beep /usr/local/bin/wm8650-beep
    \$SUDO mv /tmp/wm8650_touchd /usr/local/bin/wm8650-touchd
    \$SUDO mv /tmp/wifi-menu /usr/local/bin/wifi-menu
    \$SUDO mv /tmp/soc /usr/local/bin/soc
    \$SUDO mv /tmp/wm8650_soc_dashboard.py /usr/local/bin/wm8650-soc-dashboard
    \$SUDO chmod 755 /usr/local/bin/wifi-power-on /usr/local/bin/wm8650-beep /usr/local/bin/wm8650-touchd /usr/local/bin/wifi-menu /usr/local/bin/soc /usr/local/bin/wm8650-soc-dashboard

    \$SUDO mv /tmp/wm8650-soc.init /etc/init.d/wm8650-soc
    \$SUDO chmod 755 /etc/init.d/wm8650-soc

    if ! dpkg -s python3-pil fonts-dejavu-core kbd iputils-ping >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        \$SUDO apt-get update
        \$SUDO apt-get install -y --no-install-recommends python3-minimal python3-pil fonts-dejavu-core kbd iputils-ping
        \$SUDO apt-get clean
    fi

    \$SUDO update-rc.d wm8650-soc defaults 99
    \$SUDO service wm8650-soc restart
'"

echo "[4/4] Zakończono!"
echo "=================================================================="
echo " Dashboard SOC/IDS został zainstalowany i uruchomiony na tablecie!"
echo "=================================================================="
