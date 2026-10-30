#!/system/bin/sh
mkdir -p /sdcard/backup_wm8650
cat /proc/cmdline > /sdcard/backup_wm8650/cmdline.txt
cat /proc/mtd > /sdcard/backup_wm8650/mtd.txt
lsmod > /sdcard/backup_wm8650/lsmod.txt
dmesg > /sdcard/backup_wm8650/dmesg.txt
cp -r /system/lib/modules /sdcard/backup_wm8650/
for i in 0 1 2 3 4 5 6; do
    dd if=/dev/block/mtdblock$i of=/sdcard/backup_wm8650/mtdblock$i.bin 2>/dev/null
    dd if=/dev/mtd/mtd$i of=/sdcard/backup_wm8650/mtd$i.bin 2>/dev/null
done
echo "Gotowe!"
