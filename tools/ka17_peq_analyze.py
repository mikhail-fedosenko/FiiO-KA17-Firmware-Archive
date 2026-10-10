#!/usr/bin/env python3
"""Read-only, offline analysis of KA17 V2.25. Requires capstone==5.0.9.

No USB access, firmware writes, or patch generation. The partial interpreter
executes the extracted peak and shelf coefficient arithmetic, replacing math
library calls with host math. It is NOT an XMOS emulator or hardware verification.

Offsets are for the SHA-256-pinned archive file. XS3 encoding/dual issue reference:
https://www.xmos.com/documentation/XM-014007-PS/pdf/XM-014007-PS-xs3-arch-inst-2.1.0.pdf

Finding (peak filters only): Q_RBJ = Q_device / 10**(abs(gain_db)/40).
The caller divides the encoded Q by 100 at 0x81334..0x8133c, passes it to
the dispatcher at 0x80704, and filter type 0 calls the peak routine 0x82308
without the gain-dependent conversion. Addresses refer to image 3, tile 1.
Images 6 and 7 contain the same peak arithmetic after relocation normalization.
This does not establish the active image on a connected device.
Peak routine file offsets: image 3=0x42a18, image 6=0xa6c70,
image 7=0xbeeb8. The dispatcher skips generic coefficient stores for type 0
at 0x80f90, retaining the coefficients written by the dedicated peak routine.

Shelf types 1 (low) and 2 (high) use the RBJ Q convention directly, with
alpha=sin(w)/(2*Q). They do not use the shelf-slope S convention. Their paths
start at 0x80834 and 0x80aa4; shared normalization ends at 0x81040.
Reference: https://www.w3.org/TR/audio-eq-cookbook/
"""

import argparse
import cmath
import hashlib
import json
import math
from pathlib import Path
import re
import struct

import capstone
from ka17_xs3_lanes import require_stack_memory_lane


SHA256 = "2006917650ccb6207e9be52a3202f24d727c293b5e3f3c10f4ad044231ee8213"
ROOT = Path(__file__).resolve().parents[1]
BASE = 0x80000
PEAK = 0x82308
FLOAT_END = 0x82488
SWAP = bytes((i >> 4) | ((i & 15) << 4) for i in range(256))
MD = capstone.Cs(capstone.CS_ARCH_XCORE, 0)
# XS3 instructions missing from Capstone's older XCore decoder. The operand
# encoding is the same l3r/l2rus format as XOR; reuse its register decoding.
XS3 = {
    0xB7ED: "fmul", 0xB7EE: "fadd", 0xB7EF: "fsub",
    0xBFEE: "fgt", 0xBFEF: "flt", 0xC7ED: "fun", 0xC7EE: "feq",
    0xF7EC: "stdsp", 0xEFEC: "lddsp",
}


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def floating(value):
    return struct.unpack("<f", struct.pack("<I", value))[0]


def decode(data, offset):
    h = struct.unpack_from("<H", data, offset)[0]
    if h == 0x17FF:
        return 2, "nop", ""
    if h & 0xFFC0 == 0x7F80:
        return 2, "dualentsp", str(h & 63)
    if h & 0xF800 == 0xF800 and offset + 4 <= len(data):
        second = struct.unpack_from("<H", data, offset + 2)[0]
        if second in XS3:
            proxy = next(MD.disasm(struct.pack("<HH", h, 0x0FEC), 0))
            operands = proxy.op_str
            if XS3[second] in ("stdsp", "lddsp"):
                left, immediate = operands.rsplit("r", 1)
                operands = left + immediate
            return 4, XS3[second], operands
    instruction = next(MD.disasm(data[offset:offset + 4], BASE + offset), None)
    if instruction is None:
        raise ValueError(f"Unsupported opcode at {BASE + offset:#x}: {h:04x}")
    return instruction.size, instruction.mnemonic, instruction.op_str


