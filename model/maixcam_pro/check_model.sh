#!/bin/sh
MODEL="${1:-/root/models/am_3332_192_int8.mud}"
if [ -f "$MODEL" ]; then
    echo "OK: $MODEL"
    ls -lh "$MODEL"
    exit 0
fi
echo "MISSING: $MODEL" >&2
echo "MaixCAM Pro KWS weights are external to this repository." >&2
exit 1
