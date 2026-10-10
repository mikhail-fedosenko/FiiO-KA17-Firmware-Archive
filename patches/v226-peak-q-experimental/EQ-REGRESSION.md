# EQ silence in the experimental KA17 build

Follow-up: after this static investigation, the user authorized flashing the
corrected code with a new USB marker. See [custom 2.27](../v227-peak-q-experimental/README.md)
for the subsequent transfer and validation status. The no-flash statements below
describe the earlier static-analysis phase.

## Status and observed symptom

On 2026-10-10, after installing custom USB version 2.26, the user reported sound
only with EQ OFF. All other tested EQ settings, including presets, were silent.
The user requested static diagnosis first: no reflash, rollback or device-setting
change. No such device action was performed during this investigation.

Both archived custom binaries are **known bad**. The 2.26 marker changes USB
identification only and inherits the DSP code from the unmarked 2.25 candidate.
The binary files and their manifests remain unchanged for reproducibility.

## Confirmed instruction defect

The peak routine enters XS3 dual-issue mode at `0x82308`. In this mode a word
contains either one long instruction or two short instructions:

- Low halfword, address `4n`: resource lane.
- High halfword, address `4n+2`: memory lane.

Short stack loads/stores (`LDWSP`, `STWSP`) require the memory lane. Our generator
instead paired every short instruction with a following NOP, putting stack
accesses in the resource lane. For example, the decoded bytes at `0x82350` are:

```text
Shipped:    04 54 ff 17    STWSP r0, 4 ; NOP   (invalid lane)
Corrected:  ff 17 04 54    NOP ; STWSP r0, 4   (memory lane)
```

This defect occurs at `0x82350`, `0x823a4`, `0x823cc`, `0x823dc`, and `0x82400`
in each of images 3, 6 and 7, tile 1: **15 invalid bundles**. These are tile-local
execution addresses, not offsets in the encoded firmware file. The stock peak
windows have no misplaced short stack accesses.

The first invalid bundle lies on the replacement's unconditional calculation
path, including at 0 dB gain. It is reached before coefficient calculation
finishes. This is a concrete execution defect consistent with EQ failing even
on presets, while an EQ-bypass path still produces audio. No hardware exception
registers or execution trace were captured, so the specific exception, firmware
handler behavior and whether this is the only cause of silence remain unproven.

Source: [XMOS XS3 architecture, v2.1.0](https://www.xmos.com/documentation/XM-014007-PS/pdf/XM-014007-PS-xs3-arch-inst-2.1.0.pdf),
sections 5.2 (lane order), 22.124 and 22.191 (raw stack-memory opcodes), and 25.1
(memory-lane restriction).

## Why the previous checks missed it

The partial interpreter decoded and executed the instruction arithmetic without
enforcing this lane restriction. The assembler's round-trip decoding check
verified opcode identity, not whether the processor could execute the bundle.
Consequently correct coefficient-model results, valid CRCs, and successful USB
enumeration were insufficient evidence for working EQ. The assembler and
validation gap were introduced by this patch, not the original FiiO firmware.

## Offline correction and regression checks

The generator now places short `ldw`/`stw` instructions after the NOP, while
leaving the arithmetic, call targets, instruction addresses and window length
unchanged. Short arithmetic instructions can execute in either lane; long
instructions occupy the entire word. Unclassified short instructions are rejected.

`tools/ka17_xs3_lanes.py` independently recognizes the documented six-bit
LDWSP/STWSP opcodes directly from bytes. It does not use the assembler or
Capstone to determine whether these instructions occupy the resource lane.
This is a **targeted stack-memory check, not full XS3 ISA validation**.
The partial interpreter and candidate verifier now reject the known-bad code.

The regression test was run against the old generator first: stock checks
passed, the shipped artifact had all 15 violations, and new builds failed in
all three images. After the generator correction, the tests pass. The model
also rejects the shipped binary at `0x82350` with 0 dB gain.

Completed offline checks:

- Four regression tests pass, with subcases covering all three PEQ images.
- The standalone lane checker reports 0 violations for stock, 15 for archived
  2.26 (expected exit 1), and 0 for the newly generated temporary candidate.
- The new candidate passes 2,940 peak coefficient cases; the stock analysis
  passes 1,512 peak cases and 5,880 low/high-shelf cases with the lane guard active.
- All image/tile CRCs pass. Compared with the old unmarked candidate, the new
  binary differs only by the 15 halfword swaps and tile CRCs: 72 changed bytes.
- The corrected unmarked temporary candidate SHA-256 is
  `6dd84c988634e027677cff6a050ef5a1d69d5248d83d08c719e8a1d713523652`.
  It retains USB version 2.25, is not a new published release, and was not flashed.
- The archived 2.26 SHA-256 remains
  `11ae81a3b422c77fbdb15ccd198922f9bf7f7ad0392ad075689b85f574b30a68`.

Run from the repository root with the analysis environment:

```sh
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/ka17_xs3_lanes.py patches/v226-peak-q-experimental/Fiio_KA17_V226_PEAK_Q_EXPERIMENTAL.bin
```

The second command intentionally exits 1 and lists the defects. Building into
a new temporary directory permits coefficient and CRC checks of the corrected
generator without modifying either archived firmware file or accessing USB.

**This is not confirmation of restored audio.** Math-library hooks still stand
in for target code, fixed-point conversion and the live DSP remain incompletely
validated, and no corrected image has been flashed. Low-frequency/high-sample-
rate numerical precision is a separate issue and is not fixed by moving the
instructions to their proper lane. The earlier response values are arithmetic
model results, not measurements of the silent firmware.
