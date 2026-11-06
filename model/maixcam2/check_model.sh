#!/bin/sh
DIR="${1:-/root/models/sensevoice-maixcam2}"
fail=0
for f in SenseVoiceAx.py am.mvn chn_jpn_yue_eng_ko_spectok.bpe.model \
         client.py embeddings.npy frontend.py model.mud \
         pe_nonstream.npy pe_streaming.npy server.py tokenizer.py \
         sensevoice.axmodel streaming_sensevoice.axmodel; do
    if [ -f "$DIR/$f" ]; then
        printf 'OK   %s\n' "$DIR/$f"
    else
        printf 'MISS %s\n' "$DIR/$f" >&2
        fail=1
    fi
done
[ -f "$DIR/sensevoice.axmodel" ] && sha256sum "$DIR/sensevoice.axmodel"
[ -f "$DIR/streaming_sensevoice.axmodel" ] && sha256sum "$DIR/streaming_sensevoice.axmodel"
exit "$fail"
