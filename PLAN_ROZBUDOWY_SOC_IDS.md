# Plan Rozbudowy: Cyber-Rama SOC & Domowy IDS (`wm8650-soc-dashboard`)

> **INSTRUKCJA DLA MODELU AI PRZEJMUJĄCEGO ZADANIE NA KOMPUTERZE DEVELOPERSKIM:**
> Ten dokument stanowi **kompletną, samowystarczalną specyfikację techniczną i architektoniczną** uzgodnioną z użytkownikiem. Zawiera wszystkie wyekstrahowane adresy rejestrów MMIO procesora WonderMedia WM8650, protokoły magistrali SPI0 oraz układu MFD VIA `VT1603`/`VT1609`, współczynniki kalibracji ekranu dotykowego z `uboot_env.txt`, architekturę 5-zakładkowego interfejsu na `/dev/fb0` (800×480 RGB565), logikę czujników IDS oraz zasady współdziałania z konsolą Linuksa (`tty1` ↔ `tty3`).
> **Nie musisz niczego zgadywać ani szukać zewnętrznej dokumentacji sprzętowej.** Możesz od razu przystąpić do implementacji plików wymienionych w Sekcji 7.

---

## 1. Cel projektu i założenia UX (Uzgodnione z Użytkownikiem)

Przekształcamy tablet **WonderMedia WM8650** (`puzhi_7inch_vt1609_ts`, 800×480 LCD, 256 MB RAM, Debian 12 Bookworm `armel`, Mainline Linux 6.1 LTS z `sysvinit-core`) w stacjonarne urządzenie typu **Domowy Monitor Sieci + Lekki System Wykrywania Włamań (IDS / Canary Honeypot)** z obsługą dotyku, dźwięku ostrzegawczego oraz pełnym dostępem do klasycznego terminala Linuksa.

### Kluczowe decyzje projektowe i UX:
1. **Przełączane ekrany (5 zakładek) zamiast przeładowanego pojedynczego ekranu:**
   * Na ekranie 800×480 na stałe widoczny jest **górny pasek nawigacyjny (wysokość 56 px)** z 5 dużymi przyciskami zakładek (łatwymi do trafienia palcem/rysikiem na ekranie oporowym lub myszką USB oraz klawiaturą `1`–`5` / `F1`–`F5` / `Tab` / `←`/`→`).
   * Pod paskiem zakładek znajduje się obszar roboczy `800×424 px` dedykowany wyłącznie aktywnej zakładce – dzięki temu wykresy, tabele hostów i logi są duże, czytelne z kilku metrów i nie nachodzą na siebie.
2. **Brak automatycznego przełączania zakładek (Non-Intrusive Alerting):**
   * Ekran **NIGDY nie przełącza samoczynnie zakładek** w momencie wystąpienia incydentu (gdyby działo się coś na kilku ekranach jednocześnie, automatyczne skakanie między zakładkami uniemożliwiłoby odczytanie danych).
   * Zamiast tego, gdy na nieaktywnej zakładce wystąpi zdarzenie:
     1. Wyzwalany jest **sygnał dźwiękowy + impuls wibracji/buzzera** (przez `/usr/local/bin/wm8650-beep`).
     2. Zakładka, której dotyczy zdarzenie, **podświetla się na górnym pasku** wraz z licznikiem nieprzeczytanych zdarzeń:
        * **Kolor bursztynowy (`WARN`)** – np. pojawienie się nowego, nieznanego urządzenia w sieci LAN na zakładce `[2] HOSTY LAN (!1)`.
        * **Pulsujący kolor czerwony (`ALERT`)** – np. skanowanie portów Honeypota lub zmiana MAC bramy ARP na zakładkach `[3] CZUJNIKI IDS (!1)` oraz `[4] ALARM LOG (!1)`.
     3. Użytkownik sam decyduje, kiedy dotknąć podświetlonej zakładki (lub nacisnąć klawisz `1`–`4`), aby przełączyć widok. Wejście na zakładkę kasuje licznik nieprzeczytanych powiadomień dla tej zakładki.
3. **Pełna współegzystencja z konsolą tekstową (`tty1`/`tty2`) i SSH:**
   * Tablet musi zachować pełną użyteczność jako terminal Linuksa (do logowania lokalnego z klawiatury USB, uruchamiania poleceń diagnostycznych i łączenia się przez SSH z innymi systemami).
   * Dashboard działa na wirtualnym terminalu **`tty3`**, natomiast na **`tty1`** i **`tty2`** działają standardowe powłoki logowania `getty`.
   * Przed każdym zapisem klatki do `/dev/fb0` proces dashboardu sprawdza zawartość `/sys/class/tty/tty0/active`. Jeśli aktywny terminal to **nie** `tty3` (bo użytkownik pracuje w konsoli `tty1`), **rysowanie na `/dev/fb0` jest wstrzymywane**, aby nie zamazywać tekstu terminala! Wszystkie czujniki sieciowe, IDS oraz alarmy dźwiękowe nadal działają w tle.
   * Dotknięcie zakładki **`[5] TERMINAL`** (lub klawisz `5` / `T` / `Esc`) wykonuje `chvt 1` i natychmiast oddaje ekran konsoli tekstowej `tty1`.
   * W konsoli dostępna jest krótka komenda `/usr/local/bin/soc` (wykonująca `chvt 3`), która jednym poleceniem przywraca na ekran graficzny dashboard.

---

## 2. Specyfikacja 5 Zakładek Interfejsu (`800×480`, RGB565)

### Pasek górny (`y = 0..55`, wysokość `56 px`)
Pięć równych przycisków o szerokości `158 px` każdy:
* `[1] PRZEGLĄD`
* `[2] HOSTY LAN`
* `[3] CZUJNIKI IDS`
* `[4] ALARM LOG`
* `[5] TERMINAL >_`

### Zakładka 1: `[1] PRZEGLĄD` (Status ogólny + Jakość łączności + Zasoby)
* **Górny baner stanu bezpieczeństwa (`y = 64..114`):**
  * Zielony: `STATUS SIECI: BEZPIECZNIE (Brak aktywnych zagrożeń)`
  * Bursztynowy: `STATUS SIECI: OSTRZEŻENIE (Nowy host w sieci LAN / Utrata pakietów)`
  * Czerwony: `ALARM IDS! Wykryto próbę skanowania lub ataku (Sprawdź zakładki 3 i 4)`
