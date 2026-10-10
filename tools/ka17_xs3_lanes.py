#!/usr/bin/env python3
"""Offline check for misplaced short stack loads/stores in KA17 peak code.

This is deliberately NOT a complete XS3 instruction validator. It recognizes
LDWSP/STWSP directly from their documented six-bit opcodes, independently of
Capstone, the patch assembler and the coefficient interpreter. The caller must
provide a word-aligned region known to execute in dual-issue mode.

XM-014007-PS v2.1.0: sections 5.2, 22.124, 22.191 and 25.1.
https://www.xmos.com/documentation/XM-014007-PS/pdf/XM-014007-PS-xs3-arch-inst-2.1.0.pdf
"""
import argparse
import json
from pathlib import Path
import struct


def stack_lane_violations(data, address):
    if address % 4 or len(data) % 4:
        raise ValueError('Dual-issue window must be word aligned')
    errors = []
    for offset in range(0, len(data), 4):
        resource, _ = struct.unpack_from('<HH', data, offset)
        opcode = resource & 0xFC00
        # Short STWSP=010101..., LDWSP=010111... . Long forms begin
        # with a prefix and use both lanes; they cannot match these masks.
        if opcode in (0x5400, 0x5C00):
            errors.append({'address': hex(address+offset),
                           'opcode': 'STWSP' if opcode == 0x5400 else 'LDWSP',
                           'bundle': data[offset:offset+4].hex(),
                           'error': 'short stack memory instruction in resource lane'})
    return errors


def require_stack_memory_lane(data, address):
    errors = stack_lane_violations(data, address)
    if errors:
        first = errors[0]
        raise ValueError(f"Illegal XS3 lane at {first['address']}: "
                         f"{first['opcode']} requires memory lane (second halfword)")


def main():
    import ka17_peq_analyze as k

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    args = parser.parse_args()
    stock = next((k.ROOT/'KA17 V2.25 Firmware').rglob('Fiio_KA17_xmos_dfu_V225.bin'))
    images = k.load_images(stock)
    raw = args.firmware.read_bytes()
    if len(raw) != stock.stat().st_size:
        raise ValueError('Unexpected container size; pinned V2.25 layout required')
    decoded = raw.translate(k.SWAP)
    # This CLI accepts only the known V2.25 image layout, including patched
    # versions. Headers and the mode-setting peak entry must remain identical.
    original = stock.read_bytes().translate(k.SWAP)
    for im in images:
        a = im['offset']+12
        if decoded[a:a+244] != original[a:a+244]:
            raise ValueError('Image layout differs from pinned V2.25')
    results = []
    for im in images:
        if im['id'] not in (3, 6, 7):
            continue
        start = im['tile1_offset']+k.PEAK-k.BASE
        if decoded[start:start+4] != bytes.fromhex('ff178e7f'):
            raise ValueError('Expected dual-issue peak prologue missing')
        errors = stack_lane_violations(decoded[start:start+k.FLOAT_END-k.PEAK], k.PEAK)
        results.append({'image': im['id'], 'violations': errors})
    print(json.dumps({'scope': 'short stack memory lane placement only',
                      'firmware': str(args.firmware), 'results': results}, indent=2))
    raise SystemExit(1 if any(r['violations'] for r in results) else 0)


if __name__ == '__main__':
    main()
