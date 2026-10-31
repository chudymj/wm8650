CC ?= arm-linux-gnueabi-gcc
CFLAGS ?= -O2 -Wall

all: wm8650_wifi_on

wm8650_wifi_on: wm8650_wifi_on.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f wm8650_wifi_on

.PHONY: all clean
