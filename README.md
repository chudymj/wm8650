# Debian 12 (Bookworm) & Mainline Linux 6.1 LTS dla WonderMedia WM8650

Kompletny zestaw narzędzi, konfiguracji i skryptów umożliwiający uruchomienie nowoczesnego systemu **Debian 12 (Bookworm) `armel`** z jądrem **Mainline Linux 6.1 LTS** na chińskim tablecie z procesorem **WonderMedia WM8650** (ARM926EJ-S / ARMv5TEJ).

Projekt zastępuje przestarzałego i nieużywalnego Androida 2.2 (Froyo) / Linuksa 2.6.32 ultralekkim, w pełni funkcjonalnym systemem serwerowo-konsolowym ze wsparciem dla sieci Wi-Fi, Ethernet, ZRAM oraz nowoczesnych protokołów (OpenSSH, WPA2, TLS 1.3).

> 🛡️ **NOWOŚĆ (Gałąź `feature/soc-ids-dashboard`):**
> Pełna specyfikacja techniczna i plan wdrożenia **Domowego Monitora Sieci + Systemu Wykrywania Włamań (IDS / Canary Honeypot)** na 5 przełączanych ekranach framebuffera (`/dev/fb0`) z obsługą ekranu dotykowego (`VT1609`), alarmów dźwiękowych (`VT1603 I2S`) + wibracji oraz przełączaniem na konsolę (`tty1` ↔ `tty3`) znajduje się w pliku **[PLAN_ROZBUDOWY_SOC_IDS.md](./PLAN_ROZBUDOWY_SOC_IDS.md)**.

---

## 📱 Specyfikacja sprzętowa tabletu (`puzhi_7inch_vt1609_ts`)

* **SoC:** WonderMedia WM8650 (ARM926EJ-S rev 5, architektura `armel` / ARMv5TEJ, ~800 MHz)
* **Pamięć RAM:** 256 MB DDR2 (dostępne ~231 MB dla Linuksa, ~25 MB zajęte po starcie, **~185 MB wolnego RAM-u!**)
* **Swap w RAM:** ZRAM (80 MB skompresowanej przestrzeni wymiany algorytmem LZ4)
* **Wyświetlacz:** 7" TFT LCD 800x480 (`vt8500-fb`, konsola tekstowa `fbcon` z pingwinem Tux)
* **Łączność:**
  * **Wi-Fi:** Wewnętrzny moduł USB Ralink RT3070 (`148f:2070`) na porcie USB 4, sterowany linią zasilania GPIO Bank 0 Pin 6 (otwarty sterownik `rt2800usb` + firmware `rt2870.bin`)
  * **Ethernet:** Zintegrowany kontroler VIA Rhine III Fast Ethernet (`eth0`, adapter 30-pin)
* **Pamięć masowa:**
  * **Karta microSD:** minimum **1 GB**, zalecana **2 GB – 4 GB** (obsługa kart SD/SDHC do 32 GB, MBR)
  * **SPI NOR Flash** (512 KB, `mtd0..mtd5`): `w-load`, `U-Boot 1.1.4` (nietykalna – gwarantuje brak możliwości uceglenia urządzenia)
  * **NAND Flash** (2 GB Samsung `K9GAG08U0E`, `mtd6..mtd16`): oryginalne partycje Androida 2.2

---

## 🚀 Kluczowe osiągnięcia techniczne

1. **Jądro Mainline Linux 6.1 LTS z Device Tree:**
   * Zastąpienie archaicznego jądra 2.6.32 z 2011 roku nowoczesnym jądrem 6.1 LTS.
   * Obsługa Device Tree (`arch/arm/boot/dts/wm8650-mid.dts`) z pełną deklaracją 256 MB RAM oraz natywnymi timingami matrycy LCD 800x480.
   * Rozwiązano problem zniekształceń i czarnych bloków czcionki (framebuffer konsoli `fbcon` działa w natywnej 16-bitowej przestrzeni RGB565).
