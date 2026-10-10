# Handoff: FiiO KA17 firmware, PEQ and USB control

Status as of 2026-10-10 (Europe/Minsk). This document supports continued firmware
research and patch development. Communicate with the repository owner in Russian.
Paths below are relative to the repository root unless explicitly absolute.

## 1. Current state

- The corrected 2.27 firmware, generator fixes, regression documentation, USB CLI
  and presets were committed and pushed on `main` as
  `35093508492783bf5457014685c7acb425b7f3ab`. This amended the earlier published
  `3a5162013f66db8cb2a42f7a5aceafc441f4a1ab`, which contained the **faulty**
  experimental 2.26 patch. Inspect `git status` before continuing and preserve
  unrelated local changes. Use the authorized `gh` CLI for GitHub operations.
- At the user's explicit request, corrected custom **2.27** was flashed.
  After reconnection, FiiO `findDev` returned `0x227`; macOS reported
  `bcdDevice=551`. The user confirmed sound after the EQ playback check.
  This is not a frequency-response measurement.
- USER1 contains the first supplied oratory1990 Truthear Zero profile (Harman).
  USER2 contains the second profile (oratory1990's personal target).
  Writes and all parameters were checked by **direct HID readback**, then by
  another write using the new CLI and readback after switching slots.
  USER3 was not overwritten. USER2 was active at the last check; query the device
  again when current state matters.
- Authorization for that specific 2.27 flash has already been fulfilled.
  A later session must not independently reflash or change other settings merely
  because this handoff records the previous authorization.

## 2. Read the existing artifacts first

The detailed evidence is already recorded; use these entry points instead of
reconstructing the entire investigation.

| Topic | Repository file |
|---|---|
| Current binary, SHA-256, build reproduction and hardware status | [2.27 notes](../patches/v227-peak-q-experimental/README.md) |
| 2.26 failure, evidence and instruction-lane fix | [Regression analysis](../patches/v226-peak-q-experimental/EQ-REGRESSION.md) |
| Original Q mismatch, formulas, shelves and high-Fs precision | [Arithmetic notes](../patches/v226-peak-q-experimental/README.md) |
| Container parser, XS3 decoder and partial peak/shelf interpreter | [ka17_peq_analyze.py](../tools/ka17_peq_analyze.py) |
| Patch assembler, CRC calculation and reversible byte manifests | [ka17_patch_peak.py](../tools/ka17_patch_peak.py) |
| Nine USB version markers; pinned 2.26/2.27 builds | [ka17_mark_version.py](../tools/ka17_mark_version.py) |
| Independent check for forbidden short stack-memory placement | [ka17_xs3_lanes.py](../tools/ka17_xs3_lanes.py) |
| Numerical-error reproduction | [ka17_precision_check.py](../tools/ka17_precision_check.py) |
| Browser-free PEQ control, protocol, commands and limits | [USB guide](../tools/KA17-PEQ-USB.md), [CLI](../tools/ka17_peq_usb.py) |
| Exact values from the two supplied screenshots | [Preset JSON](../presets/truthear-zero-oratory1990.json) |
| Tests | [Lane tests](../tools/test_ka17_xs3_lanes.py), [USB tests](../tools/test_ka17_peq_usb.py) |

Local operation records excluded from Git (not available in a fresh clone):

- `patches/v227-peak-q-experimental/flash-session-2026-10-10/session.json`
  and `xmosdfu.log`: transfer, version and the user's audio confirmation.
- `presets/backups/2026-10-10-original-browser-read.json`: initial web-panel
  snapshot, **not** a guaranteed accurate CLI backup. The panel sometimes
  substitutes defaults when reads fail.
- `presets/backups/2026-10-10-after-browser-usb-verification.json`: direct
  readback of the already-installed profiles.
- `presets/backups/2026-10-10-before-cli-validation.json`: valid backup before
  the CLI qualification write; contains the oratory profiles, not older settings.
- `presets/backups/2026-10-10-cli-apply-result.json`: successful CLI write.

## 3. What “reading the firmware” means

**Parsing the official archived BIN works. Full flash readback from the connected
hardware has NOT been implemented or verified.** A USB version marker does not
prove that every installed firmware byte matches the file.

The original is nested under `KA17 V2.25 Firmware/`. Locate it with
`Path(...).rglob('Fiio_KA17_xmos_dfu_V225.bin')`, as `load_images` does.
It is 811,008 bytes. Its exact SHA-256 is pinned in `ka17_peq_analyze.SHA256`;
the parser deliberately rejects a different original. The offsets below must
be re-established before using them with another firmware version.

Every byte in the BIN has its two nibbles swapped:
`decoded_byte = (byte >> 4) | ((byte & 15) << 4)`.
This is reversible encoding, not cryptographic encryption; `k.SWAP` is the
lookup table. Container integers are little-endian. After decoding, look for
magic `0x00ff51de` at `0x1000` boundaries. Relevant header fields:

| Relative offset | Meaning |
|---:|---|
| `+0x04` | CRC of the first header block |
| `+0x08` | CRC of the whole image |
| `+0x10` | Image length |
| `+0x14` | Image ID; **not a version number** |
| `+0x18` | Repeated length |
| `+0x1c` | Tile count, here 2 |
| `+0x3c` / `+0x44` | Relative tile0 start / size in 32-bit words |
| `+0x58` / `+0x60` | Relative tile1 start / size in words |

Verified **decoded file offsets**, in bytes:

| Image ID | Image start | Length | Tile0 start / length | Tile1 start / length |
|---:|---:|---:|---:|---:|
| 1 | `0x00000` | 206888 | `0x01f80` / 69920 | `0x130a0` / 128904 |
| 3 | `0x33000` | 92300 | `0x34f80` / 46992 | `0x40710` / 37244 |
| 5 | `0x4a000` | 315056 | `0x4bf80` / 306976 | `0x96ea0` / 16 |
| 6 | `0x97000` | 92964 | `0x98f80` / 47592 | `0xa4968` / 37308 |
| 7 | `0xae000` | 97644 | `0xaff80` / 52272 | `0xbcbb0` / 37308 |

The executable tile base is `0x80000`. Convert runtime PC to file offset with:
`file_offset = tile_offset + pc - 0x80000`.
Image 5 contains the ESP32-C3 MCU update and has not been changed.
The mapping of **all** KA17 operating modes to images remains unproven.
Do not label image 1 definitively as “EQ OFF/MQA” based only on indirect clues.

## 4. PEQ address map and model boundaries

The main code studied is tile1 of images **3, 6 and 7**. Their peak code matches
after normalizing CP constants and call addresses.

- `0x80704`: filter-type dispatcher.
- Type 0: peak function at `0x82308`.
- Type 1: low-shelf path starting at `0x80834`.
- Type 2: high-shelf path starting at `0x80aa4`.
- `0x80f88..0x81040`: shared shelf-normalization section.
- `0x80f90`: peak skips the generic stores because it writes its own coefficients.
- `0x81334..0x8133c`: caller converts the supplied Q from hundredths.
- Peak runtime address `0x82308` maps to file offset `0x42a18` in image3,
  `0xa6c70` in image6 and `0xbeeb8` in image7.
- Replacement window: `0x8232c..0x82488`, end exclusive, 348 bytes. The new code
  uses 216 bytes, with NOP padding. Prologue and epilogue remain byte-identical.
- `0x82488` begins the subsequent fixed-point conversion. The model stops
  **before** it. Output floats: `sp[4]=b0`, `r8=b1=a1`, `r0=b2`, `sp[3]=a2`.
- The original code subsequently writes **b2, b1, b0, -a1, -a2**.
  The decoded operations indicate a Q24 representation; the full conversion
  path and audio DSP have not been emulated or measured on hardware.
- Peak inputs: `r0=gain`, `r1=frequency`, `r2=Q`, `r3=Fs`, all float32.
  The preserved prologue sets `r8=Fs`, `r7=Q`, `r9=frequency`, `r6=gain`.
  `r5` participates in output-buffer handling and is not used by the patch.
  Caller stack arguments and epilogue bounds checks need separate analysis
  before extending the model: the current `run()` does not model the full ABI.
- CP is `0x87110` for image3 and `0x87150` for images6/7. It is derived from
  the startup LDAP at `0x80090` in **single-issue** mode.

Known helper targets for image3 (images6/7 use a `+0x40` offset):

| Helper | PC |
|---|---:|
| fabsf | `0x84ce8` |
| float32 → float64 | `0x83b48` |
| float64 divide | `0x833e8` |
| float64 pow | `0x83e54` |
| float64 → float32 | `0x836a8` |
| float64 multiply | `0x83bc8` |
| float64 tan | `0x84404` |
| float32 divide | `0x84838` |

`PeakProgram` installs hooks using call sites in the **original** image.
To model patched code, first create `PeakProgram(stock_image)`, then replace
`.data` with the patched tile. Instantiating it directly from a patched image
will not work because the original call sites have been replaced. Helpers use
host math rather than executing their instructions. This model does not prove
all register/libm side effects.

## 5. XS3 pitfalls

Capstone 5.0.9 understands older XCore, not all of XS3. `decode()` extends it
for floating-point instructions and doubleword stack loads/stores. Opcodes are
listed in `ka17_peq_analyze.XS3`; operand decoding uses a compatible XOR format
as a proxy. This is **not an independent, complete processor decoder**.

- Dual-issue PCs and bundles are aligned to 4 bytes. Two short instructions
  read old register values simultaneously; modeling them sequentially is wrong.
- The first halfword is the resource lane; the second is the memory lane.
  Short stack LDW/STW instructions are allowed only in the second lane.
  Custom 2.26 violated this rule; see the regression analysis.
- Long 32-bit instructions occupy both lanes. ADD/LDC/NOP can use either lane.
- BL/branch displacement units are 4 bytes in dual issue and 2 in single issue.
- DI is saved in LR's low bit. DUALENTSP enables the mode, ENTSP clears it,
  and RETSP restores it. Apply the rules for the actual mode at each location,
  rather than treating the entire tile as dual issue.
- `STDSP/LDDSP` stack immediates use units of 8 bytes.
- The new guard checks raw six-bit opcodes of short LDWSP/STWSP independently
  of Capstone. It does not validate every ISA restriction, branch target or ABI.

Primary reference: [XMOS XS3 v2.1.0](https://www.xmos.com/documentation/XM-014007-PS/pdf/XM-014007-PS-xs3-arch-inst-2.1.0.pdf).
Temporary local copies were saved as `/tmp/ka17-xs3.pdf` and `/tmp/ka17-xs3.txt`.
Sections 5.2, 22.124, 22.191 and 25 are particularly relevant to this regression.

## 6. CRCs, versions and builds

Use `crc()` and `checksums()` in `ka17_patch_peak.py`, not a direct
`zlib.crc32(payload)`. All original tiles/images were checked.
The first header CRC covers bytes `[12:256]`; the second covers
`[12:image_size]`. The tile trailer covers the payload word count (excluding
the CRC word), followed by the payload. The XS3 recurrence uses initial value
`0xffffffff`, an additional zero word and a complement.
Update tile CRCs **before** image CRCs. Because of the CRC residue, the whole-image
CRC sometimes stays unchanged after replacing a payload and its tile CRC;
this alone is not evidence of a bug.

The build has two stages, each with a reversible manifest:

1. Stock → `patches/v225-peak-q-lane-fixed/`: corrected peak, USB still 2.25.
2. That pinned intermediate → `patches/v227-peak-q-experimental/`: USB 2.27.

Exact hashes and commands are in the 2.27 README. Older directories
`v225-peak-q-candidate` and `v226-peak-q-experimental` retain faulty binaries
as regression fixtures. **Do not overwrite or flash them.**
Generators refuse to overwrite existing output directories.

The version changes in nine USB descriptors; decoded offsets are listed in
`ka17_mark_version.DESCRIPTORS`. Each descriptor starts with `12 01`.
VID/PID occupy bytes 8..11 and bcdDevice bytes 12..13. This changes the USB
marker, not the displayed MCU version or image IDs. The screen can therefore
still show 2.25. A marker is **not** a substitute for full firmware readback.

## 7. Hardware operations and limits

Individual flash history is in the local session records. Vendor procedure:
[FiiO firmware update](https://www.fiio.com/newsinfo/895464.html).
A successful DFU transfer is not proof of an accurate frequency response.

The official Apple Silicon updater was extracted from the nested
`*For M Chip MAC.zip` in the 2.25 archive. Keep `xmosdfu`, `findDev` and
`libusb-1.0.0.dylib` together. The previous staging directory was
`/tmp/ka17-authorized-flash-v227`; the staged BIN was SHA-256 checked.
These temporary files may not exist in a later session.
The command actually used, **only after authorization**, was:

```sh
./xmosdfu 0x0093 --download firmware.bin 'FIIO KA17'
```

`findDev 0x0093` queries the version. Both vendor tools returned exit code 1
even on success. Check their output, the final 12672/12672 blocks,
`Download complete`, and the subsequent USB version. Do not experiment with
upload/erase commands on the connected device.

Before writing, the user disconnected audio outputs, stopped playback and set
D.MODE OFF, USB U2.0 and EQ OFF. After `Download complete`, the user reconnected
USB. If `Updating` appears, keep the cable connected until completion.
In this session the device returned directly to its normal screen.

macOS USB/HID access from the sandbox required `require_escalated`; ordinary
`ioreg` reads were available. HID PEQ settings and firmware updates use different
protocols. The verified HID framing, USER1/2/3 internal IDs, empty-report handling
and CLI are documented in the USB guide; another reverse-engineering pass over
the web application is unnecessary for these established operations.

## 8. Verified results and open questions

- The partial model passed 1,512 stock peak cases, 5,880 low/high-shelf cases
  and 2,940 patched peak cases. Coefficient accuracy does not guarantee an
  accurate frequency response. Numerical studies include Q=10, which exceeds
  the current UI/CLI limit of Q<=8; distinguish the research grid from supported
  user inputs.
- The last `python -m unittest discover -s tools -p 'test_*.py' -v` run passed
  **10 tests**. `git diff --check` also passed.
- Trusting the old model alone led to the 2.26 regression: mathematical checks
  missed illegal instruction execution. Each subsequent change needs an
  independent check of its new risks, not only the same assembler/decoder.
- Float32 precision limitations at low F0, high Q and high Fs were already
  present in stock firmware. The Q patch does not fix them and can worsen some
  cases. Tables and reproduction instructions are in the existing artifacts;
  these are model results, not hardware measurements.
- The complete filter/DSP runtime, fixed-point conversion, all libm side effects,
  mode-to-image mapping, extreme operating conditions and actual device response
  remain unverified.
- The user has no audio interface or digital loopback. A possible future
  measurement is KA17 → speakers → measurement microphone → REW. Compare EQ
  ON/OFF with unchanged acoustic geometry. No such measurements have been made.
- Separately verify the preamp's effect on the audio signal. Its USB parameter
  is stored, but the user initially thought FiiO was ignoring it. The web display
  proved unreliable; readback alone does not establish gain in the audio path.

## 9. Quick start for the next agent

1. Read the 2.27 README, regression analysis and USB guide; inspect `git status`.
2. For offline analysis, install `tools/requirements.txt` in a separate venv.
   For USB access use `tools/requirements-usb.txt`. A temporary environment used
   previously was `/tmp/ka17-re-venv/bin/python` with capstone 5.0.9 and
   hidapi 0.15.0; check availability before relying on it.
3. Run the offline tests. If reproducing a build, use a **new** temporary output
   directory and preserve archived artifacts.
4. Start device inspection with CLI `show` or `ioreg`, not a flash operation.
5. Keep backup and flash logs excluded when publishing later changes. Treat
   custom 2.26 as a known-bad diagnostic artifact, not a working release.

## Suggested skills

These are optional skills from the original development environment, not
repository dependencies. Locate their current `SKILL.md` before applying them.

- `diagnosing-bugs`: for continued debugging. Distinguish a reproducible static
  defect from a hardware symptom; a mathematical test is not a complete
  emulator or hardware test.
- `code-review`: for a separate review before publishing changes or conducting
  another hardware test.
- `handoff`: for preparing the next context transfer. This document originated
  in the OS temporary directory and was later translated and moved into the
  repository at the user's request.

Apply skills when needed. Additional agents require a basis in the user's
instructions or an applicable skill. Memory notes require an explicit user request.
