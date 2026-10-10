# KA17 2.26 — experimental peak-Q correction

**WITHDRAWN / KNOWN BAD — do not flash.** On 2026-10-10, the tested KA17 had
sound only with EQ OFF; all tested EQ settings, including presets, were silent.
The patch contains incorrectly placed short memory instructions. This also
affects the unmarked 2.25 candidate. See the [regression analysis](EQ-REGRESSION.md).
The files and manifests below are preserved unchanged as diagnostic evidence.
The corrected generator is used in [custom 2.27](../v227-peak-q-experimental/README.md).
See that build's separate transfer and audio-validation status.

This is an **unofficial modification of FiiO KA17 firmware 2.25**, identified over
USB as **2.26**. It is not an official FiiO 2.26 release.

[Archived faulty firmware — diagnostic use only](Fiio_KA17_V226_PEAK_Q_EXPERIMENTAL.bin)

- Size: **811,008 bytes**.
- SHA-256: `11ae81a3b422c77fbdb15ccd198922f9bf7f7ad0392ad075689b85f574b30a68`.
- Base firmware SHA-256: `2006917650ccb6207e9be52a3202f24d727c293b5e3f3c10f4ad044231ee8213`.
- This build was transferred to one KA17 on **2026-10-10**. After USB reconnection,
  both the FiiO discovery utility and macOS reported `bcdDevice = 0x0226`.
- **The corrected PEQ response has not been verified by an audio measurement.**

## What changed

The peak coefficient calculation in tile 1 of images **3, 6 and 7** was replaced
with a calculation using the RBJ definition of Q. The replacement stays inside
the existing function and preserves its entry, stack frame, coefficient output
locations and epilogue. Image sizes and image-selection IDs are unchanged.

Low-shelf and high-shelf calculations are unchanged. Static analysis found that
their formulas already use RBJ Q directly, rather than shelf slope S.

A separate version-marker change sets `bcdDevice` from `0x0225` to `0x0226` in
nine USB device descriptors in images **1, 3, 6 and 7**. Image 1 receives only the
version marker and associated checksum changes; its DSP code is not patched.
The MCU update image, image 5, is unchanged. The mapping of every operating mode
to these images has not been established.

The intermediate peak patch changes 848 bytes from stock. The USB version marker
changes a further 25 bytes from that intermediate file. These counts include
checksum bytes. All image and tile CRCs were verified before and after patching.

## Why the original Q differs

The recovered original peak routine uses:

```text
V = 10^(abs(gain_dB) / 20)
K = tan(pi * F0 / Fs)
```

It constructs a peak using V and K/Q without converting the supplied Q to the
convention used by RBJ. The resulting response is equivalent to RBJ with:

```text
Q_RBJ = Q_KA17 / 10^(abs(gain_dB) / 40)
```

For example, at either +6 dB or -6 dB, entering Q=1 produces an effective RBJ Q of
approximately **0.708**. The peak is wider than the RBJ peak requested with Q=1.
This is a convention mismatch demonstrated by the extracted arithmetic; it does
not establish why the original developers selected that implementation.

The replacement uses signed gain:

```text
A = 10^(gain_dB / 40)
K = tan(pi * F0 / Fs)
t = K / Q
C = 1 + K*K
N = 1 / (C + t/A)

b0 = (C + t*A) * N
b1 = a1 = 2 * (K*K - 1) * N
b2 = (C - t*A) * N
a0 = 1
a2 = (C - t/A) * N
```

These are RBJ peaking coefficients in tan form. The intended input is the desired
RBJ Q directly. The archived binary cannot be recommended for use because of
the execution defect described above; mathematical agreement did not establish
that these instructions execute correctly on the processor.

## Precision at low frequencies and high sample rates

**Limited numerical precision was already present in the original firmware.**
The peak calculation rounds intermediate values and coefficients to `float32`.
When F0/Fs is small, the coefficients approach values such as 1, -2 and 1. Small
differences between them determine the filter's frequency and bandwidth;
rounding those differences can substantially change the response. Large Q makes
a narrow peak particularly sensitive.

The Q correction does **not** fix this precision problem. It also changes the
arithmetic and therefore its rounding behavior: some combinations are worse
than stock. Lowering the sample rate generally helps, but individual errors are
not monotonic because of rounding.

The following example uses **F0=20 Hz, Q=10 and gain=-12 dB**. Values are the
modeled response **at F0**, before fixed-point conversion:

| Sample rate | Original 2.25 model | Replacement arithmetic model | Intended level |
|---:|---:|---:|---:|
| 44.1 kHz | -11.9997 dB | -11.9991 dB | -12 dB |
| 48 kHz | -12.0022 dB | -11.5322 dB | -12 dB |
| 96 kHz | -12.0126 dB | -9.5536 dB | -12 dB |
| 192 kHz | -3.6624 dB | -1.9406 dB | -12 dB |

Both Q conventions have the same intended center gain, so this example exposes
precision loss independently of the original Q mismatch. It does not imply that
their bandwidths should match. These are synthetic static-model results, **not
measured KA17 performance**, and the table is not a worst-case bound over the
whole frequency response. The slopes of a narrow peak can have larger errors
than its center. The original model did not reject illegal lane placement;
these values therefore never established an audible response from custom 2.26.
They can now be reproduced using the lane-corrected replacement in memory.

