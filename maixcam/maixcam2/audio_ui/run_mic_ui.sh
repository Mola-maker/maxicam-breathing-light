#!/bin/sh
# Launch the MaixCAM2 USB microphone visualizer.
#
# The display is owned by launcher.service, so stop it while the UI is
# running and restore it on exit.  The USB Audio modules and host role are
# set up automatically if no USB capture card is currently present.
set -u

APP_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP_DIR" || exit 1

USB_DIR=/root/JLU_LEDLAB/usb_audio
ROLE_PATH=/sys/class/usb_role/8000000.dwc3-role-switch/role
ORIG_ROLE=$(cat "$ROLE_PATH" 2>/dev/null || true)
HEADLESS=0
for arg in "$@"; do
    [ "$arg" = "--headless" ] && HEADLESS=1
done

# Make the external microphone usable if it is not already enumerated.
if ! arecord -l 2>/dev/null | grep -qi 'USB Audio'; then
    if [ -x "$USB_DIR/enable_usb_mic.sh" ]; then
        "$USB_DIR/enable_usb_mic.sh" || true
    fi
fi

LAUNCHER_WAS_ACTIVE=0
if [ "$HEADLESS" = 0 ] && systemctl is-active --quiet launcher.service; then
    LAUNCHER_WAS_ACTIVE=1
    systemctl stop launcher.service || true
fi

CLEANED=0
cleanup() {
    [ "$CLEANED" = 1 ] && return
    CLEANED=1
    if [ "$LAUNCHER_WAS_ACTIVE" = 1 ]; then
        systemctl start launcher.service >/dev/null 2>&1 || true
    fi
    # If the app had to switch the port from device to host, put it back.
    # Set MIC_UI_KEEP_USB_HOST=1 to keep the USB microphone usable after exit.
    if [ "${MIC_UI_KEEP_USB_HOST:-0}" != "1" ] && [ -x "$USB_DIR/disable_usb_mic.sh" ]; then
        CURRENT_ROLE=$(cat "$ROLE_PATH" 2>/dev/null || true)
        if [ "${MIC_UI_RESTORE_USB:-0}" = "1" ] || { [ "$ORIG_ROLE" = "device" ] && [ "$CURRENT_ROLE" = "host" ]; }; then
            "$USB_DIR/disable_usb_mic.sh" >/dev/null 2>&1 || true
        fi
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

python3 -u app/mic_ui.py "$@"
RC=$?
cleanup
trap - EXIT INT TERM
exit "$RC"
