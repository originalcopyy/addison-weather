#!/bin/sh
# Flash the Note 4C with the current build. The board's USB port only exists
# while it is awake, so this waits for it: start the script, then plug in USB
# or hold DOWN for 3 s. Needs esptool on the PATH (brew install esptool).
# Usage: firmware/flash.sh [minutes to wait, default 30]
cd "$(dirname "$0")" || exit 1
wait_min=${1:-30}
end=$(( $(date +%s) + wait_min * 60 ))
echo "waiting up to $wait_min min for the board (plug in USB or hold DOWN)"
while [ "$(date +%s)" -lt "$end" ]; do
  port=$(ls /dev/cu.usbmodem* 2>/dev/null | head -n 1)
  if [ -n "$port" ]; then
    echo "found $port"
    exec esptool --chip esp32s3 --port "$port" --baud 460800 --before default-reset --after hard-reset \
      write-flash -z --flash-mode dio --flash-size 16MB --flash-freq 80m \
      0x0 build/bootloader/bootloader.bin \
      0x8000 build/partition_table/partition-table.bin \
      0x10000 build/addison_weather.bin
  fi
  sleep 0.5
done
echo "no board appeared in $wait_min min" >&2
exit 1
