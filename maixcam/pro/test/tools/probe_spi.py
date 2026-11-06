#!/usr/bin/env python3
import sys, os, time
import spidev
import stm32_protocol as p
bus = int(sys.argv[1]) if len(sys.argv) > 1 else 3
dev = int(sys.argv[2]) if len(sys.argv) > 2 else 0
s = spidev.SpiDev()
s.open(bus, dev)
s.mode = 0
s.max_speed_hz = 1_000_000
s.bits_per_word = 8
s.cshigh = False
session = 0x12345678
seq = 1
for attempt in range(3):
    tx = p.build_frame(p.TYPE_CONTROL, seq, session,
                       p.hello(heartbeat_ms=50,
                               features=p.FEATURE_PERFORM | p.FEATURE_TEMP))
    seq += 1
    rx = bytes(s.xfer2(list(tx)))
    print('attempt', attempt, 'rx magic', rx[:2].hex(), 'type', rx[3] if len(rx)>3 else None, 'len', int.from_bytes(rx[12:14],'little') if len(rx)>=14 else None)
    print('rx head', rx[:32].hex())
    try:
        st, caps = p.parse_status(rx)
        print('status', st)
        print('caps', caps)
    except Exception as e:
        print('parse err', e)
    time.sleep(0.1)
s.close()
