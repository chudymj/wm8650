#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stdint.h>

#define GPIO_BASE 0xd8110000
#define MAP_SIZE  4096UL

int main(int argc, char **argv) {
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open /dev/mem");
        return 1;
    }

    void *map = mmap(NULL, MAP_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, GPIO_BASE);
    if (map == MAP_FAILED) {
        perror("mmap");
        close(fd);
        return 1;
    }

    // WMT Bank 0 registers:
    // 0x40: reg_en (GPIO Enable)
    // 0x80: reg_dir (Direction: 1 = output, 0 = input)
    // 0xc0: reg_data_out (Data Out: 1 = 3.3V, 0 = 0V)
    volatile uint32_t *reg_en   = (volatile uint32_t *)((char *)map + 0x40);
    volatile uint32_t *reg_dir  = (volatile uint32_t *)((char *)map + 0x80);
    volatile uint32_t *reg_dout = (volatile uint32_t *)((char *)map + 0xc0);

    uint32_t pin_mask = (1 << 6); // Pin 6

    printf("Przed: EN=0x%08x DIR=0x%08x DOUT=0x%08x\n", *reg_en, *reg_dir, *reg_dout);

    // 1. Wlacz tryb GPIO i kierunek wyjscia
    *reg_en  |= pin_mask;
    *reg_dir |= pin_mask;

    // 2. Krotki reset zasilania (OFF -> sleep -> ON)
    *reg_dout &= ~pin_mask;
    printf("Reset: Wylaczono zasilanie (DOUT=0x%08x)\n", *reg_dout);
    usleep(300000); // 300ms

    // 3. Wlaczenie zasilania (3.3V)
    *reg_dout |= pin_mask;
    printf("Po:    EN=0x%08x DIR=0x%08x DOUT=0x%08x\n", *reg_en, *reg_dir, *reg_dout);
    printf("Zasilanie Wi-Fi (GPIO 6) WLACZONE (3.3V)!\n");

    munmap(map, MAP_SIZE);
    close(fd);
    return 0;
}
