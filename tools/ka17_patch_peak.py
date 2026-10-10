#!/usr/bin/env python3
"""Build an EXPERIMENTAL offline KA17 V2.25 peak-Q patch. Never accesses USB.

Requires ka17_peq_analyze.py and capstone==5.0.9. Input is SHA-256 pinned.
Output is a separate candidate binary, reversible byte manifest, and assembly.
No claim of hardware validation, secure-boot acceptance, or safe installation.

The replacement uses signed gain and RBJ peaking coefficients in tan form:
 A=10^(G/40), K=tan(pi*f/Fs), t=K/Q, C=1+K*K, N=1/(C+t/A)
 b0=(C+t*A)*N, b1=a1=2*(K*K-1)*N,
 b2=(C-t*A)*N, a2=(C-t/A)*N.
Preserves the original entry, stack frame, coefficient locations and epilogue.

CRC convention verified against every image/tile in the pinned stock file:
 XS3 CRC32 recurrence, init 0xffffffff, trailing zero word, complement.
 Header+4: CRC over [12:256]. Header+8: CRC over [12:image_size].
 Tile trailer: CRC over uint32_le(payload_words) followed by payload.
ISA: https://www.xmos.com/documentation/XM-014007-PS/pdf/XM-014007-PS-xs3-arch-inst-2.1.0.pdf
"""
import argparse
import cmath
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib

import ka17_peq_analyze as k
from ka17_xs3_lanes import require_stack_memory_lane

START, END = 0x8232C, k.FLOAT_END


def crc(data):
    if len(data) % 4:
        raise ValueError('CRC input must be word aligned')
    state = 0xFFFFFFFF
    for word, in struct.iter_unpack('<I', bytes(data) + bytes(4)):
        state = (zlib.crc32(bytes(4), state ^ 0xFFFFFFFF) ^ 0xFFFFFFFF) ^ word
    return state ^ 0xFFFFFFFF


