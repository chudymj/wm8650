/*
 * wm8650_beep.c - Hardware audio alert (VT1603 Class-D / HP via SPI0 + WMT I2S)
 *                 and tactile vibrator/buzzer alert (GPIO Bank 0 Bit 2)
 *                 for WonderMedia WM8650 on Mainline Linux 6.1 LTS.
 *
 * Usage:
 *   wm8650-beep click   - short 25ms tactile/audio feedback on touch
 *   wm8650-beep warn    - single 160ms 880Hz warning tone + vibration
 *   wm8650-beep alert   - triple urgent 1760Hz/880Hz IDS alarm + vibration
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#define I2S_BASE  0xD80ED000UL
#define I2S_OFF   0x00000800UL
#define GPIO_BASE 0xD8110000UL
#define PMC_BASE  0xD8130000UL
#define SPI0_BASE 0xD8240000UL
#define MAP_SIZE  4096UL

#define REG8(addr)  (*(volatile uint8_t *)(addr))
#define REG32(addr) (*(volatile uint32_t *)(addr))

static void spi0_reset_fifo(volatile uint8_t *spi) {
    REG32(spi + 0x00) |= (1u << 16) | (1u << 17);
    int timeout = 10000;
    while ((REG32(spi + 0x04) & (1u << 7)) && --timeout > 0) {}
}

static void vt1603_write(volatile uint8_t *spi, uint8_t reg, uint8_t val) {
    spi0_reset_fifo(spi);
    REG8(spi + 0x10) = (reg & 0x7F) | 0x80;
    REG8(spi + 0x10) = (reg >> 7) & 0x01;
    REG8(spi + 0x10) = val;
    int timeout = 20000;
    while ((REG32(spi + 0x04) & (1u << 7)) && --timeout > 0) {}
    (void)REG8(spi + 0x30);
    (void)REG8(spi + 0x30);
    (void)REG8(spi + 0x30);
}

static void hw_enable_clocks_and_pinmux(volatile uint8_t *pmc, volatile uint8_t *gpio, volatile uint8_t *spi) {
    /* Enable PWM (10), GPIO (11), SPI0 (12), AHB1 (15), I2S (16) clocks in PMCEL (0x250) */
    REG32(pmc + 0x250) |= (1u << 10) | (1u << 11) | (1u << 12) | (1u << 15) | (1u << 16);
    /* Enable ARF (3) & ARFP (4) in PMCEU (0x254) */
    REG32(pmc + 0x254) |= (1u << 3) | (1u << 4);
    /* Enable AUD_CLK (2) in PMCE3 (0x25C) */
    REG32(pmc + 0x25C) |= (1u << 2);

    /* Configure SPI0 pins (GP11: MOSI=0, MISO=1, SS=2, CLK=3 -> clear bits for HW SPI mode) */
    REG8(gpio + 0x004B) &= ~0x0F;
    REG8(gpio + 0x048B) |= 0x0F;
    REG8(gpio + 0x04CB) |= 0x0E;

    /* Configure I2S pins (GP10 -> 0x00 for HW I2S mode, Pin sharing bit 2 = 0 for I2S) */
    REG8(gpio + 0x004A) = 0x00;
    REG32(gpio + 0x0200) &= ~(1u << 2);
    REG32(gpio + 0x0200) |= (1u << 0);

    /* Configure Vibrator / Buzzer GPIO (Bank 0, Pin 2: 0x40 EN, 0x80 DIR, 0xC0 OUT) */
    REG8(gpio + 0x0040) |= (1u << 2);
    REG8(gpio + 0x0080) |= (1u << 2);

    /* Initialize SPI0 controller if not already enabled */
    if ((REG32(spi + 0x00) & (1u << 5)) == 0) {
        REG32(spi + 0x00) = (30u << 21) | (1u << 16) | (1u << 17);
        REG32(spi + 0x04) = 0xFFFFFFFFu;
        REG32(spi + 0x08) = (1u << 2) | (1u << 5);
        REG32(spi + 0x0C) = 0x20u;
        REG32(spi + 0x00) |= (1u << 5);
    }
}

