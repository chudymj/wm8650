#!/bin/bash
set -e

# ==============================================================================
# Skrypt automatycznej kompilacji jądra Mainline Linux 6.1 LTS dla WM8650
# ==============================================================================

KERNEL_VER="6.1.191"
KERNEL_ARCHIVE="linux-${KERNEL_VER}.tar.xz"
KERNEL_URL="https://cdn.kernel.org/pub/linux/kernel/v6.x/${KERNEL_ARCHIVE}"
KERNEL_DIR="linux-${KERNEL_VER}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=================================================================="
echo " Budowanie jądra Linux ${KERNEL_VER} dla WonderMedia WM8650"
echo "=================================================================="

# Sprawdzenie zależności na maszynie budującej
NEED_PKGS=()
command -v arm-linux-gnueabi-gcc >/dev/null 2>&1 || NEED_PKGS+=("gcc-arm-linux-gnueabi")
command -v mkimage >/dev/null 2>&1 || NEED_PKGS+=("u-boot-tools")
command -v bison >/dev/null 2>&1 || NEED_PKGS+=("bison")
command -v flex >/dev/null 2>&1 || NEED_PKGS+=("flex")
command -v wget >/dev/null 2>&1 || NEED_PKGS+=("wget")

if [ ${#NEED_PKGS[@]} -gt 0 ]; then
    echo "Instalacja brakujących pakietów: ${NEED_PKGS[*]}..."
    sudo apt-get update && sudo apt-get install -y "${NEED_PKGS[@]}" libssl-dev libelf-dev bc
fi

cd "$ROOT_DIR"

# Pobieranie źródeł
if [ ! -d "$KERNEL_DIR" ]; then
    if [ ! -f "$KERNEL_ARCHIVE" ]; then
        echo "Pobieranie źródeł jądra ${KERNEL_VER}..."
        wget "$KERNEL_URL"
    fi
    echo "Rozpakowywanie źródeł..."
    tar -xf "$KERNEL_ARCHIVE"
fi

cd "$KERNEL_DIR"

# Aplikowanie konfiguracji i drzewa urządzeń (DTS)
echo "Kopiowanie konfiguracji i DTS..."
cp "$SCRIPT_DIR/wm8650_defconfig" arch/arm/configs/wm8650_defconfig
cp "$SCRIPT_DIR/wm8650-mid.dts" arch/arm/boot/dts/wm8650-mid.dts

export ARCH=arm
export CROSS_COMPILE=arm-linux-gnueabi-

echo "Konfigurowanie jądra (wm8650_defconfig)..."
make wm8650_defconfig

NPROC=$(nproc || echo 4)
echo "Kompilacja jądra i drzewa urządzeń (wątki: $NPROC)..."
make -j"$NPROC" zImage wm8650-mid.dtb modules

echo "Tworzenie obrazu zImage z dołączonym Device Tree (DTB)..."
cat arch/arm/boot/zImage arch/arm/boot/dts/wm8650-mid.dtb > "$ROOT_DIR/zImage-dtb"

echo "Generowanie obrazu U-Boot (uImage)..."
mkimage -A arm -O linux -T kernel -C none -a 0x8000 -e 0x8000 \
    -n "Linux ${KERNEL_VER} (WM8650)" \
    -d "$ROOT_DIR/zImage-dtb" "$ROOT_DIR/uImage"

echo "Instalowanie modułów jądra..."
rm -rf "$ROOT_DIR/modules_wm8650"
make INSTALL_MOD_PATH="$ROOT_DIR/modules_wm8650" modules_install

echo "=================================================================="
echo " Sukces! Obraz uImage oraz moduły zostały wygenerowane:"
echo "   - Obraz jądra: $ROOT_DIR/uImage"
echo "   - Moduły:      $ROOT_DIR/modules_wm8650/"
echo "=================================================================="
