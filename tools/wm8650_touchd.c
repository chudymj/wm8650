/*
 * wm8650_touchd.c - Userspace driver daemon for VIA VT1609 resistive touchscreen
 *                   and battery SAR-ADC over SPI0 (0xD8240000) on WM8650.
 *
 * Calibrated using factory parameters from backup_wm8650/uboot_env.txt:
 *   wmt.io.touch=1:vt1609:2:800:480
 *   wmt.io.ts.2dcal=174 -23279 47793714 14523 268 -4891371 55776
 *
 * Sends calibrated tap coordinates "TOUCH <x> <y>\n" via UDP to 127.0.0.1:9999
 * and writes battery voltage/percentage to /run/wm8650_battery.txt.
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <time.h>

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

static uint8_t vt1603_read(volatile uint8_t *spi, uint8_t reg) {
    spi0_reset_fifo(spi);
    REG8(spi + 0x10) = (reg & 0x7F);
    REG8(spi + 0x10) = (reg >> 7) & 0x01;
    REG8(spi + 0x10) = 0xFF;
    int timeout = 20000;
    while ((REG32(spi + 0x04) & (1u << 7)) && --timeout > 0) {}
    (void)REG8(spi + 0x30);
    (void)REG8(spi + 0x30);
    return REG8(spi + 0x30);
}

static void init_spi0_and_vt1609(volatile uint8_t *pmc, volatile uint8_t *gpio, volatile uint8_t *spi) {
    /* Enable GPIO (11), SPI0 (12), AHB1 (15) clocks in PMCEL (0x250) */
    REG32(pmc + 0x250) |= (1u << 11) | (1u << 12) | (1u << 15);
    REG32(pmc + 0x254) |= (1u << 3) | (1u << 4);

    /* Configure GP11 (0x004B) bits 0..3 as hardware SPI0 */
    REG8(gpio + 0x004B) &= ~0x0F;
    REG8(gpio + 0x048B) |= 0x0F;
    REG8(gpio + 0x04CB) |= 0x0E;

    /* Initialize SPI0 controller */
    REG32(spi + 0x00) = (30u << 21) | (1u << 16) | (1u << 17);
    REG32(spi + 0x04) = 0xFFFFFFFFu;
    REG32(spi + 0x08) = (1u << 2) | (1u << 5);
    REG32(spi + 0x0C) = 0x20u;
    REG32(spi + 0x00) |= (1u << 5);

    /* Initialize VT1609 SAR-ADC & Touchscreen state machine */
    vt1603_write(spi, 0xC0, 0x08); /* PWC_REG: enable SAR-ADC power & TS clock */
    vt1603_write(spi, 0xC3, 0x60); /* Panel settling time */
    uint8_t intcr = vt1603_read(spi, 0xC8);
    vt1603_write(spi, 0xC8, intcr & ~(1u << 7)); /* Active low IRQ */
    vt1603_write(spi, 0xCA, vt1603_read(spi, 0xCA) | 0x09); /* Clear INTS */
    vt1603_write(spi, 0xC1, 0x02); /* CR_REG: BIT1 = Auto X/Y position mode */
}

static void update_battery_file(volatile uint8_t *spi) {
    /* Switch temporarily to manual battery ADC channel (BIT0) */
    vt1603_write(spi, 0xC1, 0x00);
    vt1603_write(spi, 0xC6, 0x00);
    vt1603_write(spi, 0xC7, 0x01); /* AMCR_REG: Battery channel */
    vt1603_write(spi, 0xCA, vt1603_read(spi, 0xCA) | 0x01);
    vt1603_write(spi, 0xC1, (1u << 4)); /* Start manual ADC conversion */
    usleep(6000);
    uint8_t bl = vt1603_read(spi, 0xCE);
    uint8_t bh = vt1603_read(spi, 0xCF);
    /* Restore auto touchscreen mode */
    vt1603_write(spi, 0xC1, 0x02);

    int raw_bat = ((bh & 0x0F) << 8) | bl;
    int mv = (raw_bat * 1047) / 1000;
    if (mv < 3000 || mv > 4500) {
        /* Fallback if powered directly by DC adapter or uncalibrated */
        mv = 4050;
    }
    int pct = (mv - 3500) * 100 / (4100 - 3500);
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;

    FILE *fp = fopen("/run/wm8650_battery.txt", "w");
    if (fp) {
        fprintf(fp, "%d %d\n", mv, pct);
        fclose(fp);
    }
}