Further improvement would require retaining greater precision through coefficient
calculation and conversion. The final coefficient representation and audio DSP
must also be evaluated; replacing some calculations with `double` alone cannot
be assumed to solve every low-frequency/high-Q case. This build does not include
that improvement.

## How to identify the installed custom firmware

After updating and reconnecting the KA17, inspect the USB device version:

| Build | USB `bcdDevice` | Decimal value shown by macOS `ioreg` |
|---|---|---:|
| Original / unmarked peak candidate | `0x0225` | 549 |
| This custom build | **`0x0226`** | **550** |

On macOS, with ripgrep installed:

```sh
ioreg -p IOUSB -l -w 0 | rg -A 35 'FIIO KA17@'
```

Find `"bcdDevice" = 550` in the KA17 entry. Its vendor/product IDs should remain
`10610`/`147` (`0x2972`/`0x0093`).

Alternatively, the `findDev` executable bundled in the official FiiO Mac updater
can query the device from its Resources directory, alongside its bundled libusb:

```sh
./findDev 0x0093
```

The observed output for this build is:

```text
findDev
target dev found!
bcd:0x226
finish
```

This vendor utility returned exit code 1 even when it found the device, so check
its output rather than interpreting that exit code alone as a detection failure.

**The number on the KA17 screen may still be 2.25**, because the MCU version has
not been changed. USB 2.26 confirms that firmware containing our identification
marker is running. It does not prove correct PEQ operation in every mode; that
requires response measurements.

## Validation and limitations

- The stock peak path fails the regression against RBJ with the same Q.
- The former arithmetic-only model passed 2,940 parameter combinations across the
  three PEQ images; maximum coefficient error against the RBJ reference was
  approximately `2.58e-7`. Small coefficient error is **not** a guarantee of
  small response error, as the precision example above demonstrates.
- Shelf formulas were checked on 5,880 parameter combinations before patching;
  their code remains byte-identical in this build.
- The input is pinned by SHA-256. Image sizes, checksums, allowed change ranges,
  and reversibility of the recorded byte edits were checked.
- The partial instruction interpreter substitutes host math-library calls. It
  is not a bit-exact XMOS emulator. Fixed-point conversion and the running audio
  DSP have not been comprehensively validated.
- Hardware evidence includes a completed transfer, successful USB re-enumeration,
  an ordinary device screen, the 2.26 USB marker, and the subsequent **failure
  report: silence with EQ enabled**. No complete firmware readback or
  acoustic/electrical PEQ response measurement was performed.

This remains experimental firmware. A valid CRC does not establish correct
execution, and possession of the original firmware does not guarantee recovery
if a modified device stops exposing its update interface. Incorrect DSP behavior
can also produce loud noise. The observed USB boot success is not a general
safety guarantee for other devices, modes or parameter combinations.

## Reproduce the checks

From the repository root, use Python 3.10 or later:

```sh
python3 -m venv /tmp/ka17-analysis-venv
/tmp/ka17-analysis-venv/bin/python -m pip install -r tools/requirements.txt

/tmp/ka17-analysis-venv/bin/python tools/ka17_peq_analyze.py
/tmp/ka17-analysis-venv/bin/python -m unittest discover -s tools -p 'test_*.py' -v
/tmp/ka17-analysis-venv/bin/python tools/ka17_mark_version.py \
  --verify patches/v226-peak-q-experimental/Fiio_KA17_V226_PEAK_Q_EXPERIMENTAL.bin
/tmp/ka17-analysis-venv/bin/python tools/ka17_precision_check.py
```

These commands operate on local files and do not access USB or flash a device.
The version-marker verifier checks historical artifact identity and CRCs only;
it does not approve its instruction placement or audio behavior. To demonstrate
the newly detected defect, the following commands must **fail**:

```sh
/tmp/ka17-analysis-venv/bin/python tools/ka17_xs3_lanes.py \
  patches/v226-peak-q-experimental/Fiio_KA17_V226_PEAK_Q_EXPERIMENTAL.bin
/tmp/ka17-analysis-venv/bin/python tools/ka17_patch_peak.py \
  --verify-candidate patches/v225-peak-q-candidate/Fiio_KA17_V225_PEAK_Q_EXPERIMENTAL.bin
```

The updated generator refuses to validate these old artifacts. It emits corrected
lane placement when building into a new output directory. For the separate
expected failing stock Q regression, run
`tools/ka17_patch_peak.py --check-stock` with the same Python interpreter.

The [peak patch manifest](../v225-peak-q-candidate/patch-manifest.json) records
changes from official 2.25 to the unmarked peak candidate. The
[version manifest](version-manifest.json) records the subsequent USB marker
change. Both contain exact before/after bytes and SHA-256 hashes. The intermediate
binary and disassembly are retained as evidence of that two-stage build. The
original faulty generator is recorded in Git commit `3a51620`; the current
generator deliberately produces different bytes.

## References

- [Original ASR discussion](https://www.audiosciencereview.com/forum/index.php?threads/some-notes-on-fiio-ka17.61493/page-2)
- [RBJ Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/)
- [XMOS XS3 architecture and instructions](https://www.xmos.com/documentation/XM-014007-PS/pdf/XM-014007-PS-xs3-arch-inst-2.1.0.pdf)
- [Official FiiO KA17 firmware update instructions](https://www.fiio.com/newsinfo/895464.html)
