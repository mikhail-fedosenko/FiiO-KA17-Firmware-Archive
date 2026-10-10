# KA17 PEQ from the terminal

`ka17_peq_usb.py` reads and writes user presets directly over USB HID. It does
not need Chrome, the FiiO website, a FiiO account or an Internet connection after
installing its Python dependency. It does not update firmware.

## Current presets and standalone APO files

The user's 2026-10-10 Nova screenshots and the previously supplied Zero personal
oratory1990 target are mapped in
[`../presets/truthear-nova-zero-users.json`](../presets/truthear-nova-zero-users.json).

| Slot | Internal ID | Profile | Preamp |
|---|---:|---|---:|
| USER1 | 4 | Truthear Nova: screenshot 1, Harman | +0.1 dB |
| USER2 | 8 | Truthear Nova: screenshot 2, oratory1990 target | -2.0 dB |
| USER3 | 9 | Truthear Zero: previously supplied oratory1990 personal target | -3.8 dB |

All four known profiles are also available as standalone Equalizer APO files:

- [Nova / Harman](../presets/apo/truthear-nova-oratory1990-harman.txt)
- [Nova / oratory1990 target](../presets/apo/truthear-nova-oratory1990-target.txt)
- [Zero / Harman](../presets/apo/truthear-zero-oratory1990-harman.txt)
- [Zero / oratory1990 target](../presets/apo/truthear-zero-oratory1990-target.txt)

The older [`truthear-zero-oratory1990.json`](../presets/truthear-zero-oratory1990.json)
retains its historical USER1/USER2 mapping; applying that file replaces those
slots with Zero profiles. To choose a different slot, use its standalone APO file.

Q is entered exactly as shown, without the stock KA17 gain-dependent workaround:
this device runs the custom 2.27 peak-Q correction. Low/high shelves use Q, not
the BW column. Unused bands are neutral peak filters at 0 dB. Zero-gain shelves
retain their frequency, Q and shelf type. Nova screenshot 2 specifies **10 Hz**
for its second peak; the CLI preserves this value rather than substituting 20 Hz.
The lower validation limit is now 10 Hz. This extends the previous UI-derived
limit; USB storage verification does not establish the acoustic response at 10 Hz.

Direct USB readback confirms stored parameters. Whether the audio engine applies
the preamp and filter response accurately has not been measured. A zero shown
by the website is not conclusive evidence that the device discarded the value.

## Setup on macOS

From the repository root:

```sh
python3 -m venv .venv-usb
.venv-usb/bin/python -m pip install -r tools/requirements-usb.txt
```

The installed package is `hidapi==0.15.0` from PyPI; the import name is `hid`.
macOS Apple Silicon is the tested platform. Other platforms have not been tested.

Connect the KA17 over USB, enable an EQ mode on the device and close FiiO Control
in the browser/mobile app so there is only one controller. Pause playback while
editing: selecting a preset changes the active audio response immediately.

## Commands

Validate the file without accessing USB:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py validate presets/truthear-nova-zero-users.json
```

Read the active preset without switching it:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py show
```

Back up all three user presets, including USER3:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py read \
  --slots USER1 USER2 USER3 --output presets/backups/my-ka17-before.json
```

Write the current three-slot mapping, making a fresh backup first:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py apply \
  presets/truthear-nova-zero-users.json \
  --backup presets/backups/before-oratory.json
```

The backup name must be new; existing files are never overwritten. Backups under
`presets/backups/` are excluded from Git. `apply` is an explicit write command:
there is no second interactive prompt. It validates every input before opening
USB, backs up every slot it will change, checks the in-memory readback, sends
Save, switches away/back and checks all saved values. It restores the initially
active preset. Only slots named in the input file are written.

Verify the saved profiles without rewriting their parameters:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py verify presets/truthear-nova-zero-users.json
```

`read` and `verify` temporarily select each requested slot and then restore the
previous active slot. They do not save or change the band's parameter values.
`show` is the command to use when even temporary selection is undesirable.

Restore a backup produced by this CLI:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py apply \
  presets/backups/my-ka17-before.json \
  --backup presets/backups/before-restore.json
```

## Import arbitrary PEQ from Equalizer APO

Apply a standalone profile to any user slot:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py validate my-eq.txt --slot USER3
.venv-usb/bin/python tools/ka17_peq_usb.py apply my-eq.txt --slot USER3 \
  --backup presets/backups/before-my-eq.json
.venv-usb/bin/python tools/ka17_peq_usb.py verify my-eq.txt --slot USER3
```

Or validate/apply/verify multiple APO files together:

```sh
.venv-usb/bin/python tools/ka17_peq_usb.py apply \
  --apo USER1=presets/apo/truthear-nova-oratory1990-harman.txt \
  --apo USER2=presets/apo/truthear-nova-oratory1990-target.txt \
  --apo USER3=presets/apo/truthear-zero-oratory1990-target.txt \
  --backup presets/backups/before-nova-zero.json
