#!/usr/bin/env python3
"""Read/save KA17 user PEQ over USB HID, without a browser. Never flashes firmware.

Protocol source: official https://fiiocontrol.fiio.com/static/js/index-B_yYxU3i.js
SHA256 f223151bbdc964883d4573767625bbaf6a34ce9c4babe314ad33d7bfafb19921.
Commands pre/cN, fN/aT, vre/dN, bre; encoder ut/y6e. See KA17-PEQ-USB.md.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import struct
import sys
import time

VID, PID, REPORT_ID = 0x2972, 0x0093, 1
SLOTS = {'USER1': 4, 'USER2': 8, 'USER3': 9}
TYPES = {'PEAK': 0, 'LOW_SHELF': 1, 'HIGH_SHELF': 2}
READ, WRITE = 0xBB, 0xAA
BAND, PRESET, GAIN, COUNT, SAVE = 0x15, 0x16, 0x17, 0x18, 0x19


def crc8(data):
    """CRC-8/MAXIM, reflected polynomial 0x8c, initial value zero."""
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8C if crc & 1 else 0)
    return crc


def packet(command, payload=b'', *, write=False, sequence=0):
    allowed = {BAND, PRESET, GAIN, SAVE} if write else {BAND, PRESET, GAIN, COUNT}
    if command not in allowed:
        raise ValueError('Command outside the PEQ-only allowlist')
    head = struct.pack('>BBHBB', WRITE if write else READ,
                       10 if write else 11, sequence, command, len(payload)) + payload
    return head + bytes((crc8(head), 0xEE))


def response_payload(raw, command, index=None):
    """Ignore padding, unrelated reports and delayed responses to other reads.

    KA17 2.27 returns sequence=0 and checksum=0, even for nonzero request
    sequences. Matching uses command and band index, with one request in flight.
    Envelope, payload length, end marker and decoded values are checked.
    """
    if not raw or raw[0] != REPORT_ID:
        return None
    data = raw[1:]
    if len(data) < 8 or data[:2] != b'\xbb\x0b' or data[4] != command:
        return None
    n = data[5]
    if len(data) < n+8 or data[n+7] != 0xEE:
        return None
    payload = data[6:6+n]
    if index is not None and (not payload or payload[0] != index):
        return None
    return payload


def scaled(value, scale, low, high, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field}: number required')
    try:
        number = Decimal(str(value))
        units = number * scale
        if not number.is_finite() or not low <= number <= high or units != units.to_integral_value():
            raise ValueError(f'{field}: must be {low}..{high}, step {1/scale:g}')
        return int(units)
    except InvalidOperation as exc:
        raise ValueError(f'{field}: invalid number') from exc


def band_payload(index, band):
    if not 0 <= index < 10 or not isinstance(band, dict):
        raise ValueError('Expected band index 0..9 and a band object')
    if set(band) != {'type', 'frequency_hz', 'gain_db', 'q'} or band['type'] not in TYPES:
        raise ValueError('Supported band types: PEAK, LOW_SHELF, HIGH_SHELF')
    return struct.pack('>BhHHB', index,
                       scaled(band['gain_db'], 10, -12, 12, 'gain_db'),
                       scaled(band['frequency_hz'], 1, 20, 20000, 'frequency_hz'),
                       scaled(band['q'], 100, .25, 8, 'q'), TYPES[band['type']])


def decode_band(payload, index):
    if len(payload) != 8:
        raise ValueError('Invalid band response length')
    pos, gain, freq, q, kind = struct.unpack('>BhHHB', payload)
    if pos != index or kind not in TYPES.values():
        raise ValueError('Unexpected band index/type; refusing incomplete backup')
    band = {'type': next(k for k, v in TYPES.items() if v == kind),
            'frequency_hz': freq, 'gain_db': gain/10, 'q': q/100}
    band_payload(index, band)
    return band


def validate_document(document):
    if not isinstance(document, dict) or document.get('schema') != 1:
        raise ValueError('Expected JSON schema 1')
    presets = document.get('presets')
    if not isinstance(presets, list) or not presets or len(presets) > 3:
        raise ValueError('Expected one to three user presets')
    seen = set()
    for preset in presets:
        if not isinstance(preset, dict) or preset.get('slot') not in SLOTS:
            raise ValueError('Only USER1, USER2 and USER3 can be written')
        if preset['slot'] in seen:
            raise ValueError('Duplicate preset slot')
        seen.add(preset['slot'])
        scaled(preset.get('preamp_db'), 10, -12, 12, 'preamp_db')
        bands = preset.get('bands')
        if not isinstance(bands, list) or len(bands) != 10:
            raise ValueError('Exactly 10 bands are required, including neutral unused bands')
        for index, band in enumerate(bands):
            band_payload(index, band)
    return presets


class KA17:
    def __init__(self):
        import hid  # Only device commands require the optional USB dependency.
        devices = {x['path']: x for x in hid.enumerate(VID, PID)
                   if x['product_string'] == 'FIIO KA17'}
        if len(devices) != 1:
            raise RuntimeError(f'Expected one KA17, found {len(devices)}. Enable EQ and close FiiO Control.')
        self.info = next(iter(devices.values()))
        self.device = hid.device()
        self.device.open_path(self.info['path'])
        self.sequence = 0
        self.last_send = 0.0

    def close(self):
        self.device.close()

    def send(self, command, payload=b'', write=False):
        # The official KA17 queue uses a 200 ms interval. Avoid racing firmware.
        time.sleep(max(0, self.last_send + .2 - time.monotonic()))
        data = bytes([REPORT_ID]) + packet(command, payload, write=write, sequence=self.sequence)
        self.sequence = (self.sequence+1) & 0xFFFF
        result = self.device.write(data)
        self.last_send = time.monotonic()
        if result != len(data):
            raise OSError('Incomplete HID write')

    def read(self, command, payload=b'', index=None):
        # Clear already queued reports. A read is never accepted solely because
        # it is the first input report after sending the command.
        for _ in range(64):
            if not self.device.read(128, 1):
                break
        else:
            raise RuntimeError('Unexpected HID traffic; close other KA17 controllers')
        self.send(command, payload)
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            raw = bytes(self.device.read(128, 250))
            result = response_payload(raw, command, index)
            if result is not None:
                return result
        raise TimeoutError(f'KA17 read timed out: command={command:#x}, band={index}')

    def active(self):
        payload = self.read(PRESET)
        if len(payload) != 1 or payload[0] not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            raise ValueError('Invalid active preset response')
        return payload[0]

    def select(self, number):
        if self.active() != number:
            self.send(PRESET, bytes([number]), write=True)
            time.sleep(.3)
        if self.active() != number:
            raise RuntimeError(f'Preset switch to {number} did not take effect')

    def current(self):
        number = self.active()
        count = self.read(COUNT)
        if count != b'\x0a':
            raise ValueError(f'Expected 10 bands, received {count.hex()}')
        gain = self.read(GAIN)
        if len(gain) != 2:
            raise ValueError('Invalid global gain response')
        preamp = struct.unpack('>h', gain)[0]/10
        scaled(preamp, 10, -12, 12, 'preamp_db')
        result = {'slot': next((k for k, v in SLOTS.items() if v == number), str(number)),
                  'preamp_db': preamp,
                  'bands': [decode_band(self.read(BAND, bytes([i]), i), i) for i in range(10)]}
        if self.active() != number:
            raise RuntimeError('Preset changed during read; close other controllers')
        return result

    def snapshot(self, slots):
        previous = self.active()
        presets = []
        try:
            for slot in slots:
                self.select(SLOTS[slot])
                presets.append(self.current())
        finally:
            self.select(previous)
        return {'schema': 1, 'captured_at': datetime.now(timezone.utc).isoformat(),
                'usb_bcdDevice': hex(self.info['release_number']),
                'active_preset_before': previous, 'presets': presets}

    def write_preset(self, preset):
        number = SLOTS[preset['slot']]
        self.select(number)
        # Set attenuation first; preserve screenshot values without Q conversion.
        gain = scaled(preset['preamp_db'], 10, -12, 12, 'preamp_db')
        self.send(GAIN, struct.pack('>h', gain), write=True)
        for i, band in enumerate(preset['bands']):
            self.send(BAND, band_payload(i, band), write=True)
        compare(preset, self.current())
        self.send(SAVE, bytes([number]), write=True)
        time.sleep(1)
        # Loading a different user slot and loading this one again tests saved
        # preset state, not just the values in the current editing buffer.
        other = next(value for value in SLOTS.values() if value != number)
        self.select(other)
        self.select(number)
        compare(preset, self.current())


def compare(expected, actual):
    for field in ('slot', 'preamp_db', 'bands'):
        if actual[field] != expected[field]:
            raise ValueError(f"{expected['slot']}: readback mismatch in {field}; no success claimed")


def write_json(path, document):
    # No overwrite: this must complete before changing preset parameters.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('validate', help='Validate preset file without USB access')
    check.add_argument('file', type=Path)
    commands.add_parser('show', help='Read currently active preset without changing it')
    read = commands.add_parser('read', help='Read slots, temporarily selecting each; restore active slot')
    read.add_argument('--slots', nargs='+', choices=SLOTS, default=list(SLOTS))
    read.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser('verify', help='Compare saved slots with a file, without rewriting them')
    verify.add_argument('file', type=Path)
    apply = commands.add_parser('apply', help='Back up, write and read back the named USER slots')
    apply.add_argument('file', type=Path)
    apply.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    document = None
    if hasattr(args, 'file'):
        document = json.loads(args.file.read_text())
        presets = validate_document(document)  # Validate everything before opening USB.
    if args.command == 'validate':
        print(json.dumps({'valid': True, 'slots': [p['slot'] for p in presets]}))
        return
    if hasattr(args, 'output') and args.output.exists():
        raise ValueError('Output already exists')
    if hasattr(args, 'backup') and args.backup.exists():
        raise ValueError('Backup already exists')
    device = KA17()
    try:
        if args.command == 'show':
            print(json.dumps(device.current(), indent=2))
        elif args.command == 'read':
            write_json(args.output, device.snapshot(args.slots))
            print(f'Saved {args.output}')
        elif args.command == 'verify':
            actual = device.snapshot([p['slot'] for p in presets])
            for expected, result in zip(presets, actual['presets']):
                compare(expected, result)
            print(json.dumps({'verified': [p['slot'] for p in presets],
                              'readback': actual}, indent=2))
        elif args.command == 'apply':
            if device.info['release_number'] != 0x0227:
                raise ValueError('Writing is qualified only on custom 2.27 (USB 0x0227)')
            backup = device.snapshot([p['slot'] for p in presets])
            write_json(args.backup, backup)
            previous = backup['active_preset_before']
            try:
                for preset in presets:
                    device.write_preset(preset)
                    print(f"{preset['slot']}: saved and read back", file=sys.stderr)
            finally:
                device.select(previous)
            print(json.dumps({'saved_and_verified': [p['slot'] for p in presets],
                              'backup': str(args.backup), 'restored_active_preset': previous}))
    finally:
        device.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, KeyError, ImportError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