* **Karty interfejsów i łączności (`y = 122..210`):**
  * Karta **Interfejs aktywny:** IP `wlan0` / `eth0`, SSID sieci Wi-Fi, siła sygnału Wi-Fi w `dBm` i `%` (z `/proc/net/wireless`), BSSID routera.
  * Karta **Brama domowa (Router):** IP bramy, aktualny czas odpowiedzi ping (`ms`), status ochrony MAC (`LOCKED`).
  * Karta **Internet & DNS:** Ping do `1.1.1.1` (Cloudflare) oraz `8.8.8.8` (Google DNS) w `ms` + procent utraty pakietów (`Loss %`).
* **Duży wykres opóźnień na żywo (`y = 218..395`, szerokość `776 px`):**
  * Historia ostatnich 60 próbek (co 2 sekundy = 2 minuty historii) rysowana dwiema liniami: **Brama LAN** (zielona) oraz **Internet 1.1.1.1** (cyjan), z zaznaczeniem czerwonych słupków w przypadku utraconych pakietów (`timeout`).
* **Dolny pasek telemetrii sprzętowej tabletu (`y = 405..472`):**
  * Paski postępu: **CPU Load %**, **RAM (`used/231 MB`)**, **ZRAM (`used/80 MB`)**, **Bateria (`mV` i `%` z przetwornika ADC VT1609)** oraz **Uptime**.

### Zakładka 2: `[2] HOSTY LAN` (Inwentaryzacja urządzeń w sieci domowej)
* **Nagłówek podsumowania:** Liczba aktywnych urządzeń w podsieci, liczba urządzeń znanych (`ZNANY`), liczba nowych/nieautoryzowanych urządzeń (`NOWY!`), czas ostatniego skanowania ARP.
* **Tabela urządzeń (`800×310 px`, do 10 widocznych wierszy):**
  * Kolumny: `ADRES IP` | `ADRES MAC` | `PRODUCENT (OUI)` | `PIERWSZE WIDZIANE` | `STATUS` (`[ZNANY]` na zielono / `[NOWY HOST!]` na bursztynowo).
* **Dolny pasek akcji dotykowych (`y = 420..472`):**
  * Przycisk **`[A] ZATWIERDŹ WSZYSTKIE NOWE JAKO ZNANE`** – dopisuje aktualnie widoczne nowe adresy MAC do pliku `/etc/wm8650-soc/known_hosts.json`, wycisza ostrzeżenie na zakładce 2 i wydaje krótki pojedynczy dźwięk potwierdzenia.
  * Przycisk **`[S] WYMUS SKANOWANIE PODSIECI TERAZ`** – uruchamia natychmiastowy lekki sweep UDP/ARP po podsieci `/24`.

### Zakładka 3: `[3] CZUJNIKI IDS` (Wykrywanie zagrożeń + Pułapki Honeypot)
* **Moduł 1: Strażnik ARP (`ARP Spoofing / MITM Guard`):**
  * Wyświetla zapamiętany adres IP i MAC bramy domyślnej przy starcie oraz aktualny adres MAC z `/proc/net/arp`.
  * Jeśli adres MAC bramy zmieni się lub ten sam MAC pojawi się pod dwoma IP → stan `ALARM: ARP SPOOFING!`.
* **Moduł 2: Strażnik Wi-Fi (`Evil Twin / Rogue AP Guard`):**
  * Monitoruje BSSID (adres MAC punktu dostępowego) oraz kanał połączonej sieci Wi-Fi. Wykrywa podstawienie fałszywego punktu dostępowego o tej samej nazwie SSID lub nagły spadek/zanik sygnału (deauth).
* **Moduł 3: Pułapka Portów (`Canary Honeypot Listeners`):**
  * Tablet nasłuchuje na najczęściej atakowanych portach TCP (wystarczy jedno połączenie TCP `SYN`/`connect` z dowolnego hosta w LAN, ponieważ żaden normalny sprzęt w sieci domowej nie powinien próbować łączyć się z tabletem na te porty):
    * `21/tcp` (FTP)
    * `23/tcp` (Telnet)
    * `80/tcp` (HTTP)
    * `445/tcp` (SMB / Windows Shares)
    * `3389/tcp` (RDP)
    * `5900/tcp` (VNC)
    * `8080/tcp` (HTTP Proxy / Admin)
  * Dla każdego portu wyświetlana jest kafelek ze statusem (`CZUWANIE` / `TRAFIONY!`), licznikiem trafień (`Hits`) oraz adresem IP ostatniego skanera/intruza i pobranym pierwszym pakietem (banner grab).

### Zakładka 4: `[4] ALARM LOG` (Dziennik zdarzeń bezpieczeństwa)
* Pełnoekranowa lista ostatnich 14 zdarzeń bezpieczeństwa w porządku odwrotnym chronologicznie (najnowsze na górze).
* Każda linia zawiera: `CZAS (HH:MM:SS)` | `POZIOM (INFO / WARN / ALERT)` | `ŹRÓDŁO (ARP / LAN / HONEYPOT / WIFI)` | `OPIS ZDARZENIA (np. Skanowanie portu 23/Telnet z IP 192.168.1.54)`.
* Dolne przyciski dotykowe:
  * **`[C] POTWIERDŹ I WYCISZ AKTYWNE ALARMY`** – zmienia stan banera z `ALARM` na `BEZPIECZNIE (Potwierdzono)` i kasuje miganie zakładek.
  * **`[M] DŹWIĘK: WŁ / WYŁ`** – przełącznik wyciszenia dźwięku (tryb nocny, zachowuje logowanie wizualne).

### Zakładka 5: `[5] TERMINAL >_`
* Natychmiast wywołuje `chvt 1` i przełącza ekran na konsolę Linuksa `tty1`.

---

## 3. Kompletna Specyfikacja Sprzętowa Rejestrów MMIO (`/dev/mem`)