```

The importer follows the [official APO configuration syntax](https://sourceforge.net/p/equalizerapo/wiki/Configuration%20reference/)
for `Preamp: ... dB` and `Filter N: ON/OFF PK/PEQ/LSC/HSC Fc ... Hz Gain ... dB Q ...`.
`LS`/`HS` aliases with explicit Q are accepted too. Comments, UTF-8 BOM, whitespace
and case variations are supported. Filter numbers are informational; enabled
filters retain file order. OFF filters are omitted. Missing Preamp defaults to
0 dB. One to ten enabled filters are accepted; free slots are reset to neutral
1000 Hz peaks, Q=1, gain=0. The JSON schema still requires all ten bands.

This imports a shared-channel PEQ, not the full APO processing language. Unsupported
commands (`Include`, `Channel`, `Device`, `GraphicEQ`, expressions, etc.), multiple
preamps, shelf slope/BW notation and omitted Q are rejected. There is no silent
approximation, rounding or clamping. Every input is checked before accessing USB.

Writing is restricted to the tested USB version `0x0227` and USER1/2/3. The tool
rejects ambiguous device selection and unrepresentable precision. Limits: integer
frequency 10..20000 Hz, gain/preamp -12..12 dB in 0.1 dB steps, Q 0.25..8 in 0.01
steps. Peak/low-shelf/high-shelf filters are supported. A backup containing another
filter type is rejected rather than silently changed.

If a command fails after writing starts, it may have partially updated a slot.
The pre-write backup is retained; inspect the error/readback and restore it if
needed. There is no hidden automatic rollback or success claim after a timeout.

## Protocol and validation

Source: [official FiiO Control bundle](https://fiiocontrol.fiio.com/static/js/index-B_yYxU3i.js),
retrieved during this session; SHA-256
`f223151bbdc964883d4573767625bbaf6a34ce9c4babe314ad33d7bfafb19921`.
Relevant symbols: `ut/y6e` (framing/CRC), `pre/cN` (band write/read),
`fN/aT` (preset selection/read), `vre/dN` (global gain), `bre` (Save), and the
`FIIO_KA17` preset table. This is a reverse-engineered client implementation,
not a vendor-supported API guarantee.

- VID/PID `0x2972/0x0093`, HID report ID 1.
- Payload: header `AA 0A` for writes or `BB 0B` for reads, 16-bit sequence,
  command, payload length, data, CRC-8/MAXIM and `EE` terminator.
- Integers are big-endian. Gain is signed tenths of dB; frequency is integer Hz;
  Q is unsigned hundredths. Band index is 0..9; types are peak=0, LS=1, HS=2.
- On this KA17, response sequence/checksum bytes are zero. The reader therefore
  matches command and band index, validates the envelope and decoded ranges,
  and allows only one outstanding request. It does not claim response-CRC
  validation where the firmware does not provide it.
- Reads skip empty/zero reports and unrelated replies. The website's legacy
  client accepts the first input report, and its band read catches failures by
  substituting a neutral 20 Hz peak. This is consistent with the observed false
  display of preamp=0 and a missing zero-gain shelf. Direct readback found the
  intended values stored correctly.
- Commands are paced at least 200 ms apart, matching the official KA17 queue.

Offline protocol regression tests:

```sh
.venv-usb/bin/python -m unittest discover -s tools -p 'test_ka17_peq_usb.py' -v
```

They cover real reply envelopes, zero reports before valid replies, wrong-band
replies, signed negative gain, exact Q precision, malformed frames, rejecting
factory/reset operations, and preserving existing backups.

Earlier Zero-only verification on 2026-10-10: direct USB `verify` matched all 20 bands and
both preamp values after browser Save and subsequent slot selection. With the
browser closed, CLI `apply` then backed up and rewrote USER1/USER2, saved each,
switched away/back and matched every value again. It restored active preset 8
(USER2). USER3 was not written. All ten repository regression tests passed
(six USB protocol tests and four firmware-lane tests). An original
browser-read snapshot is also retained under `presets/backups/`; it is labelled
as such and is not a device-verified CLI backup. Audio-response/Q measurements
remain outside this verification.

Latest hardware verification on 2026-10-10: the CLI imported the three standalone
APO files into USER1 (Nova/Harman), USER2 (Nova/oratory1990 target) and USER3
(Zero/oratory1990 target). Before writing it saved
`presets/backups/2026-10-10-before-nova-zero-apo.json`. Every band and preamp
matched direct HID readback both before Save and after switching away/back.
The Nova USER2 second peak retained exactly 10 Hz, -4.4 dB and Q=0.30. The initially
active USER2 (internal ID 8) was restored. A subsequent three-slot snapshot is
saved as `presets/backups/2026-10-10-after-nova-zero-apo.json`. All 14 repository
regression tests passed, including four APO import tests. Audio response, preamp
application in the audio path and power-cycle persistence remain unmeasured.
