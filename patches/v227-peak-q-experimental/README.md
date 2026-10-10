# KA17 custom 2.27 — peak Q and instruction-lane correction

Unofficial modification of FiiO 2.25. USB identification is **2.27**
(`bcdDevice=0x0227`, decimal **551**). The MCU/display version may remain 2.25.

- File: [Fiio_KA17_V227_PEAK_Q_EXPERIMENTAL.bin](Fiio_KA17_V227_PEAK_Q_EXPERIMENTAL.bin)
- Size: 811,008 bytes.
- SHA-256: `ce6b13a6b05626a32746954bf9cf0ee262f010920259e66956606d53c78d519b`.
- Hardware status: all 12,672 blocks transferred on 2026-10-10; the updater
  reported `Download complete`. After reconnect, the user observed the normal
  screen; FiiO `findDev` reported `bcd:0x227` and macOS `ioreg` independently
  reported `bcdDevice = 551` for the KA17 (VID/PID `0x2972/0x0093`).
  In response to a request to check preset/custom EQ playback, the user reported
  that sound is present. This confirms audio restoration in the tested setting;
  the exact preset, custom-filter settings and sample rate were not specified.
  PEQ response and Q accuracy have not been measured.

Compared with the faulty custom 2.26, this build moves 15 short stack-memory
instructions into the correct XS3 dual-issue lane, changes nine USB version
markers, and updates the affected CRCs. No other bytes change. See the
[failure analysis](../v226-peak-q-experimental/EQ-REGRESSION.md).

The intended RBJ peak-Q correction is retained. Low/high-shelf code, MCU image,
image-selection IDs, and image sizes are unchanged. The low-frequency/high-Q/
high-sample-rate precision limitation remains; see the
[arithmetic and precision notes](../v226-peak-q-experimental/README.md).

Offline validation passed: 2,940 peak coefficient cases, four lane regression
tests covering all three affected images, CRCs for all images/tiles, all nine
version markers, and a restricted byte comparison against custom 2.26. The
model uses host math-library hooks and does not fully emulate the live DSP.
Successful transfer or a USB version marker alone does not prove working EQ.

## Reproduce and verify

### Manual workaround for unmodified 2.25

For a **peaking** filter with a desired RBJ Q and gain G in dB, enter:

```text
Q_KA17 = Q_RBJ * 10^(abs(G) / 40)
```

For example, Q_RBJ=1 at either +6 or -6 dB requires Q_KA17≈1.41254
(1.41 with a 0.01 input step). Keep frequency and gain unchanged. The stock
routine uses V=10^(abs(G)/20) and K/Q without converting Q to the RBJ
convention, yielding Q_effective=Q_KA17/sqrt(V). This explains the gain-dependent
bandwidth mismatch; it does not establish the original developers' intent.
The workaround is limited by the device's Q range and rounding. Do not apply
it to shelves or to this patched build, which accepts the desired RBJ Q directly.

**Both stock and patched firmware retain limited PEQ numerical precision at
high sample rates**, especially for low-frequency, high-Q filters. Float32
rounding of almost-cancelling coefficients can produce substantial response
errors. The correction does not solve this separate issue, and some parameter
combinations can be worse after the patch. These conclusions come from the
static arithmetic model; electrical/acoustic response measurements are pending.

### Offline checks

Use Python with `tools/requirements.txt` installed. From the repository root:

```sh
python -m unittest discover -s tools -p 'test_*.py' -v
python tools/ka17_patch_peak.py --verify-candidate patches/v225-peak-q-lane-fixed/Fiio_KA17_V225_PEAK_Q_EXPERIMENTAL.bin
python tools/ka17_mark_version.py --version 2.27 --verify patches/v227-peak-q-experimental/Fiio_KA17_V227_PEAK_Q_EXPERIMENTAL.bin
python tools/ka17_xs3_lanes.py patches/v227-peak-q-experimental/Fiio_KA17_V227_PEAK_Q_EXPERIMENTAL.bin
```

All four commands are offline. The [peak manifest](../v225-peak-q-lane-fixed/patch-manifest.json)
and [version manifest](version-manifest.json) record reversible edits from the
pinned original firmware through the corrected intermediate build to custom 2.27.

After reconnecting on macOS, identify the device with:

```sh
ioreg -p IOUSB -l -w 0 | rg -A 35 'KA17@'
```

The KA17 entry should show `"bcdDevice" = 551`, vendor 10610 and product 147.
This is a custom identification marker, not an official FiiO release number.
