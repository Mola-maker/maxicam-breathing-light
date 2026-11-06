#!/bin/sh
# Switch MaixCAM2 USB-C to host mode and enable the installed USB Audio Class
# modules.  USB gadget networking is unavailable while this is active.
set -e

ROLE=/sys/class/usb_role/8000000.dwc3-role-switch/role
MODS="snd-usb-audio snd-usbmidi-lib snd-rawmidi snd-hwdep"

modprobe snd-usb-audio
systemctl stop usb-gadget.service 2>/dev/null || true
echo host > "$ROLE"

# Wait for the USB audio card to appear.
i=0
while [ "$i" -lt 40 ]; do
    if arecord -l 2>/dev/null | grep -q 'USB Audio'; then
        break
    fi
    sleep 0.25
    i=$((i + 1))
done

# PCM2902/CM108-class devices expose a capture volume, usually defaulting to 0.
for card in $(arecord -l 2>/dev/null | awk '/^card / {gsub(":", "", $2); print $2}'); do
    if arecord -l 2>/dev/null | grep -A1 "^card $card:" | grep -q 'USB Audio'; then
        amixer -c "$card" cset numid=3 16 >/dev/null 2>&1 || true
        amixer -c "$card" cset numid=4 on >/dev/null 2>&1 || true
        echo "USB microphone card=$card"
    fi
done

echo "USB role: $(cat "$ROLE")"
arecord -l
