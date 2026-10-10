#!/usr/bin/env python3
"""Mark a pinned experimental peak patch as USB bcdDevice 2.26 or 2.27.

Default 2.26 reproduces the historical known-bad artifact for identity checks.
Version 2.27 uses the lane-corrected source and rejects misplaced stack accesses.

Offline only. Changes the nine verified USB device descriptors in images
1/3/6/7, plus tile0 and whole-image CRCs. Does not change MCU version,
image-selection IDs, PEQ instructions, DFU protocol version or file size.
USB version identifies the custom container; it does not prove PEQ accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import ka17_peq_analyze as k
import ka17_patch_peak as patch
from ka17_xs3_lanes import require_stack_memory_lane

SOURCE_SHA256 = '49747c0aec401a5ab14d8cf5e14cf6aba06dd9d8b0969bd2a30630843b3fb0dc'
FIXED_SOURCE_SHA256 = '6dd84c988634e027677cff6a050ef5a1d69d5248d83d08c719e8a1d713523652'
DESCRIPTORS = {1: (0xF820, 0xFA08),
               3: (0x3E670, 0x3E688, 0x3E8C0),
               6: (0xA2970, 0xA2B18),
               7: (0xBA668, 0xBA810)}


def build(version='2.26'):
    if version not in ('2.26', '2.27'):
        raise ValueError('Only pinned 2.26 and 2.27 builds are supported')
    fixed = version == '2.27'
    directory = 'v225-peak-q-lane-fixed' if fixed else 'v225-peak-q-candidate'
    source = k.ROOT/'patches'/directory/'Fiio_KA17_V225_PEAK_Q_EXPERIMENTAL.bin'
    source_hash = FIXED_SOURCE_SHA256 if fixed else SOURCE_SHA256
    bcd = 0x0227 if fixed else 0x0226
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == source_hash
    stock = next((k.ROOT/'KA17 V2.25 Firmware').rglob('Fiio_KA17_xmos_dfu_V225.bin'))
    images = k.load_images(stock)
    decoded = bytearray(raw.translate(k.SWAP))
    before = bytes(decoded)
    patch.checksums(decoded, images)
    if fixed:
        for im in images:
            if im['id'] in (3, 6, 7):
                a = im['tile1_offset']+k.PEAK-k.BASE
                require_stack_memory_lane(decoded[a:a+k.FLOAT_END-k.PEAK], k.PEAK)
    allowed = set()
    for im in images:
        if im['id'] not in DESCRIPTORS:
            continue
        begin, end = im['tile0_offset'], im['tile0_offset']+im['tile0_size']
        discovered = tuple(off for off in range(begin, end-17)
                           if decoded[off:off+2] == b'\x12\x01'
                           and decoded[off+8:off+12] == bytes.fromhex('72299300'))
        assert discovered == DESCRIPTORS[im['id']], (im['id'], discovered)
        for off in discovered:
            assert decoded[off+12:off+14] == bytes.fromhex('2502')
            struct.pack_into('<H', decoded, off+12, bcd)
            allowed.update(range(off+12, off+14))
        allowed.update(range(end-4, end))
        allowed.update(range(im['offset']+8, im['offset']+12))
    patch.checksums(decoded, images, update=True)
    patch.checksums(decoded, images)
    changed = [i for i,(a,b) in enumerate(zip(before,decoded)) if a!=b]
    assert set(changed) <= allowed
    for im in images:
        a,b = im['tile1_offset'],im['tile1_offset']+im['tile1_size']
        assert decoded[a:b] == before[a:b], 'DSP tile was modified'
        a,b = im['offset'],im['offset']+im['size']
        if im['id'] == 5: assert decoded[a:b] == before[a:b], 'MCU update image was modified'
        assert decoded[a+0x14:a+0x18] == before[a+0x14:a+0x18], 'Image selection ID changed'
    output = bytes(decoded).translate(k.SWAP)
    assert len(output) == len(raw)
    edits = [{'offset':hex(i),'before':raw[i:i+1].hex(),'after':output[i:i+1].hex()} for i in changed]
    restored = bytearray(output)
    for edit in edits: restored[int(edit['offset'],16)] = int(edit['before'],16)
    assert restored == raw
    manifest = {'status':'EXPERIMENTAL_USB_VERSION_MARKER_ONLY',
                'source_sha256':source_hash,
                'candidate_sha256':hashlib.sha256(output).hexdigest(),
                'usb_bcdDevice':f'0x{bcd:04x}', 'displayed_usb_version':version,
                'source_lane_fix':fixed,
                'official_release':False,
                'mcu_version_changed':False,
                'file_size':len(output), 'changed_bytes_from_peak_candidate':len(changed),
                'descriptor_offsets':{str(i):[hex(v) for v in offsets] for i,offsets in DESCRIPTORS.items()},
                'checks':['All source and output image/tile CRCs valid','All DSP tiles byte-identical to peak candidate',
                          'MCU image and image selection IDs unchanged','Reversible to exact source SHA-256'],
                'limitations':['On-device display may report unchanged MCU version 2.25',
                               'PEQ accuracy limitations from original candidate remain',
                               'USB version confirms identification only, not audio response'],
                'edits':edits}
    return output, manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',type=Path)
    parser.add_argument('--version',choices=('2.26','2.27'),default='2.26')
    args=parser.parse_args()
    output,manifest=build(args.version)
    if args.verify:
        assert args.verify.read_bytes()==output
    else:
        label=args.version.replace('.', '')
        dest=k.ROOT/'patches'/f'v{label}-peak-q-experimental'
        dest.mkdir(exist_ok=False)
        (dest/f'Fiio_KA17_V{label}_PEAK_Q_EXPERIMENTAL.bin').write_bytes(output)
        (dest/'version-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({a:b for a,b in manifest.items() if a!='edits'},indent=2))


if __name__=='__main__':main()
