#!/bin/sh
# Restore the normal MaixCAM2 USB device/gadget mode.
set -e

ROLE=/sys/class/usb_role/8000000.dwc3-role-switch/role

modprobe -r snd-usb-audio snd-usbmidi-lib snd-rawmidi snd-hwdep 2>/dev/null || true
echo device > "$ROLE"
sleep 1

# usb-gadget has Restart=always and can need one retry right after host mode.
systemctl start usb-gadget.service 2>/dev/null || true
i=0
while [ "$i" -lt 20 ]; do
    if systemctl is-active --quiet usb-gadget.service; then
        break
    fi
    sleep 0.5
    systemctl start usb-gadget.service 2>/dev/null || true
    i=$((i + 1))
done

echo "USB role: $(cat "$ROLE")"
echo "gadget: $(systemctl is-active usb-gadget.service)"