2. **Optymalizacja pamięci RAM (Debian 12 + `sysvinit-core`):**
   * Zamiast ciężkiego `systemd` (który zużywałby ~80 MB RAM i powodował OOM), system działa na klasycznym `sysvinit-core`.
   * Całkowite zużycie RAM w spoczynku to zaledwie **~25 MB**, co pozostawia ponad 185 MB czystej pamięci operacyjnej na aplikacje użytkownika.
3. **Sterowanie zasilaniem Wi-Fi przez GPIO:**
   * Karta Wi-Fi (Ralink RT3070) jest podłączona do wewnętrznego portu USB, którego zasilanie (3.3V) jest kontrolowane przez pin 6 banku 0 kontrolera GPIO procesora WM8650.
   * Opracowano dedykowany program C (`tools/wm8650_wifi_on.c`), który mapuje rejestry GPIO (`0xd8110000`) przez `/dev/mem`, resetuje zasilanie i utrzymuje stan wysoki.
   * Włączenie zasilania zostało zautomatyzowane w skrypcie startowym `/etc/init.d/wm8650-boot`.
4. **Wygodny graficzny konfigurator Wi-Fi (`wifi-menu`):**
   * Narzędzie konsolowe ncurses (`whiptail`), które skanuje eter radiowy, wyświetla listę dostępnych sieci wraz z siłą sygnału w dBm, pyta o hasło i automatycznie zestawia połączenie WPA2/DHCP.
5. **Autonomiczny start z karty microSD:**
   * Za pomocą `wmt_scriptcmd` bootloader U-Boot wczytuje `uImage` bezpośrednio z pierwszej partycji FAT32 karty SD (`fatload mmc 0 0x2000000 uImage; bootm 0x2000000`) bez dotykania pamięci wewnętrznej tabletu.

---

## 📂 Struktura repozytorium

```
wm8650/
├── install_debian12_bookworm.sh  # Główny skrypt instalacyjny Debiana 12 Bookworm na kartę SD
├── make_wmt_scriptcmd.py         # Skrypt generujący binarny obraz startowy wmt_scriptcmd dla U-Boota
├── wmt_scriptcmd                 # Wygenerowany skrypt startowy U-Boota dla karty SD
├── dump.sh                       # Skrypt zrzucający dane sprzętowe uruchamiany na Androidzie
│
├── kernel/                       # Pliki źródłowe jądra Mainline 6.1 LTS
│   ├── wm8650_defconfig          # Zoptymalizowana konfiguracja jądra (savedefconfig)
│   ├── wm8650-mid.dts            # Drzewo urządzeń (DTS) z konfiguracją pamięci i LCD
│   └── build_kernel.sh           # Zautomatyzowany skrypt pobierający i kompilujący Linux 6.1 LTS
│
├── tools/                        # Narzędzia systemowe
│   ├── wm8650_wifi_on.c          # Program C włączający zasilanie Wi-Fi (GPIO bank 0 pin 6)
│   ├── wifi-menu                 # Interaktywny skaner i kreator połączeń Wi-Fi (whiptail)
│   └── Makefile                  # Plik kompilacji narzędzi
│
├── backup_wm8650/                # Zrzuty diagnostyczne z oryginalnego systemu Android 2.2
│   ├── cmdline.txt               # Parametry startowe jądra Androida
│   ├── dmesg.txt                 # Pełny dmesg ze sterownikami wmt
│   ├── lsmod.txt                 # Lista oryginalnych modułów jądra
│   ├── mtd.txt                   # Układ partycji pamięci Flash SPI i NAND
│   └── uboot_env.txt             # Zmienne środowiskowe bootloadera U-Boot
│
└── legacy/                       # Skrypty archiwalne
    ├── build_debian_sdcard.sh    # Dawny instalator Debiana 7 Wheezy na starym jądrze 2.6.32
    └── fix_sdcard.sh             # Skrypt naprawy kolorów konsoli na starym jądrze
```

