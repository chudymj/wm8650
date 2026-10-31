#!/bin/bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Uruchom ten skrypt z sudo:"
    echo "  sudo ./fix_sdcard.sh"
    exit 1
fi

MNT_ROOT=""
for path in /media/chudy/debian_rootfs /media/*/debian_rootfs; do
    if [ -d "$path/etc" ]; then
        MNT_ROOT="$path"
        break
    fi
done

if [ -z "$MNT_ROOT" ]; then
    echo "Blad: Nie znaleziono zamontowanej partycji debian_rootfs w /media!"
    exit 1
fi

echo "=================================================================="
echo " Naprawa czcionki i palety kolorow konsoli na: $MNT_ROOT"
echo "=================================================================="

# 1. Wylaczenie zapetlonego udevd
sed -i '2i exit 0' "$MNT_ROOT/etc/init.d/udev" 2>/dev/null || true
sed -i '2i exit 0' "$MNT_ROOT/etc/init.d/udev-mtab" 2>/dev/null || true

# 2. Skopiowanie czytelnej czcionki VGA 8x16 na karte
if [ -f /usr/share/consolefonts/Uni1-VGA16.psf.gz ]; then
    cp /usr/share/consolefonts/Uni1-VGA16.psf.gz "$MNT_ROOT/etc/console.psf.gz"
    echo "Skopiowano czcionke Uni1-VGA16 -> /etc/console.psf.gz"
fi

# 3. Skrypt w Perlu ustawiajacy tablice kolorow FBIOPUTCMAP
cat > "$MNT_ROOT/sbin/set_fb_cmap.pl" <<'EOF'
#!/usr/bin/perl
use strict;
open(my $fb, "+<", "/dev/fb0") or exit 0;

# 16-kolorowa pelna paleta VGA (kolor 7 = jaskrawy bialy 0xFFFF)
my @r = (0x0000, 0x0000, 0x0000, 0x0000, 0xaaaa, 0xaaaa, 0xaaaa, 0xffff,
         0x5555, 0x5555, 0x5555, 0x5555, 0xffff, 0xffff, 0xffff, 0xffff);
my @g = (0x0000, 0x0000, 0xaaaa, 0x5555, 0x0000, 0x0000, 0xaaaa, 0xffff,
         0x5555, 0x5555, 0xffff, 0xffff, 0x5555, 0x5555, 0xffff, 0xffff);
my @b = (0x0000, 0xaaaa, 0x0000, 0xaaaa, 0x0000, 0xaaaa, 0x0000, 0xffff,
         0x5555, 0xffff, 0x5555, 0xffff, 0x5555, 0xffff, 0x5555, 0xffff);

my $r_buf = pack("S16", @r);
my $g_buf = pack("S16", @g);
my $b_buf = pack("S16", @b);

my $r_ptr = unpack("L", pack("P", $r_buf));
my $g_ptr = unpack("L", pack("P", $g_buf));
my $b_ptr = unpack("L", pack("P", $b_buf));

my $cmap = pack("IILLLL", 0, 16, $r_ptr, $g_ptr, $b_ptr, 0);
ioctl($fb, 0x4605, $cmap); # FBIOPUTCMAP
close($fb);
EOF
chmod +x "$MNT_ROOT/sbin/set_fb_cmap.pl"

# 4. Standardowa paleta barw VGA dla konsoli (/etc/vtrgb)
cat > "$MNT_ROOT/etc/vtrgb" <<'EOF'
0,170,0,170,0,170,0,255,85,255,85,255,85,255,85,255
0,0,170,85,0,0,170,255,85,85,255,255,85,85,255,255
0,0,0,0,170,170,170,255,85,85,85,85,255,255,255,255
EOF

# 5. Aktualizacja /sbin/init-wm8650
cat > "$MNT_ROOT/sbin/init-wm8650" <<'EOF'
#!/bin/sh
/bin/mount -t proc proc /proc 2>/dev/null
/bin/mount -t sysfs sys /sys 2>/dev/null

if [ -e /proc/boot-splash ]; then
    echo 0 > /proc/boot-splash
fi

# 1. Wymuszenie trybu ekranu i reset colormap
fbset -fb /dev/fb0 -depth 16 2>/dev/null || true

# 2. Wgranie bialej palety przez ioctl FBIOPUTCMAP
/usr/bin/perl /sbin/set_fb_cmap.pl 2>/dev/null || true

# 3. Wgranie palety VGA do konsoli
if [ -x /usr/bin/setvtrgb ]; then
    /usr/bin/setvtrgb /etc/vtrgb 2>/dev/null || true
fi

# 4. Zaladowanie prawdziwej czcionki VGA 8x16
if [ -f /etc/console.psf.gz ] && [ -x /bin/setfont ]; then
    setfont /etc/console.psf.gz 2>/dev/null || true
fi

# 5. Przelaczenie wirtualnej konsoli (wymusza na fbcon odrysowanie w nowej palecie)
chvt 2 2>/dev/null || true
sleep 0.1
chvt 1 2>/dev/null || true

# 6. Kody ANSI dla bialej czcionki na czarnym tle
echo -en "\033]P7ffffff\033]P0000000\033[37;40m\033[2J\033[H" > /dev/tty0 2>/dev/null || true
echo -en "\033]P7ffffff\033]P0000000\033[37;40m\033[2J\033[H" > /dev/console 2>/dev/null || true

/bin/umount /proc 2>/dev/null
/bin/umount /sys 2>/dev/null

exec /sbin/init "$@"
EOF
chmod +x "$MNT_ROOT/sbin/init-wm8650"

# 6. Ekran logowania w /etc/issue z wyraznym naglowkiem
cat > "$MNT_ROOT/etc/issue" <<'EOF'
\033]P7ffffff\033]P0000000\033[37;40m\033[2J\033[H
===================================================
  Debian GNU/Linux 7 (WonderMedia WM8650)
  Login: root   Haslo: debian
===================================================

EOF

# 7. rc.local - powtorzenie odswiezenia konsoli i wypisanie komunikatu
cat > "$MNT_ROOT/etc/rc.local" <<'EOF'
#!/bin/sh -e
if [ -e /proc/boot-splash ]; then
    echo 0 > /proc/boot-splash
fi

# Powtorzenie ustawien czcionki i palety na koncu startu
/usr/bin/perl /sbin/set_fb_cmap.pl 2>/dev/null || true
if [ -f /etc/console.psf.gz ] && [ -x /bin/setfont ]; then
    setfont /etc/console.psf.gz 2>/dev/null || true
fi

# Odswiezenie konsoli tty1
chvt 2 2>/dev/null || true
sleep 0.1
chvt 1 2>/dev/null || true
echo -en "\033]P7ffffff\033]P0000000\033[37;40m" > /dev/tty1 2>/dev/null || true

# Ladowanie modulow sprzetowych
for mod in kpad wmt_battery_md rt3070sta; do
    insmod "/lib/modules/2.6.32.9-default/${mod}.ko" 2>/dev/null || modprobe "$mod" 2>/dev/null || true
done

# Kopia logow
mkdir -p /boot/wmt
dmesg > /boot/wmt/boot_dmesg.txt 2>/dev/null || true
echo "Debian gotowy: $(date)" > /boot/wmt/status.txt 2>/dev/null || true

exit 0
EOF
chmod +x "$MNT_ROOT/etc/rc.local"

sync
echo "=================================================================="
echo " GOTOWE! Nowa czcionka VGA i paleta FBIOPUTCMAP wgrane na karte."
echo " Mozesz teraz odmontowac karte poleceniem:"
echo "   sudo umount -R /media/chudy/WMTBOOT /media/chudy/debian_rootfs"
echo "=================================================================="