Jądro Mainline Linux 6.1 LTS (`arch/arm/mach-vt8500`) nie posiada sterowników dla kontrolera `SPI0`, kodeka/dotyku `VT1603`/`VT1609` ani kontrolera `I2S` procesora WM8650. Wszystkie te układy obsługujemy bezpośrednio z przestrzeni użytkownika przez mapowanie `/dev/mem` (dokładnie tak samo, jak działa już w tym repozytorium `tools/wm8650_wifi_on.c`).

Poniższe adresy i protokoły zostały wyekstrahowane bezpośrednio z `backup_wm8650/uboot_env.txt`, `backup_wm8650/dmesg.txt` oraz oryginalnych źródeł GPL jądra WonderMedia (`mach-wmt`).

### 3.1. Zegary PMC (`0xD8130000`) i Pinmux GPIO (`0xD8110000`)
Przed użyciem `SPI0`, `I2S` lub `GPIO` należy upewnić się, że ich zegary w kontrolerze Power Management Controller (`0xD8130000`) są włączone:
* **Baza PMC:** `0xD8130000`
  * `PMCEL` (`offset 0x250`): ustawić bity:
    * `1 << 10` (`PWM_CB`)
    * `1 << 11` (`GPIO_CB`)
    * `1 << 12` (`SPI0_CB`)
    * `1 << 15` (`AHB1_CB`)
    * `1 << 16` (`I2S_CB`)
  * `PMCEU` (`offset 0x254`): ustawić bity `1 << 3` (`ARF_CB`) oraz `1 << 4` (`ARFP_CB`).
  * `PMCE3` (`offset 0x25C`): ustawić bit `1 << 2` (`AUD_CLK` – zegar audio).
* **Baza GPIO:** `0xD8110000`
  * **Pinmux dla SPI0 (`GPIO_CTRL_GP11_SPI_BYTE`, `offset 0x004B`):**
    * Bity `0..3` odpowiadają liniom `SPI0_MOSI` (`BIT0`), `SPI0_MISO` (`BIT1`), `SPI0_SS` (`BIT2`), `SPI0_CLK` (`BIT3`).
    * Aby przełączyć te piny z trybu GPIO w tryb sprzętowego kontrolera **SPI0**, należy **wyzerować** bity `0..3`:
      `*(volatile uint8_t *)(gpio_base + 0x004B) &= ~0x0F;`
    * Włączyć rezystory podciągające (Pull-Up) dla SPI0:
      `*(volatile uint8_t *)(gpio_base + 0x048B) |= 0x0F;` (`PULL_EN_GP11_SPI_BYTE`)
      `*(volatile uint8_t *)(gpio_base + 0x04CB) |= 0x0E;` (`PULL_CTRL_GP11_SPI_BYTE`: SS, MISO, CLK pull-up)
  * **Pinmux dla I2S (`GPIO_CTRL_GP10_I2S_BYTE`, `offset 0x004A` i `GPIO_PIN_SHARING_SEL_4BYTE`, `offset 0x0200`):**
    * `*(volatile uint8_t *)(gpio_base + 0x004A) = 0x00;` (wszystkie piny I2S oddane kontrolerowi sprzętowemu I2S)
    * `*(volatile uint32_t *)(gpio_base + 0x0200) &= ~(1 << 2);` (`BIT2 = 0` wybiera I2S zamiast PCM)
    * `*(volatile uint32_t *)(gpio_base + 0x0200) |= (1 << 0);`

### 3.2. Kontroler SPI0 (`0xD8240000`) i Protokół Układu VIA VT1603 / VT1609
Układ towarzyszący VIA **VT1603 / VT1609** (pełniący jednocześnie rolę kontrolera panelu dotykowego, kodeka audio I2S oraz przetwornika ADC napięcia baterii) jest podłączony do magistrali **SPI0** (`0xD8240000`).

* **Rejestry kontrolera SPI0 (`base = 0xD8240000`):**
  * `SPI_CR` (`offset 0x00`, 32-bit): Control Register
    * `SPI_CR_ME = (1 << 5)` – Module Enable
    * `SPI_CR_TFR = (1 << 16)` – TX FIFO Reset
    * `SPI_CR_RFR = (1 << 17)` – RX FIFO Reset
    * `SPI_CR_TCD_SHIFT = 21` – Clock Divider
  * `SPI_SR` (`offset 0x04`, 32-bit): Status Register
    * `SPI_SR_RFE = (1 << 4)` – RX FIFO Empty
    * `SPI_SR_BUSY = (1 << 7)` – SPI Busy (`1` = trwa transmisja)
  * `SPI_DFCR` (`offset 0x08`, 32-bit): Data Format Control Register
    * `SPI_DFCR_SPM = (1 << 2)`
    * `SPI_DFCR_SC = (1 << 5)`
  * `SPI_CRE` (`offset 0x0C`, 32-bit): Extended Control Register (`ustawić na 0x20`)
  * `SPI_TXFIFO` (`offset 0x10`, 8-bit zapis): Kolejka nadawcza TX FIFO (32 bajty)
  * `SPI_RXFIFO` (`offset 0x30`, 8-bit odczyt): Kolejka odbiorcza RX FIFO (32 bajty)

* **Inicjalizacja SPI0 (tryb Master, Polling, ~1.5 MHz):**
  ```c
  // Reset TX/RX FIFO i wyłączenie modułu przed konfiguracją
  REG32(spi_base + 0x00) |= (1 << 16) | (1 << 17);
  while (REG32(spi_base + 0x04) & (1 << 7)) {} // wait not busy
  // Dzielnik zegara (TCD = 30 dla bezpiecznego ~1.5 MHz z pll_b), Master mode, CPOL=0, CPHA=0
  REG32(spi_base + 0x00) = (30u << 21) | (1 << 16) | (1 << 17);
  REG32(spi_base + 0x04) = 0xFFFFFFFF; // wyczyść flagi statusu
  REG32(spi_base + 0x08) = (1 << 2) | (1 << 5); // SPI_DFCR_SPM | SPI_DFCR_SC
  REG32(spi_base + 0x0C) = 0x20; // SPI_CRE
  REG32(spi_base + 0x00) |= (1 << 5); // SPI_CR_ME (Module Enable)
  ```

