CROSS_COMPILE ?= arm-linux-gnueabi-
CC := $(CROSS_COMPILE)gcc
CFLAGS ?= -O2 -Wall

all: wm8650_wifi_on wm8650_beep wm8650_touchd libwm8650_rgb565.so

wm8650_wifi_on: wm8650_wifi_on.c
	$(CC) $(CFLAGS) -o $@ $<

wm8650_beep: wm8650_beep.c
	$(CC) $(CFLAGS) -o $@ $<

wm8650_touchd: wm8650_touchd.c
	$(CC) $(CFLAGS) -o $@ $<

libwm8650_rgb565.so: wm8650_rgb565.c
	$(CC) $(CFLAGS) -fPIC -shared -o $@ $<

clean:
	rm -f wm8650_wifi_on wm8650_beep wm8650_touchd libwm8650_rgb565.so

.PHONY: all clean
