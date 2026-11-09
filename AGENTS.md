# Wytyczne dla Agentów AI (AGENTS.md) – Projekt WonderMedia WM8650 Debian 12 & SOC/IDS

Ten plik zawiera obowiązkowe reguły architektoniczne i jakościowe dla każdego modelu AI (w szczególności modeli szybkich klasy **Gemini Flash**) pracującego nad tym repozytorium.

## 1. Kontekst Sprzętowy (Niezmienny)
* **Urządzenie:** Tablet 7" (`puzhi_7inch_vt1609_ts`) z procesorem **WonderMedia WM8650** (`ARM926EJ-S`, architektura `armel` / ARMv5TEJ, 256 MB RAM, 800×480 LCD 16-bit RGB565 `/dev/fb0`).
* **System:** Debian 12 (Bookworm) `armel` z `sysvinit-core` (bez `systemd`!) oraz jądrem **Mainline Linux 6.1 LTS** (`arch/arm/boot/dts/wm8650-mid.dts`).
* **Peryferia sterowane z przestrzeni użytkownika przez `/dev/mem`:**
  * **Wi-Fi Power (Ralink RT3070 USB):** GPIO Bank 0 Pin 6 (`0xD8110040`, `0xD8110080`, `0xD81100C0` bit 6) – narzędzie `tools/wm8650_wifi_on.c`.
  * **Wibrator / Buzzer:** GPIO Bank 0 Pin 2 (`0xD8110040`, `0xD8110080`, `0xD81100C0` bit 2) – narzędzie `tools/wm8650_beep.c`.
  * **Magistrala SPI0 (`0xD8240000`) + układ MFD VIA `VT1603`/`VT1609`:**
    * Dotyk oporowy `VT1609` (`rejestry 0xC0..0xD3`) + kalibracja `wmt.io.ts.2dcal=174 -23279 47793714 14523 268 -4891371 55776` – demon `tools/wm8650_touchd.c`.
    * Pomiar napięcia baterii SAR-ADC (`rejestry 0xC7, 0xCE, 0xCF`) – zapis do `/run/wm8650_battery.txt`.
    * Kodek audio `VT1603` + kontroler `WMT I2S (`0xD80ED800`, FIFO `0xD80EDB60`)` – narzędzie `tools/wm8650_beep.c`.
* Pełna dokumentacja rejestrów znajduje się w pliku `PLAN_ROZBUDOWY_SOC_IDS.md`.

## 2. Twarde Reguły dla Modeli Klasy Flash (Guardrails)
1. **Zakaz skracania plików i używania placeholderów (`TODO`, `...`):**
   * Podczas edycji `soc_dashboard/wm8650_soc_dashboard.py` lub narzędzi w `tools/` nigdy nie usuwaj istniejących zakładek ani logiki czujników na rzecz skrótów. Używaj precyzyjnych edycji fragmentów pliku.
2. **Zakaz automatycznego przełączania zakładek przy alarmie:**
   * Interfejs ma 5 zakładek (`[1] PRZEGLAD`, `[2] HOSTY LAN`, `[3] CZUJNIKI IDS`, `[4] ALARM LOG`, `[5] TERMINAL >_`).
   * Gdy wystąpi incydent na nieaktywnej zakładce, należy **wyłącznie** wywołać sygnał dźwiękowy/wibrację (`wm8650-beep`) oraz podświetlić odpowiednią zakładkę na pasku górnym (`unread_warn` – bursztynowy, `unread_alert` – pulsujący czerwony). Przełączenie zakładki (`STATE.active_tab`) może nastąpić wyłącznie po kliknięciu lub naciśnięciu klawisza przez użytkownika.
3. **Współpraca z konsolą Linuksa (`tty1` ↔ `tty3`):**
   * Dashboard działa na `tty3`. Przed każdym zapisem do `/dev/fb0` musi sprawdzać, czy `/sys/class/tty/tty0/active` zawiera `tty3`. Gdy użytkownik przełączy się na terminal tekstowy (`tty1` przez zakładkę `[5] TERMINAL >_` lub `chvt 1`), dashboard nie może nadpisywać `/dev/fb0`.
4. **Wydajność konwersji RGB565:**
   * Do konwersji obrazu `Pillow` (`800×480 RGB`) na 16-bitowy bufor `/dev/fb0` zawsze używaj natywnego `img.tobytes("raw", "BGR;16")` (działa w C w czasie ~3 ms na ARM926EJ-S).
5. **Obowiązkowe testy po każdej zmianie kodu:**
   * Przed zakończeniem odpowiedzi zawsze zweryfikuj kompilację i składnię:
     ```bash
     gcc -fsyntax-only -Wall tools/wm8650_wifi_on.c tools/wm8650_beep.c tools/wm8650_touchd.c
     python3 -m py_compile soc_dashboard/wm8650_soc_dashboard.py
     bash -n install_debian12_bookworm.sh soc_dashboard/wm8650-soc.init tools/soc
     ```