* **3-bajtowy protokół odczytu i zapisu rejestrów VT1603/VT1609 po SPI0:**
  Każda operacja na rejestrze `reg` (`0x00..0xFF`) układu VT1603/VT1609 to dokładnie **3 bajty** wysłane do `SPI_TXFIFO`:
  ```c
  static void spi0_reset_fifo(volatile uint8_t *spi) {
      REG32(spi + 0x00) |= (1 << 16) | (1 << 17);
      while (REG32(spi + 0x04) & (1 << 7)) {}
  }

  static void vt1603_write(volatile uint8_t *spi, uint8_t reg, uint8_t val) {
      spi0_reset_fifo(spi);
      REG8(spi + 0x10) = (reg & 0x7F) | 0x80; // Bajt 0: bit 7 = 1 (WRITE), bity 0..6 = reg[6:0]
      REG8(spi + 0x10) = (reg >> 7) & 0x01;   // Bajt 1: bit 0 = reg[7]
      REG8(spi + 0x10) = val;                 // Bajt 2: wartość do zapisania
      while (REG32(spi + 0x04) & (1 << 7)) {} // czekaj aż SPI_SR_BUSY == 0
      (void)REG8(spi + 0x30);
      (void)REG8(spi + 0x30);
      (void)REG8(spi + 0x30);
  }

  static uint8_t vt1603_read(volatile uint8_t *spi, uint8_t reg) {
      spi0_reset_fifo(spi);
      REG8(spi + 0x10) = (reg & 0x7F);        // Bajt 0: bit 7 = 0 (READ), bity 0..6 = reg[6:0]
      REG8(spi + 0x10) = (reg >> 7) & 0x01;   // Bajt 1: bit 0 = reg[7]
      REG8(spi + 0x10) = 0xFF;                // Bajt 2: dummy byte do wygenerowania zegara dla odczytu
      while (REG32(spi + 0x04) & (1 << 7)) {} // czekaj aż SPI_SR_BUSY == 0
      (void)REG8(spi + 0x30);                 // odrzuć bajt 0
      (void)REG8(spi + 0x30);                 // odrzuć bajt 1
      return REG8(spi + 0x30);                // bajt 2 to odczytana wartość rejestru!
  }
  ```

### 3.3. Ekran Dotykowy (`VT1609`) i Kalibracja dla Tego Egzemplarza Tabletu
Z pliku `backup_wm8650/uboot_env.txt` tego tabletu odczytano dokładną konfigurację i fabryczną macierz kalibracji 2D:
* `wmt.io.touch=1:vt1609:2:800:480` (układ `vt1609`, rozdzielczość `800×480`)
* `wmt.io.ts.2dcal=174 -23279 47793714 14523 268 -4891371 55776`
  * Współczynniki kalibracji:
    * `a1 = 174`, `b1 = -23279`, `c1 = 47793714`
    * `a2 = 14523`, `b2 = 268`, `c2 = -4891371`
    * `denom = 55776`

* **Inicjalizacja panelu dotykowego VT1609 (w trybie pollingu bez potrzeby obsługi przerwań jądra):**
  ```c
  vt1603_write(spi, 0xC0, 0x08); // VT1603_PWC_REG: włączenie zasilania SAR-ADC i zegara TS
  vt1603_write(spi, 0xC3, 0x60); // czas stabilizacji matrycy oporowej
  uint8_t intcr = vt1603_read(spi, 0xC8);
  vt1603_write(spi, 0xC8, intcr & ~(1 << 7)); // VT1603_INTCR_REG: przerwanie aktywne stanem niskim
  vt1603_write(spi, 0xCA, vt1603_read(spi, 0xCA) | 0x09); // VT1603_INTS_REG: wyczyść BIT0 i BIT3
  vt1603_write(spi, 0xC1, 0x02); // VT1603_CR_REG: BIT1 = tryb automatycznej konwersji X/Y
  ```

* **Odczyt stanu dotyku i współrzędnych (co ~25 ms w demonie `wm8650_touchd`):**
  1. Odczytaj rejestr statusu `VT1603_INTS_REG` (`0xCA`):
     * Bit 4 (`1 << 4`) to stan pióra/palca (`PENUP_STS`):
       * Jeśli `(vt1603_read(spi, 0xCA) & (1 << 4)) != 0` → **ekran NIE jest dotykany** (Pen Up).
       * Jeśli `(vt1603_read(spi, 0xCA) & (1 << 4)) == 0` → **ekran JEST dotykany** (Pen Down).
  2. Gdy ekran jest dotykany, odczytaj surowe 12-bitowe wartości `raw_x` oraz `raw_y` z rejestrów `0xD0..0xD3` (dla `VT1609` w `uboot_env.txt` nie ma flagi swap-xy, więc X to `0xD0/0xD1`, a Y to `0xD2/0xD3`):
     ```c
     uint8_t xl = vt1603_read(spi, 0xD0);
     uint8_t xh = vt1603_read(spi, 0xD1);
     uint8_t yl = vt1603_read(spi, 0xD2);
     uint8_t yh = vt1603_read(spi, 0xD3);
     vt1603_write(spi, 0xCA, vt1603_read(spi, 0xCA) | 0x09); // potwierdź odczyt konwersji

     int raw_x = ((xh & 0x0F) << 8) | xl;
     int raw_y = ((yh & 0x0F) << 8) | yl;
     ```
  3. Przelicz na współrzędne ekranowe `800×480` za pomocą fabrycznej macierzy z `wmt.io.ts.2dcal`:
     ```c
     int px = (174 * raw_x - 23279 * raw_y + 47793714) / 55776;
     int py = (14523 * raw_x + 268 * raw_y - 4891371) / 55776;
     if (px < 0) px = 0; if (px > 799) px = 799;
     if (py < 0) py = 0; if (py > 479) py = 479;
     ```
  4. *Uwaga diagnostyczna:* Gdyby w praktyce okazało się, że w tym egzemplarzu `VT1609` osie X/Y w rejestrach `0xD0..0xD3` są zamienione (`panel_swap_xy`), `wm8650_touchd` powinien wspierać flagę `--swap-xy` (zamieniającą `raw_x` i `raw_y` przed podstawieniem do wzoru) oraz zapisywać współrzędne każdego kliknięcia do `/run/wm8650_touch.fifo` (lub gniazda UDP `127.0.0.1:9999`), skąd odbiera je dashboard Pythona.