def load_images(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Unrecognized firmware: offsets are pinned to V2.25 SHA-256")
    decoded = raw.translate(SWAP)
    assert decoded.translate(SWAP) == raw
    images = []
    for start in range(0, len(decoded) - 0x74, 0x1000):
        if u32(decoded, start) != 0x00FF51DE:
            continue
        size = u32(decoded, start + 0x10)
        assert start + size <= len(decoded)
        assert u32(decoded, start + 0x18) == size
        assert u32(decoded, start + 0x1C) == 2
        first = u32(decoded, start + 0x3C)
        second = u32(decoded, start + 0x58)
        length0 = u32(decoded, start + 0x44) * 4
        length1 = u32(decoded, start + 0x60) * 4
        assert first + length0 == second
        assert second + length1 == size
        images.append({"id": u32(decoded, start + 0x14), "offset": start,
                       "size": size, "tile0_offset": start + first,
                       "tile0_size": length0, "tile1_offset": start + second,
                       "tile1_size": length1,
                       "tile1": decoded[start + second:start + second + length1]})
    assert [i["id"] for i in images] == [1, 3, 5, 6, 7]
    return images


class PeakProgram:
    """Constrained interpreter for the coefficient path, not the audio engine.

    Library hook semantics are identified by static inspection and mathematical
    call-site context. Host libm is not asserted bit-identical to XMOS libm.
    Float arithmetic instructions are rounded to IEEE-754 binary32.
    """

    def __init__(self, image):
        self.image = image
        self.data = image["tile1"]
        # Startup LDAP at 0x80090 executes in single issue mode (2-byte units).
        n, mnemonic, operands = decode(self.data, 0x90)
        assert mnemonic == "ldap"
        self.cp = BASE + 0x90 + n + 2 * int(operands.split(",")[-1], 0)
        assert self.data[PEAK - BASE:PEAK - BASE + 4] == bytes.fromhex("ff178e7f")
        # Locate helpers from calls at immutable positions inside the peak routine.
        sites = {0x8232C: "fabsf", 0x82330: "f32_to_f64",
                 0x82340: "div_f64", 0x82350: "pow_f64",
                 0x82354: "f64_to_f32", 0x82368: "mul_f64",
                 0x82384: "tan_f64", 0x823A8: "div_f32"}
        self.hooks = {}
        for site, name in sites.items():
            n, mnemonic, operand = decode(self.data, site - BASE)
            assert mnemonic == "bl"
            self.hooks[site + n + 4 * int(operand, 0)] = name

    def constant(self, index):
        return u32(self.data, self.cp - BASE + 4 * index)

    def fingerprint(self, start=PEAK, end=FLOAT_END):
        """Normalize relocated CP indices and math call addresses before comparing."""
        result = []
        pc = start
        while pc < end:
            n, mnemonic, operand = decode(self.data, pc - BASE)
            if mnemonic == "bl":
                target = pc + n + 4 * int(operand, 0)
                operand = self.hooks[target]
            match = re.search(r"cp\[(.*?)\]", operand)
            if match:
                operand = operand[:match.start()] + f"constant({self.constant(int(match[1], 0)):#x})"
            result.append((mnemonic, operand))
            pc += n
        return hashlib.sha256(repr(result).encode()).hexdigest()

    def run(self, gain, frequency, q, fs=48000, trace=False):
        registers = {f"r{i}": 0 for i in range(12)}
        registers.update(r0=bits(gain), r1=bits(frequency), r2=bits(q), r3=bits(fs), sp=0x200000)
        memory = {0x200008: 0x210000, 0x20000C: 20}
        registers, memory, events = self.execute(registers, memory, PEAK, FLOAT_END, trace)
        # Before fixed-point conversion: stack[4]=b0, r8=b1=a1,
        # r0=b2, stack[3]=a2. Subsequent stores negate feedback coefficients.
        b0 = floating(memory[registers["sp"] + 16])
        b1 = floating(registers["r8"])
        b2 = floating(registers["r0"])
        a2 = floating(memory[registers["sp"] + 12])
        return (b0, b1, b2, 1.0, b1, a2), events

    def execute(self, registers, memory, start, end, trace=False):
        pc = start
        events = []

        def f64(regs, start):
            return struct.unpack("<d", struct.pack("<II", regs[f"r{start}"], regs[f"r{start+1}"]))[0]

        def memory_address(arg, old):
            match = re.fullmatch(r"(\w+)\[(.*?)\]", arg)
            if not match:
                raise ValueError(arg)
            base, index = match.groups()
            index = old[index] if index in old else int(index, 0)
            return (self.cp if base == "cp" else old[base]) + index * 4

        steps = 0
        while pc != end:
            steps += 1
            assert steps < 2000, f"Unexpected loop at {pc:#x}"
            # An arithmetic model must not silently execute the known-bad
            # short stack-memory bundles from the first experimental release.
            require_stack_memory_lane(self.data[pc-BASE:pc-BASE+4], pc)
            # XS3 dual issue: both halfwords read the OLD register state.
            old = registers.copy()
            updates = {}
            stores = {}
            next_pc = pc + 4
            instructions = [decode(self.data, pc - BASE)]
            if instructions[0][0] == 2:
                instructions.append(decode(self.data, pc - BASE + 2))
                assert instructions[1][0] == 2
            pos = pc
            for n, mnemonic, operand in instructions:
                args = operand.split(", ") if operand else []

                def value(arg):
                    return old[arg] if arg in old else int(arg, 0)

                if mnemonic == "nop":
                    pass
                elif mnemonic == "dualentsp":
                    updates["sp"] = old["sp"] - int(operand) * 4
                elif mnemonic == "add":
                    updates[args[0]] = (value(args[1]) + value(args[2])) & 0xFFFFFFFF
                elif mnemonic == "ldc":
                    updates[args[0]] = int(args[1], 0)
                elif mnemonic in ("lsu", "eq"):
                    x, y = value(args[1]), value(args[2])
                    updates[args[0]] = int(x < y if mnemonic == "lsu" else x == y)
                elif mnemonic == "ldw":
                    address = memory_address(args[1], old)
                    updates[args[0]] = u32(self.data, address - BASE) if args[1].startswith("cp[") else memory[address]
                elif mnemonic == "stw":
                    stores[memory_address(args[1], old)] = value(args[0])
                elif mnemonic in ("stdsp", "lddsp"):
                    address = old["sp"] + int(args[2], 0) * 8
                    for register, addr in [(args[0], address), (args[1], address + 4)]:
                        if mnemonic == "stdsp":
                            stores[addr] = old[register]
                        else:
                            updates[register] = memory[addr]
                elif mnemonic in ("fmul", "fadd", "fsub", "flt", "fgt", "fun", "feq"):
                    x, y = floating(value(args[1])), floating(value(args[2]))
                    if mnemonic == "fmul": result = bits(x * y)
                    elif mnemonic == "fadd": result = bits(x + y)
                    elif mnemonic == "fsub": result = bits(x - y)
                    elif mnemonic == "flt": result = int(x < y)
                    elif mnemonic == "fgt": result = int(x > y)
                    elif mnemonic == "feq": result = int(x == y)
                    else: result = int(math.isnan(x) or math.isnan(y))
                    updates[args[0]] = result
                elif mnemonic == "or":
                    updates[args[0]] = value(args[1]) | value(args[2])
                elif mnemonic == "bru":
                    next_pc = pc + 4 + value(args[0]) * 4
                elif mnemonic in ("bf", "bt", "bu"):
                    if mnemonic == "bu" or (value(args[0]) != 0) == (mnemonic == "bt"):
                        next_pc = pc + 4 + int(args[-1], 0) * 4
                elif mnemonic == "bl":
                    target = pc + 4 + int(operand, 0) * 4
                    name = self.hooks[target]
                    x, y = f64(old, 0), f64(old, 2)
                    if name == "fabsf": out = bits(abs(floating(old["r0"]))); double = False
                    elif name == "f32_to_f64": out = floating(old["r0"]); double = True
                    elif name == "f64_to_f32": out = bits(x); double = False
                    elif name == "div_f64": out = x / y; double = True
                    elif name == "mul_f64": out = x * y; double = True
                    elif name == "pow_f64": out = math.pow(x, y); double = True
                    elif name == "tan_f64": out = math.tan(x); double = True
                    elif name == "exp_f64": out = math.exp(x); double = True
                    elif name == "sin_f64": out = math.sin(x); double = True
                    elif name == "cos_f64": out = math.cos(x); double = True
                    elif name == "sqrt_f64": out = math.sqrt(x); double = True
                    elif name == "add_f64": out = x + y; double = True
                    elif name == "sub_f64": out = x - y; double = True
                    elif name == "compare_f64":
                        out = (1 if math.isnan(x) or math.isnan(y) else (x > y) - (x < y)) & 0xFFFFFFFF
                        double = False
                    elif name == "unordered_f64":
                        out = int(math.isnan(x) or math.isnan(y)); double = False
                    elif name == "div_f32": out = bits(floating(old["r0"]) / floating(old["r1"])); double = False
                    else: raise AssertionError(name)
                    if double:
                        updates["r0"], updates["r1"] = struct.unpack("<II", struct.pack("<d", out))
                    else:
                        updates["r0"] = out
                    if trace:
                        events.append({"address": hex(pc), "helper": name,
                                       "result": out if double or name in ("compare_f64", "unordered_f64") else floating(out)})
                else:
                    raise ValueError(f"Unsupported executed instruction {pos:#x}: {mnemonic} {operand}")
                pos += n
            registers.update(updates)
            memory.update(stores)
            pc = next_pc
        return registers, memory, events


class ShelfProgram(PeakProgram):
    def __init__(self, image):
        super().__init__(image)
        sites = {0x80760: "exp_f64", 0x8079C: "sin_f64",
                 0x80848: "add_f64", 0x8087C: "cos_f64",
                 0x808A0: "sqrt_f64", 0x80974: "sub_f64",
                 0x80FA0: "compare_f64", 0x80FB0: "unordered_f64",
                 0x80830: "peak_path_not_executed"}
        for site, name in sites.items():
            n, mnemonic, operand = decode(self.data, site - BASE)
            assert mnemonic == "bl"
            self.hooks[site + n + 4 * int(operand, 0)] = name

    def fingerprint(self):
        # Include dispatcher, both shelves and normalization, excluding unrelated
        # filters and fixed-point conversion. Branch operands remain unchanged.
        normalize = super().fingerprint
        parts = [normalize(a, b) for a, b in
                 ((0x80704, 0x80D2C), (0x80F88, 0x81040))]
        return hashlib.sha256(repr(parts).encode()).hexdigest()

    def run(self, kind, gain, frequency, q, fs=48000, trace=False):
        assert kind in ("low", "high")
        assert 0 < frequency < fs / 2 and q > 0
        registers = {f"r{i}": 0 for i in range(12)}
        registers.update(r0=1 if kind == "low" else 2, r1=bits(gain),
                         r2=bits(frequency), r3=bits(q), sp=0x200000)
        memory = {0x200004: bits(fs), 0x200008: 0x210000,
                  0x20000C: 0x210000, 0x200010: 20}
        registers, memory, events = self.execute(registers, memory, 0x80704, 0x81040, trace)

        def double(low, high):
            return struct.unpack("<d", struct.pack("<II", low, high))[0]

        def stack(low, high):
            return double(memory[registers["sp"] + 4*low], memory[registers["sp"] + 4*high])

        # At 0x81040, all five values have been divided by a0 in firmware.
        # The subsequent DSP array is ordered b2,b1,b0,-a1,-a2, not b0 first.
        return (stack(0x17, 0x16), stack(0x19, 0x18),
                double(registers["r11"], registers["r6"]), 1.0,
                double(registers["r7"], memory[registers["sp"] + 4*0x15]),
                stack(0x14, 0x13)), events


def rbj_shelf(kind, gain, frequency, q, fs):
    """Independent cookbook reference, using Q rather than shelf slope S."""
    a = 10 ** (gain / 40)
    w = 2 * math.pi * frequency / fs
    c = math.cos(w)
    beta = math.sqrt(a) * math.sin(w) / q
    if kind == "low":
        raw = (a*((a+1)-(a-1)*c+beta), 2*a*((a-1)-(a+1)*c),
               a*((a+1)-(a-1)*c-beta), (a+1)+(a-1)*c+beta,
               -2*((a-1)+(a+1)*c), (a+1)+(a-1)*c-beta)
    else:
        assert kind == "high"
        raw = (a*((a+1)+(a-1)*c+beta), -2*a*((a-1)+(a+1)*c),
               a*((a+1)+(a-1)*c-beta), (a+1)-(a-1)*c+beta,
               2*((a-1)-(a+1)*c), (a+1)-(a-1)*c-beta)
    return tuple(x / raw[3] for x in raw)


def recovered_peak(gain, frequency, q, fs):
    """Algebra recovered from the instructions; no device communication."""
    v = 10 ** (abs(gain) / 20)
    k = math.tan(math.pi * frequency / fs)
    numerator = v if gain >= 0 else 1
    denominator = 1 if gain >= 0 else v
    norm = 1 / (1 + denominator * k / q + k * k)
    return ((1 + numerator * k / q + k*k) * norm, 2*(k*k-1)*norm,
            (1 - numerator * k / q + k*k) * norm, 1.0, 2*(k*k-1)*norm,
            (1 - denominator * k / q + k*k) * norm)


def rbj_peak(gain, frequency, q, fs):
    a = 10 ** (gain / 40)
    w = 2 * math.pi * frequency / fs
    alpha = math.sin(w) / (2*q)
    c = math.cos(w)
    norm = 1 + alpha/a
    return ((1+alpha*a)/norm, -2*c/norm, (1-alpha*a)/norm,
            1.0, -2*c/norm, (1-alpha/a)/norm)


def response(coeffs, frequency, fs):
    z = cmath.exp(-2j * math.pi * frequency / fs)
    b0, b1, b2, a0, a1, a2 = coeffs
    return 20 * math.log10(abs((b0+b1*z+b2*z*z)/(a0+a1*z+a2*z*z)))


def verify(images):
    programs = [PeakProgram(i) for i in images if i["id"] in (3, 6, 7)]
    fingerprints = {p.fingerprint() for p in programs}
    assert len(fingerprints) == 1, "Peak routines differ after relocation normalization"
    cases = 0
    max_machine_error = max_identity_error = max_compensated_error = 0.0
    for program in programs:
        for fs in (44100, 48000, 96000, 192000):
            for frequency in (100, 1000, 10000):
                for q in (0.3, 0.707, 1, 2, 5, 10):
                    for gain in (-12, -6, -3, 0, 3, 6, 12):
                        actual, _ = program.run(gain, frequency, q, fs)
                        model = recovered_peak(gain, frequency, q, fs)
                        expected = rbj_peak(gain, frequency, q / 10**(abs(gain)/40), fs)
                        machine_error = max(abs(a-b) for a, b in zip(actual, model))
                        identity_error = max(abs(a-b) for a, b in zip(model, expected))
                        max_machine_error = max(max_machine_error, machine_error)
                        max_identity_error = max(max_identity_error, identity_error)
                        assert machine_error < 2e-6, (program.image["id"], gain, frequency, q, fs, machine_error)
                        assert identity_error < 1e-12, (gain, frequency, q, fs, identity_error)
                        compensated, _ = program.run(gain, frequency, q * 10**(abs(gain)/40), fs)
                        target = rbj_peak(gain, frequency, q, fs)
                        compensated_error = max(abs(a-b) for a,b in zip(compensated, target))
                        max_compensated_error = max(max_compensated_error, compensated_error)
                        assert compensated_error < 2e-6, (gain, frequency, q, fs, compensated_error)
                        cases += 1
    sample, trace = programs[0].run(6, 1000, 1, trace=True)
    # Observable mismatch at a shoulder, not just equal center-frequency gain.
    expected_same_q = rbj_peak(6, 1000, 1, 48000)
    assert response(sample, 500, 48000) - response(expected_same_q, 500, 48000) > 0.9
    return {"cases": cases, "normalized_peak_sha256": fingerprints.pop(),
            "max_machine_vs_formula_coefficient_error": max_machine_error,
            "max_formula_vs_adjusted_RBJ_coefficient_error": max_identity_error,
            "max_compensated_vs_target_RBJ_coefficient_error": max_compensated_error,
            "compensation_note": "Algebra check only; device Q limits and 0.01 quantization are not applied",
            "example": {"gain": 6, "frequency": 1000, "q": 1, "fs": 48000,
                        "effective_rbj_q": 10**(-6/40),
                        "firmware_500hz_db": response(sample, 500, 48000),
                        "rbj_same_q_500hz_db": response(expected_same_q,500,48000),
                        "math_hook_trace": trace}}


def verify_shelves(images):
    programs = [ShelfProgram(i) for i in images if i["id"] in (3, 6, 7)]
    fingerprints = {p.fingerprint() for p in programs}
    assert len(fingerprints) == 1, "Shelf paths differ after relocation normalization"
    cases = 0
    max_error = max_rounded_error = max_response_error = max_inverse_error = 0.0
    max_pole_radius = 0.0
    for program in programs:
        for kind in ("low", "high"):
            for fs in (44100, 48000, 96000, 192000):
                for frequency in (20, 100, 1000, 10000, 20000):
                    for q in (0.3, 0.5, 0.707, 1, 2, 5, 10):
                        for gain in (-12, -6, -3, 0, 3, 6, 12):
                            actual, _ = program.run(kind, gain, frequency, q, fs)
                            expected = rbj_shelf(kind, gain, frequency, q, fs)
                            # The firmware divides binary32 gain by 40 BEFORE
                            # conversion to double. Account for this independently
                            # to distinguish rounding from an algebraic mismatch.
                            effective_gain = 40 * floating(bits(floating(bits(gain)) / 40))
                            rounded = rbj_shelf(kind, effective_gain, frequency,
                                                floating(bits(q)), fs)
                            error = max(abs(a-b) for a, b in zip(actual, expected))
                            rounded_error = max(abs(a-b) for a, b in zip(actual, rounded))
                            assert error < 1e-6, (kind, gain, frequency, q, fs, error)
                            assert rounded_error < 2e-14, (kind, gain, frequency, q, fs, rounded_error)
                            max_error = max(max_error, error)
                            max_rounded_error = max(max_rounded_error, rounded_error)
                            inverse, _ = program.run(kind, -gain, frequency, q, fs)
                            probes = (0, frequency/2, frequency, min(frequency*2, fs/2), fs/2)
                            for probe in probes:
                                measured = response(actual, probe, fs)
                                response_error = abs(measured - response(expected, probe, fs))
                                inverse_error = abs(measured + response(inverse, probe, fs))
                                max_response_error = max(max_response_error, response_error)
                                max_inverse_error = max(max_inverse_error, inverse_error)
                                assert response_error < 1e-5, (kind, gain, frequency, q, fs, probe, response_error)
                                assert inverse_error < 1e-5, (kind, gain, frequency, q, fs, probe, inverse_error)
                            assert abs(response(actual, frequency, fs) - gain/2) < 1e-5
                            assert abs(response(actual, 0, fs) - (gain if kind == "low" else 0)) < 1e-5
                            assert abs(response(actual, fs/2, fs) - (gain if kind == "high" else 0)) < 1e-5
                            a1, a2 = actual[4:]
                            discriminant = cmath.sqrt(a1*a1 - 4*a2)
                            radius = max(abs((-a1+discriminant)/2), abs((-a1-discriminant)/2))
                            assert radius < 1.0, (kind, gain, frequency, q, fs, radius)
                            max_pole_radius = max(max_pole_radius, radius)
                            cases += 1
    return {"cases": cases, "normalized_shelf_sha256": fingerprints.pop(),
            "parameter_grid": {"types": ["low", "high"], "images": [3, 6, 7],
                               "fs": [44100, 48000, 96000, 192000],
                               "frequency": [20, 100, 1000, 10000, 20000],
                               "q": [0.3, 0.5, 0.707, 1, 2, 5, 10],
                               "gain_db": [-12, -6, -3, 0, 3, 6, 12]},
            "max_machine_vs_RBJ_coefficient_error": max_error,
            "max_machine_vs_input_rounded_RBJ_coefficient_error": max_rounded_error,
            "max_probe_response_error_db": max_response_error,
            "max_boost_cut_cascade_error_db": max_inverse_error,
            "max_pole_radius": max_pole_radius,
            "q_convention": "RBJ Q directly; not slope S; no peak gain compensation",
            "scope": "Interpreted coefficient instructions through normalization; host math hooks; before fixed-point conversion and DSP processing"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path)
    disassembly = parser.add_mutually_exclusive_group()
    disassembly.add_argument("--disassemble-peak", type=int, choices=(3,6,7))
    disassembly.add_argument("--disassemble-shelves", type=int, choices=(3,6,7))
    args = parser.parse_args()
    path = args.firmware or next((ROOT / "KA17 V2.25 Firmware").rglob("Fiio_KA17_xmos_dfu_V225.bin"))
    images = load_images(path)
    if args.disassemble_peak or args.disassemble_shelves:
        image_id = args.disassemble_peak or args.disassemble_shelves
        program_type = PeakProgram if args.disassemble_peak else ShelfProgram
        program = program_type(next(i for i in images if i["id"] == image_id))
        pc, end = (PEAK, FLOAT_END) if args.disassemble_peak else (0x80704, 0x81040)
        while pc < end:
            n, mnemonic, operand = decode(program.data, pc-BASE)
            annotation = ""
            if mnemonic == "bl":
                target = pc+n+4*int(operand,0)
                annotation = f" ; {target:#x} {program.hooks[target]} [host-math hook]"
            print(f"{pc:08x} {program.data[pc-BASE:pc-BASE+n].hex():10} {mnemonic:12} {operand}{annotation}")
            pc += n
    else:
        print(json.dumps({"firmware_sha256": SHA256,
                          "images": [{k: (hex(v) if "offset" in k else v) for k,v in i.items() if k != "tile1"} for i in images],
                          "verification": verify(images),
                          "shelf_verification": verify_shelves(images)}, indent=2))


if __name__ == "__main__":
    main()