def checksums(decoded, images, update=False):
    checked = []
    for im in images:
        base = im['offset']
        entries = []
        for tile in (0, 1):
            offset, size = im[f'tile{tile}_offset'], im[f'tile{tile}_size']
            value = crc(struct.pack('<I', size//4-1) + decoded[offset:offset+size-4])
            entries.append((offset+size-4, value, f'tile{tile}'))
        # Update the trailers before calculating the image CRC.
        for offset, value, name in entries:
            if update: struct.pack_into('<I', decoded, offset, value)
            else: assert k.u32(decoded, offset) == value, (im['id'], name)
        entries = [(base+4, crc(decoded[base+12:base+256]), 'first_page'),
                   (base+8, crc(decoded[base+12:base+im['size']]), 'whole_image')]
        for offset, value, name in entries:
            if update: struct.pack_into('<I', decoded, offset, value)
            else: assert k.u32(decoded, offset) == value, (im['id'], name)
        checked.append(im['id'])
    return checked


class Assembler:
    """Only encodes the small instruction subset used by this replacement.

    Every encoding is round-trip checked with the analysis decoder. Each short
    instruction occupies its own dual-issue bundle paired with a NOP, avoiding
    register dependencies within a bundle. Existing helpers supply all calls.
    """
    def __init__(self, program):
        self.program = program
        self.data = bytearray()
        self.listing = []
        self.short = {}
        for halfword in range(65536):
            raw = struct.pack('<H', halfword)
            ins = next(k.MD.disasm(raw, 0), None)
            if ins and ins.size == 2 and ins.mnemonic in ('add', 'ldc', 'ldw', 'stw'):
                self.short[(ins.mnemonic, ins.op_str)] = raw
        self.float_operands = {}
        for halfword in range(0xF800, 0x10000):
            ins = next(k.MD.disasm(struct.pack('<HH', halfword, 0x0FEC), 0), None)
            if ins and ins.mnemonic == 'xor': self.float_operands[ins.op_str] = halfword

    def emit(self, mnemonic, operands='', raw=None):
        if raw is None:
            if mnemonic in ('fadd', 'fsub', 'fmul'):
                opcode = {'fadd': 0xB7EE, 'fsub': 0xB7EF, 'fmul': 0xB7ED}[mnemonic]
                raw = struct.pack('<HH', self.float_operands[operands], opcode)
            elif mnemonic == 'nop': raw = bytes.fromhex('ff17')
            else: raw = self.short[(mnemonic, operands)]
        n, decoded_mnemonic, decoded_operands = k.decode(raw, 0)
        assert (n, decoded_mnemonic, decoded_operands) == (len(raw), mnemonic, operands)
        pc = START + len(self.data)
        if len(raw) == 2:
            nop = bytes.fromhex('ff17')
            # XS3 section 5.2: low halfword = resource lane; high halfword
            # = memory lane. A NOP partner alone does not make a bundle legal.
            if mnemonic in ('ldw', 'stw'):
                bundle = nop + raw
                description = f'nop ; {mnemonic} {operands}'
            elif mnemonic in ('add', 'ldc', 'nop'):
                bundle = raw + nop
                description = f'{mnemonic} {operands}'.rstrip() + ' ; nop'
            else:
                raise ValueError(f'Unclassified short-instruction lane: {mnemonic}')
        else:
            bundle = raw
            description = f'{mnemonic} {operands}'.rstrip()
        require_stack_memory_lane(bundle, pc)
        self.data.extend(bundle)
        self.listing.append(f'{pc:08x} {bundle.hex()}  {description}')

    def move(self, dst, src): self.emit('add', f'{dst}, {src}, 0')

    def constant(self, dst, value):
        p = self.program
        indexes = [i for i in range((len(p.data)-(p.cp-k.BASE))//4) if p.constant(i) == value]
        assert indexes, hex(value)
        index = indexes[0]
        raw = struct.pack('<HH', 0xF000 | (index >> 6), 0x6C00 | (int(dst[1:]) << 6) | (index & 63))
        # Capstone formats small constants as decimal, larger ones as hex.
        _, mnemonic, operand = k.decode(raw, 0)
        assert mnemonic == 'ldw' and operand.startswith(dst+', cp[')
        assert int(operand.split('[')[1][:-1], 0) == index
        self.emit(mnemonic, operand, raw)

    def call(self, name):
        target = next(address for address, helper in self.program.hooks.items() if helper == name)
        pc = START + len(self.data)
        delta = target - (pc + 4)
        assert delta % 4 == 0 and 0 <= delta//4 < (1 << 20)
        immediate = delta//4
        raw = struct.pack('<HH', 0xF000 | (immediate >> 10), 0xD000 | (immediate & 1023))
        _, mnemonic, operand = k.decode(raw, 0)
        assert mnemonic == 'bl' and int(operand, 0) == immediate
        self.emit(mnemonic, operand, raw)
        self.listing[-1] += f' ; {name} -> {target:#x}'

    def build(self):
        # Original prologue already set r0=gain, r7=Q, r9=f, r8=Fs.
        self.constant('r1', k.bits(40))
        self.call('div_f32')
        self.call('f32_to_f64')
        self.move('r2', 'r0'); self.move('r3', 'r1')
        self.emit('ldc', 'r0, 0')
        self.constant('r1', 0x40240000)  # double 10, high word
        self.call('pow_f64'); self.call('f64_to_f32')
        self.emit('stw', 'r0, sp[4]')  # A
        self.move('r0', 'r9'); self.call('f32_to_f64')
        self.constant('r2', 0x54442D18); self.constant('r3', 0x400921FB)  # pi
        self.call('mul_f64')
        self.move('r9', 'r0'); self.move('r10', 'r1')
        self.move('r0', 'r8'); self.call('f32_to_f64')
        self.move('r2', 'r0'); self.move('r3', 'r1')
        self.move('r0', 'r9'); self.move('r1', 'r10')
        self.call('div_f64'); self.call('tan_f64'); self.call('f64_to_f32')
        self.move('r8', 'r0')  # K
        self.move('r1', 'r7'); self.call('div_f32')
        self.move('r7', 'r0')  # t=K/Q
        self.emit('ldw', 'r1, sp[4]'); self.call('div_f32')
        self.move('r9', 'r0')  # t/A
        self.constant('r6', k.bits(1))
        self.emit('fmul', 'r8, r8, r8')  # K squared
        self.emit('fadd', 'r10, r8, r6')  # C
        self.emit('fadd', 'r1, r10, r9')
        self.move('r0', 'r6'); self.call('div_f32')
        self.move('r6', 'r0')  # N
        self.emit('ldw', 'r0, sp[4]')
        self.emit('fmul', 'r7, r7, r0')  # t*A
        self.emit('fadd', 'r0, r10, r7'); self.emit('fmul', 'r0, r0, r6')
        self.emit('stw', 'r0, sp[4]')  # b0
        self.emit('fsub', 'r0, r10, r7'); self.emit('fmul', 'r0, r0, r6')  # b2
        self.constant('r1', k.bits(1))
        self.emit('fsub', 'r8, r8, r1'); self.emit('fadd', 'r8, r8, r8')
        self.emit('fmul', 'r8, r8, r6')  # b1=a1
        self.emit('fsub', 'r1, r10, r9'); self.emit('fmul', 'r1, r1, r6')
        self.emit('stw', 'r1, sp[3]')  # a2
        used = len(self.data)
        assert used <= END-START
        while len(self.data) < END-START: self.emit('nop')
        return bytes(self.data), '\n'.join(self.listing)+'\n', used


def verify_program(program):
    cases, worst = 0, 0.0
    worst_center = {'error_db': 0.0}
    typical_error = 0.0
    max_pole_radius = 0.0
    for fs in (44100, 48000, 96000, 192000):
        for frequency in (20, 100, 1000, 10000, 20000):
            for q in (0.3, 0.5, 0.707, 1, 2, 5, 10):
                for gain in (-12, -6, -3, 0, 3, 6, 12):
                    actual, _ = program.run(gain, frequency, q, fs)
                    expected = k.rbj_peak(gain, frequency, q, fs)
                    error = max(abs(a-b) for a,b in zip(actual, expected))
                    assert error < 2e-6, (program.image['id'],gain,frequency,q,fs,error)
                    assert all(math.isfinite(x) for x in actual)
                    a1, a2 = actual[4:]
                    discriminant = cmath.sqrt(a1*a1-4*a2)
                    radius = max(abs((-a1+discriminant)/2), abs((-a1-discriminant)/2))
                    assert radius < 1, (gain,frequency,q,fs,radius)
                    max_pole_radius = max(max_pole_radius, radius)
                    center_db = k.response(actual, frequency, fs)
                    center_error = abs(center_db-gain)
                    if center_error > worst_center['error_db']:
                        worst_center = {'error_db':center_error, 'gain_db':gain,
                                        'frequency':frequency, 'q':q, 'fs':fs,
                                        'actual_center_db':center_db}
                    # Coefficient agreement alone does not guarantee response
                    # accuracy in low-frequency, high-Q float32 filters.
                    # Bound a separately stated subset and retain the worst
                    # full-grid center error rather than hiding it.
                    if fs <= 48000 and frequency >= 100:
                        for probe in (frequency/2,frequency,min(frequency*2,fs/2)):
                            response_error = abs(k.response(actual,probe,fs)-k.response(expected,probe,fs))
                            assert response_error < 0.02, (gain,frequency,q,fs,probe,response_error)
                            typical_error = max(typical_error,response_error)
                    worst = max(worst, error); cases += 1
    return {'cases': cases, 'max_coefficient_error': worst,
            'max_pole_radius':max_pole_radius,
            'response_subset':'44.1/48 kHz, F0>=100 Hz on the test grid, probes F0/2,F0,min(2*F0,Fs/2); before fixed-point conversion',
            'max_response_subset_error_db':typical_error,
            'worst_full_grid_center_error':worst_center}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=k.ROOT/'patches'/'v225-peak-q-candidate')
    parser.add_argument('--check-stock', action='store_true', help='Run the RBJ regression on stock: expected to fail')
    parser.add_argument('--verify-candidate', type=Path, help='Read and validate an existing candidate; write nothing')
    args = parser.parse_args()
    path = next((k.ROOT/'KA17 V2.25 Firmware').rglob('Fiio_KA17_xmos_dfu_V225.bin'))
    images = k.load_images(path)  # requires exact input SHA-256
    if args.check_stock:
        verify_program(k.PeakProgram(next(i for i in images if i['id']==3)))
        raise AssertionError('Stock unexpectedly passed the regression')
    original = path.read_bytes()
    if args.verify_candidate:
        saved = args.verify_candidate.read_bytes().translate(k.SWAP)
        if len(saved) != len(original):
            raise ValueError('Unexpected candidate size')
        for im in images:
            if im['id'] in (3, 6, 7):
                a = im['tile1_offset']+START-k.BASE
                require_stack_memory_lane(saved[a:a+END-START], START)
    decoded = bytearray(original.translate(k.SWAP))
    checksums(decoded, images)
    results, listings = [], {}
    allowed = set()
    for im in images:
        if im['id'] not in (3,6,7): continue
        program = k.PeakProgram(im)
        replacement, listing, used = Assembler(program).build()
        start = im['tile1_offset'] + START-k.BASE
        decoded[start:start+len(replacement)] = replacement
        allowed.update(range(start, start+len(replacement)))
        allowed.update(range(im['offset']+8, im['offset']+12))
        end = im['tile1_offset']+im['tile1_size']
        allowed.update(range(end-4, end))
        program.data = bytes(decoded[im['tile1_offset']:end])
        result = verify_program(program)
        stock = k.PeakProgram(im)
        stock_sample, _ = stock.run(6,1000,1)
        patched_sample, _ = program.run(6,1000,1)
        result.update(image=im['id'], file_offset=hex(start), bytes_reserved=len(replacement), bytes_used=used,
                      stock_500hz_db=k.response(stock_sample,500,48000),
                      patched_500hz_db=k.response(patched_sample,500,48000),
                      target_500hz_db=k.response(k.rbj_peak(6,1000,1,48000),500,48000))
        # The entire shelf dispatcher/normalization, entry and epilogue are exact copies.
        assert program.data[:START-k.BASE] == im['tile1'][:START-k.BASE]
        assert program.data[END-k.BASE:] == im['tile1'][END-k.BASE:]
        results.append(result); listings[im['id']] = listing
    checksums(decoded, images, update=True)
    checksums(decoded, images)
    candidate = bytes(decoded).translate(k.SWAP)
    assert len(candidate) == len(original)
    changed = [i for i,(a,b) in enumerate(zip(original,candidate)) if a!=b]
    assert set(changed) <= allowed
    # A reversible manifest containing exact original/patched bytes, in encoded file coordinates.
    ranges = []
    for i in changed:
        if ranges and ranges[-1][1] == i: ranges[-1][1] += 1
        else: ranges.append([i,i+1])
    edits = [{'offset': hex(a), 'before': original[a:b].hex(), 'after': candidate[a:b].hex()} for a,b in ranges]
    restored = bytearray(candidate)
    for edit in edits:
        a=int(edit['offset'],16); before=bytes.fromhex(edit['before']); restored[a:a+len(before)]=before
    assert bytes(restored)==original
    manifest = {'status':'EXPERIMENTAL_OFFLINE_ONLY_NOT_HARDWARE_VALIDATED',
                'original_sha256':k.SHA256,'candidate_sha256':hashlib.sha256(candidate).hexdigest(),
                'file_size':len(candidate),'changed_bytes':len(changed),
                'crc_verified_images':[i['id'] for i in images], 'verification':results,
                'unchanged':'All bytes except peak calculation windows and three tile/image CRC pairs; shelf code, MCU image, image sizes, prologues and epilogues unchanged',
                'limitations':['Host math hooks; not bit-exact XMOS libm emulation',
                               'Short stack-memory lane check only; not full ISA validation',
                               'Fixed-point conversion and audio DSP execution not tested',
                               'Float32 response error remains large at low F0/high Q/high Fs; see worst_full_grid_center_error. NOT a general response-accuracy fix.',
                               'No boot/DFU/signature acceptance or acoustic validation',
                               'Image 1 not modified; active mode-to-image mapping not established'],
                'edits':edits}
    # Refuse to overwrite an existing build; no updater invocation is provided.
    if args.verify_candidate:
        actual_file = args.verify_candidate.read_bytes()
        assert actual_file == candidate, 'Candidate does not match the reproducible patch'
        checksums(actual_file.translate(k.SWAP), images)
        print(json.dumps({'verified_candidate':str(args.verify_candidate),
                          'candidate_sha256':manifest['candidate_sha256'],
                          'verification':results},indent=2))
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir/'Fiio_KA17_V225_PEAK_Q_EXPERIMENTAL.bin').write_bytes(candidate)
    (args.output_dir/'patch-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for image,listing in listings.items(): (args.output_dir/f'image-{image}-peak-patched.asm').write_text(listing)
    print(json.dumps({k:v for k,v in manifest.items() if k!='edits'},indent=2))


if __name__=='__main__': main()