static void vt1603_audio_unmute(volatile uint8_t *spi, volatile uint8_t *i2s) {
    /* Configure VT1603 DAC, Mixers, Headphone and Class-D Speaker amplifier */
    vt1603_write(spi, 0x05, 0xC0); /* DAC Vol L */
    vt1603_write(spi, 0x06, 0xC0); /* DAC Vol R */
    vt1603_write(spi, 0x07, 0x80); /* DAC unmute */
    vt1603_write(spi, 0x0B, 0x03); /* DAC digital L+R enable */
    vt1603_write(spi, 0x19, 0x22); /* 16-bit I2S */
    vt1603_write(spi, 0x25, 0x1A); /* Sysclk & Class-D clock enable */
    vt1603_write(spi, 0x60, 0xC7); /* VREF & VMID power up */
    vt1603_write(spi, 0x62, 0xDC); /* Analog DAC L+R power up */
    vt1603_write(spi, 0x68, 0x0C); /* HP mixer power up */
    vt1603_write(spi, 0x69, 0x03); /* AA mixer power up */
    vt1603_write(spi, 0x71, 0xDF); /* Left mixer DAC unmute */
    vt1603_write(spi, 0x72, 0xDF); /* Right mixer DAC unmute */
    vt1603_write(spi, 0x73, 0xE0); /* L+R mixer enable */
    vt1603_write(spi, 0x79, 0x79); /* HP Vol L */
    vt1603_write(spi, 0x7A, 0x39); /* HP Vol R */
    vt1603_write(spi, 0x7C, 0xE0); /* Class-D speaker output L+R enable */
    vt1603_write(spi, 0x90, 0x1C); /* Class-D boost */
    vt1603_write(spi, 0x91, 0x02); /* Speaker gain */
    vt1603_write(spi, 0x92, 0xFF); /* Class-D driver unmute */

    /* Initialize WMT I2S DAC + FIFO */
    REG32(i2s + 0x244) = 0x1Fu;     /* AUDPRFRST */
    REG32(i2s + 0x040) = 0x402001u; /* DACCFG: enable 16-bit stereo I2S TX */
    REG32(i2s + 0x194) = 0x10101010u; /* ASMPFCHCFG0 */
    REG32(i2s + 0x180) = 0x52u;     /* ASMPFCFG: enable + 16-bit + 2ch */
}

static void play_tone_and_vibrate(
    volatile uint8_t *gpio,
    volatile uint8_t *i2s,
    int freq_hz,
    int duration_ms,
    int use_vibrator
) {
    if (use_vibrator) {
        REG8(gpio + 0x00C0) |= (1u << 2);
    }

    if (freq_hz > 0 && duration_ms > 0) {
        int sample_rate = 16000;
        int total_samples = (sample_rate * duration_ms) / 1000;
        int half_period = sample_rate / (freq_hz * 2);
        if (half_period < 1) half_period = 1;

        for (int i = 0; i < total_samples; i++) {
            int16_t sample = ((i / half_period) & 1) ? 14000 : -14000;
            uint32_t stereo_sample = ((uint32_t)(uint16_t)sample << 16) | (uint16_t)sample;
            REG32(i2s + 0x360) = stereo_sample;
            if ((i & 7) == 0) {
                usleep(450);
            }
        }
    } else if (duration_ms > 0) {
        usleep((useconds_t)duration_ms * 1000);
    }

    if (use_vibrator) {
        REG8(gpio + 0x00C0) &= ~(1u << 2);
    }
}

int main(int argc, char **argv) {
    const char *mode = (argc > 1) ? argv[1] : "warn";

    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        return 1;
    }

    void *pmc_map  = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, PMC_BASE);
    void *gpio_map = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, GPIO_BASE);
    void *spi_map  = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, SPI0_BASE);
    void *i2s_page = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0xD80ED000UL);

    if (pmc_map == MAP_FAILED || gpio_map == MAP_FAILED ||
        spi_map == MAP_FAILED || i2s_page == MAP_FAILED) {
        close(fd);
        return 1;
    }

    volatile uint8_t *pmc  = (volatile uint8_t *)pmc_map;
    volatile uint8_t *gpio = (volatile uint8_t *)gpio_map;
    volatile uint8_t *spi  = (volatile uint8_t *)spi_map;
    volatile uint8_t *i2s  = (volatile uint8_t *)i2s_page + I2S_OFF;

    hw_enable_clocks_and_pinmux(pmc, gpio, spi);
    vt1603_audio_unmute(spi, i2s);

    if (strcmp(mode, "click") == 0) {
        play_tone_and_vibrate(gpio, i2s, 1200, 20, 1);
    } else if (strcmp(mode, "alert") == 0) {
        for (int k = 0; k < 3; k++) {
            play_tone_and_vibrate(gpio, i2s, 1760, 110, 1);
            usleep(60000);
            play_tone_and_vibrate(gpio, i2s, 880, 110, 1);
            usleep(70000);
        }
    } else {
        /* Default: "warn" */
        play_tone_and_vibrate(gpio, i2s, 880, 160, 1);
    }

    /* Mute Class-D speaker when idle to save battery and eliminate hiss */
    vt1603_write(spi, 0x07, 0xC0);

    munmap(i2s_page, MAP_SIZE);
    munmap(spi_map, MAP_SIZE);
    munmap(gpio_map, MAP_SIZE);
    munmap(pmc_map, MAP_SIZE);
    close(fd);
    return 0;
}
