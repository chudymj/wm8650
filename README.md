# Debian GNU/Linux (`armel`) dla tabletu WonderMedia WM8650

Zestaw narzędzi i skryptów pozwalający zbudować bootowalną kartę microSD z systemem **Debian GNU/Linux (`armel`)** dla tabletu opartego o procesor **WonderMedia WM8650** (ARM926EJ-S / ARMv5TEJ) bez modyfikowania wewnętrznej pamięci NAND urządzenia.

## Specyfikacja docelowego urządzenia (`puzhi_7inch_vt1609_ts`)

* **SoC:** WonderMedia WM8650 (ARM926EJ-S rev 5, ARMv5TEJ, ~800 MHz)
* **RAM:** 256 MB (212 MB dostępne dla jądra Linux, reszta zarezerwowana dla buforów wideo VPU/GOVW oraz framebuffera)
* **Pamięć wewnętrzna:**
  * SPI Flash (`mtd0..mtd5`, 512 KB): `w-load`, `U-Boot 1.1.4` oraz zmienne środowiskowe U-Boota
  * NAND Flash (`mtd6..mtd16`, 2 GB Samsung `K9GAG08U0E`): jądro Linux `2.6.32.9-default` pod adresem `0x1300000` (`mtd9`) oraz system Android 2.2 (Uberoid) na partycji `yaffs2` (`mtd11`)
* **Wyświetlacz:** 7" LCD `800x480@60Hz` (`wmtfb` `/dev/fb0`, wbudowana konsola `fbcon` 100x30 znaków)
* **Dotyk:** Kontroler oporowy `VT1609` na magistrali SPI0
* **Dźwięk:** Kodek `VT1603` I2S (`WMT_SOC`)
* **Sieć:**
  * Przewodowa (przez adapter 30-pin): `VIA Rhine III Fast Ethernet` (`eth0`, sterownik wbudowany w jądro)
  * Bezprzewodowa (wewnętrzne USB `1-4`): `Ralink RT3070` (`rt3070sta.ko`, interfejs `ra0`)

## Zawartość repozytorium

* `build_debian_sdcard.sh` – główny skrypt automatyzujący partycjonowanie karty microSD, instalację systemu Debian 7 (Wheezy) `armel` przez `debootstrap` + `qemu-user-static` oraz konfigurację sprzętową pod WM8650.
* `make_wmt_scriptcmd.py` – skrypt w Pythonie generujący binarny obraz startowy `wmt_scriptcmd` dla bootloadera U-Boot (format `IH_TYPE_SCRIPT` dla komendy `autoscr`).
* `wmt_scriptcmd` – wygenerowany plik startowy U-Boota.
* `dump.sh` – skrypt pomocniczy uruchamiany na Androidzie (Uberoid) w celu zgrania konfiguracji sprzętowej tabletu.
* `backup_wm8650/` – logi diagnostyczne i konfiguracja zgrana z tabletu (`cmdline.txt`, `mtd.txt`, `lsmod.txt`, `dmesg.txt`, `uboot_env.txt`).

## Jak działa uruchomienie z karty microSD?

1. Po włączeniu tabletu bootloader **U-Boot** z pamięci SPI Flash inicjalizuje czytnik kart (`mmcinit 0`) i szuka na pierwszej partycji FAT32 pliku `/wmt_scriptcmd` (`fatload mmc 0 0 wmt_scriptcmd; autoscr 0`).
2. Skrypt `wmt_scriptcmd`:
   * wyświetla komunikaty statusu bezpośrednio na ekranie tabletu (`textout`),
   * wczytuje fabryczne jądro `2.6.32.9-default` z pamięci NAND (`nandrw r 0x1300000 0x1000000 0x800000`) do pamięci RAM,
   * ustawia parametry startowe jądra (`bootargs`) wskazujące na drugą partycję karty microSD (`root=/dev/mmcblk0p2`) oraz wrapper `/sbin/init-wm8650`.
3. Wrapper `/sbin/init-wm8650` zapisuje `0` do `/proc/boot-splash`, co zatrzymuje wątek animacji paska postępu w jądrze WM8650 i przełącza warstwę obrazu z YUV444 (logo startowe) na RGB (`/dev/fb0` – konsola tekstowa Linuksa).
4. Podczas pierwszego startu `/etc/rc.local` automatycznie montuje partycję NAND Androida (`/dev/mtdblock11`) w trybie tylko do odczytu i kopiuje do Debiana oryginalne moduły jądra (`.ko`), w tym sterownik Wi-Fi `rt3070sta.ko`, sterownik baterii `wmt_battery_md.ko` oraz obsługę przycisków fizycznych `kpad.ko`.

## Budowanie karty microSD

Na komputerze z systemem Linux (Debian / Ubuntu / Mint) włóż kartę microSD, sprawdź jej nazwę poleceniem `lsblk` (np. `/dev/sdb`), a następnie uruchom:

```bash
chmod +x build_debian_sdcard.sh make_wmt_scriptcmd.py
sudo ./build_debian_sdcard.sh /dev/sdX
```

### Domyślne dane logowania w Debianie
* **Login:** `root`
* **Hasło:** `debian`
*(Serwer SSH oraz klient DHCP na interfejsie `eth0` uruchamiają się automatycznie przy starcie).*
