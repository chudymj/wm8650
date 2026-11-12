/*
 * wm8650_rgb565.c - Ultra-fast RGB888 to RGB565 converter and framebuffer direct writer
 *                   optimized for WonderMedia WM8650 (ARM926EJ-S / 16KB L1 data cache).
 */

#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>

#define FB_WIDTH 800

/* Direct in-place conversion + write using L1-friendly scanline buffer */
int fb_write_rgb888(int fb_fd, const uint8_t *src, int count) {
    static uint16_t line_buf[FB_WIDTH];
    const uint8_t *s = src;
    int remaining = count;
    off_t offset = 0;

    while (remaining > 0) {
        int chunk = (remaining > FB_WIDTH) ? FB_WIDTH : remaining;
        uint16_t *d = line_buf;
        for (int i = 0; i < chunk; i++) {
            uint32_t r = s[0];
            uint32_t g = s[1];
            uint32_t b = s[2];
            *d++ = (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
            s += 3;
        }
        size_t bytes_to_write = (size_t)(chunk * 2);
        ssize_t written = pwrite(fb_fd, line_buf, bytes_to_write, offset);
        if (written <= 0) {
            return -1;
        }
        offset += written;
        remaining -= chunk;
    }
    return 0;
}

void rgb888_to_rgb565(const uint8_t *src, uint16_t *dst, int count) {
    const uint8_t *s = src;
    uint16_t *d = dst;
    for (int i = 0; i < count; i++) {
        uint32_t r = s[0];
        uint32_t g = s[1];
        uint32_t b = s[2];
        *d++ = (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
        s += 3;
    }
}
