# FiiO-KA17-Firmware-Archive
As title, this repo is the collection of FiiO KA17 Firmware that exists (or not).

## USB preset tool

[Configure USER1/USER2/USER3 without a browser](tools/KA17-PEQ-USB.md). Includes
standalone Equalizer APO profiles and arbitrary PEQ import. Current mapping:
Truthear Nova Harman in USER1, Nova oratory1990 target in USER2, and Truthear Zero
oratory1990 target in USER3. USER3's internal ID is 9.

## Unknown version
- In v0.84 there is a version name ``Fiio_KA7_xmos_v134_fac_V84.bin`` that come along with other XMOS files, which i don't exactly know what that is. But haven't tested fully. I assumed ``fac`` is the factory version for QA.
- In order to flash it, flash your KA7 to the v1.16 firmware, then use the same v1.16 exe to flash ``Fiio_KA7_xmos_v134_fac_V84.bin`` ....and i don't know why it is called v1.34 but in the DAC it said 0.84

## Experimental PEQ modification

**Known-bad experimental build: do not flash the custom 2.26 or its unmarked 2.25 candidate.** On 2026-10-10, the tested device produced sound only with EQ OFF; every tested EQ setting, including presets, was silent. Static analysis found illegal XS3 instruction placement in the patch generator. The binaries are retained for diagnosis, not recommended use.

See the [regression analysis](patches/v226-peak-q-experimental/EQ-REGRESSION.md) and [original custom firmware notes](patches/v226-peak-q-experimental/README.md). The corrected build has USB version **2.27**; see its [build and hardware validation status](patches/v227-peak-q-experimental/README.md). The user confirmed sound after the update in response to the EQ playback check. PEQ response and Q accuracy remain unmeasured.

## Firmware research handoff

For firmware analysis, patch development or USB protocol work, start with the
[firmware handoff](docs/firmware-handoff.md). It maps the container and PEQ code,
records the XS3 pitfalls, and distinguishes verified results from open questions.