---

## 🛠️ Instrukcja instalacji krok po kroku

### Krok 1: Wymagania i formatowanie karty microSD

* **Wymagania dotyczące karty:**
  * **Minimalna pojemność:** **1 GB** (zainstalowany system bazowy z jądrem i modułami zajmuje łącznie ok. ~550 MB).
  * **Zalecana pojemność:** **2 GB – 4 GB lub większa** (zapewnia zapas na pamięć podręczną APT, instalowanie dodatkowych pakietów i logi systemowe).
  * **Obsługiwany standard:** SD / microSD / SDHC do **32 GB** (karty formatowane ze standardową tablicą partycji **MBR / DOS**).

Karta microSD powinna posiadać 2 partycje:
1. **Partycja 1:** ~64–128 MB, system plików **FAT32** (oznaczona jako bootowalna `WMTBOOT`).
2. **Partycja 2:** pozostała przestrzeń karty, system plików **ext4** (`debian_rootfs`).

### Krok 2: Skompilowanie jądra Linux 6.1 LTS
Na komputerze PC (Linux Mint / Ubuntu / Debian) z zainstalowanym kompilatorem ARM (`gcc-arm-linux-gnueabi`):
```bash
./kernel/build_kernel.sh
```
Skrypt automatycznie pobierze źródła jądra Linux 6.1 LTS, nałoży konfigurację `wm8650_defconfig` oraz DTS `wm8650-mid.dts`, skompiluje obraz `uImage` z dołączonym Device Tree i przygotuje moduły w katalogu `modules_wm8650/`.

### Krok 3: Instalacja Debiana 12 (Bookworm) na karcie SD
Włóż kartę microSD do czytnika w komputerze i uruchom instalator (zastąp `/dev/sdX` nazwą swojej karty, np. `/dev/sdb` lub `/dev/mmcblk0`):
```bash
sudo ./install_debian12_bookworm.sh /dev/sdX
```
Instalator:
* skopiuje `uImage` oraz `wmt_scriptcmd` na partycję FAT32,
* zainstaluje Debiana 12 armel metodą `debootstrap` + `qemu-arm-static`,
* przekonfiguruje system na lekki `sysvinit-core` (usuwając `systemd`),
* wgra moduły jądra 6.1, firmware `rt2870.bin` oraz pakiety sieciowe,
* skonfiguruje usługę ZRAM (80 MB LZ4) oraz narzędzia `wifi-power-on` i `wifi-menu`.

---

## 🖥️ Uruchomienie tabletu i obsługa

1. Włóż przygotowaną kartę microSD do slotu w tablecie i włącz zasilanie.
2. Na ekranie LCD pojawi się komunikat U-Boota, pingwin Tux i logi startowe jądra 6.1 LTS.
3. Po kilkunastu sekundach pojawi się prompt logowania konsoli:
   * **Użytkownik:** `user` (hasło: `user`, pełne uprawnienia `sudo`)
   * **Root:** `root` (hasło: `root`)

### Konfiguracja sieci Wi-Fi
Wystarczy wpisać polecenie:
```bash
wifi-menu
```
Pojawi się okienko tekstowe z wykrytymi sieciami w zasięgu. Wybierz swoją sieć, wprowadź hasło i zatwierdź. Tablet połączy się z siecią, pobierze adres IP z DHCP i zapisze konfigurację na stałe.

### Dostęp przez SSH
Z komputera w tej samej sieci lokalnej:
```bash
ssh user@<ADRES_IP_TABLETU>
```

---

## 🔒 Bezpieczeństwo
Wszystkie operacje wykonywane są wyłącznie na karcie microSD. Pamięć SPI NOR Flash zawierająca bootloader U-Boot pozostaje nienaruszona, dzięki czemu tablet jest całkowicie zabezpieczony przed ucegleniem – wyjęcie karty SD przywraca natychmiast fabryczny rozruch.