int main(int argc, char **argv) {
    int swap_xy = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--swap-xy") == 0) {
            swap_xy = 1;
        }
    }

    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open /dev/mem");
        return 1;
    }

    void *pmc_map  = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, PMC_BASE);
    void *gpio_map = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, GPIO_BASE);
    void *spi_map  = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, SPI0_BASE);
    if (pmc_map == MAP_FAILED || gpio_map == MAP_FAILED || spi_map == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 1;
    }

    volatile uint8_t *pmc  = (volatile uint8_t *)pmc_map;
    volatile uint8_t *gpio = (volatile uint8_t *)gpio_map;
    volatile uint8_t *spi  = (volatile uint8_t *)spi_map;

    init_spi0_and_vt1609(pmc, gpio, spi);

    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in dst;
    memset(&dst, 0, sizeof(dst));
    dst.sin_family = AF_INET;
    dst.sin_port = htons(9999);
    dst.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    /* Calibration coefficients from backup_wm8650/uboot_env.txt:
     * wmt.io.ts.2dcal=174 -23279 47793714 14523 268 -4891371 55776
     */
    const int64_t a1 = 174,   b1 = -23279, c1 = 47793714;
    const int64_t a2 = 14523, b2 = 268,    c2 = -4891371;
    const int64_t denom = 55776;

    int pen_was_down = 0;
    int down_samples = 0;
    int sum_x = 0, sum_y = 0;
    time_t last_bat_check = 0;

    while (1) {
        time_t now = time(NULL);
        if (now - last_bat_check >= 30) {
            update_battery_file(spi);
            last_bat_check = now;
        }

        uint8_t ints = vt1603_read(spi, 0xCA);
        int pen_down = ((ints & (1u << 4)) == 0);

        if (pen_down) {
            uint8_t xl = vt1603_read(spi, 0xD0);
            uint8_t xh = vt1603_read(spi, 0xD1);
            uint8_t yl = vt1603_read(spi, 0xD2);
            uint8_t yh = vt1603_read(spi, 0xD3);
            vt1603_write(spi, 0xCA, ints | 0x09);

            int rx = ((xh & 0x0F) << 8) | xl;
            int ry = ((yh & 0x0F) << 8) | yl;
            if (swap_xy) {
                int tmp = rx;
                rx = ry;
                ry = tmp;
            }

            if (rx > 50 && rx < 4040 && ry > 50 && ry < 4040) {
                sum_x += rx;
                sum_y += ry;
                down_samples++;

                if (!pen_was_down && down_samples >= 2) {
                    int avg_rx = sum_x / down_samples;
                    int avg_ry = sum_y / down_samples;

                    int px = (int)((a1 * avg_rx + b1 * avg_ry + c1) / denom);
                    int py = (int)((a2 * avg_rx + b2 * avg_ry + c2) / denom);
                    if (px < 0) px = 0;
                    if (px > 799) px = 799;
                    if (py < 0) py = 0;
                    if (py > 479) py = 479;

                    char msg[64];
                    int len = snprintf(msg, sizeof(msg), "TOUCH %d %d %d %d\n", px, py, avg_rx, avg_ry);
                    sendto(sock, msg, (size_t)len, 0, (struct sockaddr *)&dst, sizeof(dst));

                    pen_was_down = 1;
                }
            }
        } else {
            pen_was_down = 0;
            down_samples = 0;
            sum_x = 0;
            sum_y = 0;
        }

        usleep(25000); /* 25 ms polling interval (40 Hz) */
    }

    return 0;
}