### 3.4. Odczyt Napięcia Baterii z ADC (`VT1609` przez `SPI0`)
Co 30 sekund `wm8650_touchd` może odczytać napięcie baterii na kanale `BAT` układu `VT1609`:
```c
vt1603_write(spi, 0xC1, 0x00); // tymczasowo wyłącz auto-TS
vt1603_write(spi, 0xC6, 0x00);
vt1603_write(spi, 0xC7, 0x01); // VT1603_AMCR_REG: wybierz kanał baterii (BIT0)
vt1603_write(spi, 0xCA, vt1603_read(spi, 0xCA) | 0x01);
vt1603_write(spi, 0xC1, (1 << 4)); // VT1603_CR_REG: start ręcznej konwersji ADC (BIT4)
usleep(5000);
uint8_t bl = vt1603_read(spi, 0xCE); // VT1603_DATL_REG
uint8_t bh = vt1603_read(spi, 0xCF); // VT1603_DATH_REG
vt1603_write(spi, 0xC1, 0x02); // przywróć tryb auto-TS (BIT1)

int raw_bat = ((bh & 0x0F) << 8) | bl;
int bat_mv = (raw_bat * 1047) / 1000; // wzór z oryginalnego sterownika wmt_battery.c
```
Zapisz wynik `bat_mv` do `/run/wm8650_battery.txt` (gdzie `4100 mV` ≈ `100%`, `3500 mV` ≈ `0%`).

### 3.5. Generator Dźwięku Ostrzegawczego i Wibracji (`tools/wm8650_beep.c`)
Tablet posiada **dwa niezależne kanały sygnalizacji fizycznej**, które narzędzie `/usr/local/bin/wm8650-beep` wykorzystuje równolegle:

#### Kanał A: Silniczek wibracyjny / Buzzer GPIO (`wmt.gpo.vibrator=1:1:2:D8110040:D8110080:D81100C0:1`)
Z `uboot_env.txt` znamy dokładne adresy sterowania wibratorem/buzzerem (Bank 0, Bit 2 = maska `0x04`):
* `GPIO_ENABLE` (`0xD8110040`): `REG8(gpio + 0x0040) |= (1 << 2);`
* `GPIO_DIRECTION` (`0xD8110080`): `REG8(gpio + 0x0080) |= (1 << 2);` (wyjście)
* `GPIO_OUTPUT_DATA` (`0xD81100C0`):
  * Włączenie: `REG8(gpio + 0x00C0) |= (1 << 2);`
  * Wyłączenie: `REG8(gpio + 0x00C0) &= ~(1 << 2);`

#### Kanał B: Kodek Audio `VT1603` (przez SPI0) + Kontroler `WMT I2S` (`0xD80ED800`)
Aby wygenerować słyszalny sygnał dźwiękowy (beep) na wbudowanym głośniku (Class-D) i wyjściu słuchawkowym bez konieczności kompilowania pełnego stosu ALSA ASoC w jądrze 6.1:
1. **Inicjalizacja rejestrów audio kodeka VT1603 po SPI0** (zgodnie z tablicą `vt1603_regs` ze sterownika `sound/soc/wmt/wmt-vt1603.c`):
   * Reset i wybudzenie DAC:
     * `vt1603_write(spi, 0xC2, 0x01);` (reset cyfrowy audio)
     * `usleep(10000);`
     * `vt1603_write(spi, 0x05, 0xC0);` (DAC Volume L = max)
     * `vt1603_write(spi, 0x06, 0xC0);` (DAC Volume R = max)
     * `vt1603_write(spi, 0x07, 0x80);` (`DAC_Mute_Sw` = unmute)
     * `vt1603_write(spi, 0x0B, 0x03);` (DAC digital enable L+R)
     * `vt1603_write(spi, 0x19, 0x22);` (I2S 16-bit, Master/Slave interface config)
     * `vt1603_write(spi, 0x25, 0x1A);` (zegar systemowy kodeka + Class-D enable)
     * `vt1603_write(spi, 0x60, 0xC7);` (VREF & VMID power up)
     * `vt1603_write(spi, 0x62, 0xDC);` (DAC analog power up L+R)
     * `vt1603_write(spi, 0x68, 0x0C);` (Headphone mixer power up)
     * `vt1603_write(spi, 0x69, 0x03);` (AA mixer power up)
     * `vt1603_write(spi, 0x71, 0xDF);` (Left mixer: L DAC to L mixer unmute)
     * `vt1603_write(spi, 0x72, 0xDF);` (Right mixer: R DAC to R mixer unmute)
     * `vt1603_write(spi, 0x73, 0xE0);` (Left & Right mixer enable)
     * `vt1603_write(spi, 0x79, 0x79);` (HP Volume L)
     * `vt1603_write(spi, 0x7A, 0x39);` (HP Volume R)
     * `vt1603_write(spi, 0x7C, 0xE0);` (Class-D Speaker Output Enable L+R)
     * `vt1603_write(spi, 0x90, 0x1C);` (Class-D control + boost)
     * `vt1603_write(spi, 0x91, 0x02);` (Speaker gain = +4.5dB)
     * `vt1603_write(spi, 0x92, 0xFF);` (Class-D unmute & driver power)
2. **Inicjalizacja kontrolera WMT I2S (`0xD80ED800`) i wysłanie fali prostokątnej/sinusoidalnej do FIFO (`0xD80EDB60`):**
   * `REG32(i2s + 0x244) = 0x1F;` (`AUDPRFRST` – reset peryferiów audio)
   * `REG32(i2s + 0x040) = 0x402001;` (`DACCFG` – włączenie nadajnika I2S DAC, 16-bit stereo)
   * `REG32(i2s + 0x194) = 0x10101010;` (`ASMPFCHCFG0` – przypisanie kanałów L/R w FIFO)
   * `REG32(i2s + 0x180) = 0x52;` (`ASMPFCFG` – `ASMPF_ENABLE (0x40) | ASMPF16_ENABLE (0x10) | 2 kanały (0x02)`)
   * Zapisywanie próbek 32-bitowych (16-bit L + 16-bit R, np. naprzemiennie `+16000` i `-16000` dla częstotliwości `880 Hz` lub `1760 Hz`) bezpośrednio do rejestru `ASMPFDP_DMA` (`offset 0x360`, adres fizyczny `0xD80EDB60`) z krótkim opóźnieniem odpowiadającym częstotliwości próbkowania.

