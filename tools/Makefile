CC ?= arm-linux-gnueabi-gcc
CFLAGS ?= -O2 -Wall

all: wm8650_wifi_on wm8650_beep wm8650_touchd

wm8650_wifi_on: wm8650_wifi_on.c
	$(CC) $(CFLAGS) -o $@ $<

wm8650_beep: wm8650_beep.c
	$(CC) $(CFLAGS) -o $@ $<

wm8650_touchd: wm8650_touchd.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f wm8650_wifi_on wm8650_beep wm8650_touchd

.PHONY: all clean