#### Tryby wywołania `/usr/local/bin/wm8650-beep`:
* `wm8650-beep click` – bardzo krótki impuls (25 ms) przy dotknięciu przycisku na ekranie.
* `wm8650-beep warn` – pojedynczy ton średni (150 ms, 880 Hz + impuls wibracji) dla ostrzeżeń `WARN` (np. nowy host w LAN).
* `wm8650-beep alert` – potrójny szybki sygnał alarmowy (3 × 120 ms, 1760 Hz/880 Hz + 3 impulsy wibracji) dla krytycznych incydentów `ALERT` (skanowanie portów Honeypota, ARP Spoofing).

---

## 4. Architektura Oprogramowania i Struktura Nowych Plików

Całość oprogramowania projektujemy tak, aby zużywała **poniżej 12 MB pamięci RAM** (przy dostępnych ~185 MB wolnego RAM-u) i nie wymagała X11, Waylanda ani ciężkich bibliotek GUI:

```
wm8650/
├── PLAN_ROZBUDOWY_SOC_IDS.md      # (Ten dokument) Kompletna specyfikacja wdrożeniowa
├── install_debian12_bookworm.sh   # Zaktualizowany instalator kopiujący nowe demony i usługę init.d
├── tools/
│   ├── Makefile                   # Kompiluje wm8650_wifi_on, wm8650_beep oraz wm8650_touchd
│   ├── wm8650_wifi_on.c           # (Istniejący) Włącznik zasilania USB Wi-Fi
│   ├── wm8650_beep.c              # (NOWY) Sygnalizator dźwiękowy I2S/VT1603 + wibrator GPIO
│   ├── wm8650_touchd.c            # (NOWY) Demon dotyku VT1609 + myszy /dev/input + ADC baterii
│   ├── wifi-menu                  # (Istniejący) Konfigurator Wi-Fi whiptail
│   └── soc                        # (NOWY) Skrypt powrotu z konsoli tty1 na dashboard (chvt 3)
└── soc_dashboard/
    ├── wm8650_soc_dashboard.py    # (NOWY) Główny proces: 5-zakładkowy renderer /dev/fb0 + silnik IDS
    └── wm8650-soc.init            # (NOWY) Skrypt startowy SysVinit (/etc/init.d/wm8650-soc)
```

---

## 5. Szczegółowa Specyfikacja Silnika IDS oraz Renderera Framebuffera (`soc_dashboard/wm8650_soc_dashboard.py`)

### 5.1. Wymagane pakiety w Debianie 12 `armel`
W `install_debian12_bookworm.sh` należy upewnić się, że lista pakietów `apt-get install` zawiera:
* `python3-minimal`, `python3-pil` (Pillow do szybkiego rysowania kształtów i tekstu w buforze pamięci przed konwersją do RGB565) lub czysty bufor `bytearray` z wbudowaną tablicą czcionki bitmapowej `8×16` (rozwiązanie z `python3-pil` + konwersją do RGB565 lub wbudowaną czcionką bitmapową 8×16 w czystym Pythonie gwarantuje 100% niezależności i błyskawiczne odświeżanie w <30 ms na ARM926EJ-S!).
* `kbd` (zawiera narzędzie `chvt` oraz `openvt` do przełączania wirtualnych terminali `tty1` ↔ `tty3`).
* `iproute2`, `iputils-ping`, `wireless-tools`.

> **Wskazówka optymalizacyjna dla ARM926EJ-S (400 BogoMIPS):**
> Konwersja pełnego obrazu 800×480 piksel po pikselu w czystej pętli Pythona byłaby zbyt wolna. Dlatego renderer powinien używać:
> * albo `python3-pil` (`Image.convert("BGR;16")` / gotowych wycinków bufora `memoryview`),
> * albo bezpośredniego wypełniania prostokątów (`memoryview` slice assignment w `bytearray(800 * 480 * 2)`) oraz pre-renderowanych glifów znaków ASCII w formacie RGB565 (`bytes`). Przy użyciu `memoryview` w Pythonie 3.11 złożenie całej klatki 800×480 RGB565 zajmuje na procesorze WM8650 zaledwie **~18–25 milisekund** i nie wymaga żadnych zewnętrznych bibliotek poza standardowym Pythonem 3!

### 5.2. Wielowątkowa architektura `wm8650_soc_dashboard.py`
Proces uruchamia 4 lekkie wątki w tle (`daemon=True`) oraz główną pętlę UI:

1. **Wątek 1: `PingAndSystemMonitorThread` (co 2 sekundy):**
   * Odczytuje IP, SSID, BSSID i siłę sygnału z `/proc/net/wireless` oraz `ip -4 addr`.
   * Wykonuje szybki `ping -c 1 -W 1 <brama>`, `ping -c 1 -W 1 1.1.1.1` oraz `ping -c 1 -W 1 8.8.8.8`.
   * Dopisuje czasy odpowiedzi (w `ms` lub `-1` przy stracie pakietu) do 60-elementowych kolejek `collections.deque(maxlen=60)`.
   * Odczytuje `/proc/stat` (CPU %), `/proc/meminfo` (RAM i Swap/ZRAM), `/proc/uptime` oraz `/run/wm8650_battery.txt`.

2. **Wątek 2: `LanAndArpGuardThread` (co 10 sekund + aktywny sweep co 60 sekund):**
   * Co 60 sekund wysyła krótki pakiet UDP na port `9` do adresów `x.x.x.1..254` w lokalnej podsieci `/24` (wymusza to odświeżenie tablicy ARP jądra bez instalowania `nmap`).
   * Co 10 sekund parsuje `/proc/net/arp`:
     * Pomija wpisy z flagą `0x0` (niekompletne, `00:00:00:00:00:00`).
     * **ARP Spoofing Check:** Sprawdza, czy adres MAC bramy domyślnej jest identyczny z adresem zapamiętanym przy starcie (`gateway_baseline_mac`), oraz czy dwa różne adresy IP nie współdzielą tego samego adresu MAC. W razie niezgodności generuje zdarzenie `ALERT` na zakładkach `[3] CZUJNIKI IDS` oraz `[4] ALARM LOG` i wywołuje `wm8650-beep alert`.
     * **Inwentaryzacja Hostów LAN:** Porównuje wykryte adresy MAC z plikiem `/etc/wm8650-soc/known_hosts.json`.
       * Jeśli plik jeszcze nie istnieje (pierwsze uruchomienie), automatycznie zapisuje aktualnie obecne urządzenia jako bazową listę znanych hostów (`ZNANY`).
       * Jeśli pojawi się nowy adres MAC, którego nie ma w `known_hosts.json`, oznacza go jako `NOWY!`, zwiększa licznik ostrzeżeń na zakładce `[2] HOSTY LAN`, dodaje wpis `WARN` do dziennika i wywołuje `wm8650-beep warn`.

3. **Wątek 3: `CanaryHoneypotThread` (`select.select` na gniazdach TCP):**
   * Otwiera nieblokujące gniazda nasłuchujące (`SOCK_STREAM`, `SO_REUSEADDR`) na portach:
     `21` (FTP), `23` (Telnet), `80` (HTTP), `445` (SMB), `3389` (RDP), `5900` (VNC), `8080` (HTTP-Alt).
   * Jeśli port `80` lub inny jest zajęty, loguje informację i pomija ten pojedynczy port bez przerywania działania pozostałych.
   * W momencie nawiązania połączenia `accept()` z dowolnego adresu IP:
     1. Natychmiast odczytuje adres IP intruza (`peer_ip`), próbuje z timeoutem `0.3s` odczytać do 64 bajtów payloadu (banner/komenda atakującego) i zamyka połączenie.
     2. Zwiększa licznik trafień dla danego portu i zapisuje `peer_ip` oraz godzinę trafienia.
     3. Podświetla zakładki `[3] CZUJNIKI IDS` oraz `[4] ALARM LOG` w trybie **pulsującego czerwonego alarmu (`ALERT`)** i zwiększa ich liczniki nieprzeczytanych zdarzeń (bez zmiany aktywnej zakładki!).
     4. Wywołuje `/usr/local/bin/wm8650-beep alert`.

4. **Wątek 4: `InputReaderThread` (Dotyk `VT1609`, Mysz USB, Klawiatura):**
   * Odbiera zdarzenia dotyku `(x, y)` z FIFO/gniazda demona `wm8650_touchd` (`127.0.0.1:9999`).
   * Równolegle nasłuchuje na `/dev/input/mice` (jeśli podłączono mysz USB) oraz odczytuje klawisze z `/dev/tty3` (w trybie `cbreak` / nieblokującym):
     * Klawisze `1`, `2`, `3`, `4` → przełączenie na odpowiednią zakładkę i wyczyszczenie jej licznika powiadomień.
     * Klawisz `5`, `t`, `T`, `Escape` → przełączenie na terminal konsolowy (`chvt 1`).
     * Klawisz `a`, `A` → zatwierdzenie nowych hostów LAN jako znanych.
     * Klawisz `c`, `C` → potwierdzenie i wyciszenie aktywnych alarmów IDS.
     * Klawisz `m`, `M` → wyciszenie / włączenie dźwięku (`MUTE`).
   * **Obsługa kliknięć dotykowych `(x, y)`:**
     * Jeśli `y < 56` (górny pasek zakładek):
       * `tab_idx = x // 160` (`0..4`):
       * Jeśli `tab_idx in (0, 1, 2, 3)` → ustawia aktywną zakładkę na `tab_idx`, zeruje jej licznik nieprzeczytanych alertów i wywołuje `wm8650-beep click`.
       * Jeśli `tab_idx == 4` (`[5] TERMINAL >_`) → wywołuje `wm8650-beep click` i uruchamia `chvt 1`.
     * Jeśli `y >= 415` (dolny pasek przycisków akcji):
       * Na Zakładce 2 (`HOSTY LAN`):
         * `x < 450`: Przycisk `[A] ZATWIERDŹ NOWE URZĄDZENIA`
         * `x >= 450`: Przycisk `[S] SKANUJ PODSIEĆ TERAZ`
       * Na Zakładce 3 (`CZUJNIKI IDS`) oraz Zakładce 4 (`ALARM LOG`):
         * `x < 480`: Przycisk `[C] POTWIERDŹ / WYCISZ ALARM`
         * `x >= 480`: Przycisk `[M] DŹWIĘK: WŁ/WYŁ`

### 5.3. Zasada bezpiecznego współdzielenia `/dev/fb0` z konsolą `tty1`
W głównej pętli odświeżania ekranu (co `0.5 s` lub natychmiast po kliknięciu):
```python
def is_dashboard_vt_active() -> bool:
    try:
        with open("/sys/class/tty/tty0/active", "r") as f:
            return f.read().strip() == "tty3"
    except Exception:
        return True
```
* Jeśli `is_dashboard_vt_active()` zwraca `False` (użytkownik przełączył się na `tty1` przez przycisk `[5] TERMINAL` lub `Alt+F1`), dashboard **nie zapisuje nic do `/dev/fb0`**.
* Gdy użytkownik w konsoli `tty1` wpisze `soc` (lub naciśnie `Alt+F3`), aktywnym terminalem ponownie staje się `tty3`, a dashboard w kolejnym cyklu natychmiast odmalowuje pełny interfejs graficzny na `/dev/fb0`.

---

## 6. Wizualny System Podświetlania Zakładek (Specyfikacja Kolorów RGB565)

Każda z zakładek `0..3` posiada stan powiadomienia w tle:
* `STATE_NORMAL`:
  * Aktywna zakładka: tło ciemnoniebieskie (`#1E3A8A`), obramowanie cyjan (`#38BDF8`), tekst biały (`#FFFFFF`).
  * Nieaktywna zakładka: tło ciemnoszare (`#1E293B`), tekst jasnoszary (`#94A3B8`).
* `STATE_WARN` (gdy `unread_warns[tab] > 0` i zakładka jest nieaktywna):
  * Tło bursztynowe (`#B45309`), jasna ramka pomarańczowa (`#F59E0B`), tekst biały z licznikiem np. `[2] LAN (!2)`.
* `STATE_ALERT` (gdy `unread_alerts[tab] > 0` i zakładka jest nieaktywna):
  * Tło przełączane co klatkę (efekt pulsowania/migania) pomiędzy jaskrawą czerwienią (`#DC2626`) a ciemnym bordo (`#7F1D1D`), biała ramka ostrzegawcza, tekst biały z licznikiem np. `[3] IDS (!!1)`.

Dzięki temu nawet z drugiego końca pokoju od razu widać, na której zakładce pojawiło się zdarzenie, bez utraty widoku aktualnie obserwowanej zakładki.

---

## 7. Plan Wykonania Krok po Kroku (Checklist dla Agenta AI)

Model AI przejmujący zadanie na komputerze developerskim powinien wykonać kolejno poniższe kroki:

### Krok 1: Implementacja narzędzia dźwięku i wibracji `tools/wm8650_beep.c`
1. Utwórz plik `tools/wm8650_beep.c`.
2. Zaimplementuj mapowanie `/dev/mem` dla `PMC (0xD8130000)`, `GPIO (0xD8110000)`, `SPI0 (0xD8240000)` oraz `I2S (0xD80ED800)` zgodnie z Sekcją 3.1, 3.2 i 3.5.
3. Obsłuż argumenty wiersza poleceń: `click`, `warn`, `alert` (oraz opcjonalnie `test`).
4. W każdym trybie wysteruj równocześnie impulsy wibratora GPIO (Bank 0 Pin 2, `0xD8110040`/`0x80`/`0xC0`) oraz wyślij odpowiednią sekwencję próbek PCM do `I2S ASMPFDP_DMA (0xD80EDB60)` po odblokowaniu wzmacniacza Class-D w `VT1603`.

### Krok 2: Implementacja demona ekranu dotykowego i baterii `tools/wm8650_touchd.c`
1. Utwórz plik `tools/wm8650_touchd.c`.
2. Zaimplementuj inicjalizację `SPI0` i rejestrów dotyku `VT1609` (`0xC0..0xD3`) zgodnie z Sekcją 3.3.
3. W pętli co `25 ms` sprawdzaj bit `PENUP_STS` (`bit 4` w rejestrze `0xCA`).
4. Po wykryciu dotknięcia (z prostym debouncingiem 200 ms, aby pojedyncze dotknięcie palcem generowało jedno zdarzenie kliknięcia) przelicz surowe wartości `raw_x, raw_y` przez macierz `wmt.io.ts.2dcal` i wyślij pakiet UDP `TOUCH <x> <y>\n` na `127.0.0.1:9999`.
5. Co 30 sekund odczytaj napięcie baterii z kanału ADC `VT1609` (rejestry `0xCE`/`0xCF`, Sekcja 3.4) i zapisz wynik w mV oraz procentach do `/run/wm8650_battery.txt`.

### Krok 3: Aktualizacja `tools/Makefile` i utworzenie skryptu `tools/soc`
1. Zaktualizuj `tools/Makefile`, aby kompilował:
   * `wm8650_wifi_on`
   * `wm8650_beep`
   * `wm8650_touchd`
   przy użyciu `arm-linux-gnueabi-gcc -O2 -Wall -static`.
2. Utwórz skrypt `tools/soc`:
   ```sh
   #!/bin/sh
   chvt 3
   ```

### Krok 4: Implementacja głównego dashboardu i silnika IDS `soc_dashboard/wm8650_soc_dashboard.py`
1. Utwórz katalog `soc_dashboard/` oraz plik `soc_dashboard/wm8650_soc_dashboard.py`.
2. Zaimplementuj szybki renderer framebuffera `/dev/fb0` (800×480, 16-bit RGB565) z wbudowanym czytelnym fontem bitmapowym 8×16 (oraz powiększonym 16×32 dla nagłówków i liczników), bez zależności od zewnętrznych czcionek TTF.
3. Zaimplementuj wszystkie 5 zakładek (`[1] PRZEGLĄD`, `[2] HOSTY LAN`, `[3] CZUJNIKI IDS`, `[4] ALARM LOG`, `[5] TERMINAL >_`), wątek pingowania/zasobów, wątek ARP Guard + LAN Discovery, wątek Canary Honeypot (`21, 23, 80, 445, 3389, 5900, 8080`) oraz wątek obsługi dotyku/klawiatury/myszy zgodnie z Sekcją 5 i 6.
4. Zadbaj o sprawdzanie `/sys/class/tty/tty0/active == "tty3"` przed każdym zapisem do `/dev/fb0`.

### Krok 5: Utworzenie usługi startowej `soc_dashboard/wm8650-soc.init` oraz integracja w `install_debian12_bookworm.sh`
1. Utwórz skrypt SysVinit `soc_dashboard/wm8650-soc.init` instalowany jako `/etc/init.d/wm8650-soc`:
   * Przy starcie uruchamia w tle `/usr/local/bin/wm8650-touchd`, przełącza terminal `tty3` w tryb bez kursora (`TERM=linux setterm -cursor off > /dev/tty3`), uruchamia `wm8650_soc_dashboard.py` i przełącza widok na `tty3` (`chvt 3`), pozostawiając `tty1` i `tty2` z aktywnym `getty`.
   * Udostępnia komendy `service wm8650-soc start|stop|restart|status`.
2. Zaktualizuj `install_debian12_bookworm.sh`:
   * Dodaj kompilację `wm8650_beep` i `wm8650_touchd` (przez `make -C tools`).
   * Dodaj pakiety `python3-minimal` oraz `kbd` do instalacji `apt-get` w chroocie.
   * Skopiuj `wm8650_beep`, `wm8650_touchd`, `soc` oraz `wm8650_soc_dashboard.py` do `/usr/local/bin/` na karcie SD.
   * Skopiuj i aktywuj usługę `/etc/init.d/wm8650-soc` (`update-rc.d wm8650-soc defaults 99`).
   * Dodaj informację w `/etc/motd` na `tty1`: `Wpisz 'soc' aby wrocic na ekran graficzny SOC/IDS Dashboard (tty3) lub 'wifi-menu' aby skonfigurowac Wi-Fi.`

### Krok 6: Weryfikacja kompilacji
1. Przetestuj kompilację krzyżową `make -C tools` oraz sprawdź składnię Pythona `python3 -m py_compile soc_dashboard/wm8650_soc_dashboard.py` i skryptów powłoki `bash -n install_debian12_bookworm.sh`.
