#!/usr/bin/env python3
"""Reproduce the documented stock/custom low-frequency precision comparison.

No USB access. Executes the coefficient paths using the partial interpreter and
host math hooks, then evaluates their ideal transfer functions BEFORE fixed-point
conversion. This is not a hardware measurement or full DSP emulation.
"""
import json

import ka17_peq_analyze as k
import ka17_patch_peak as patch


def main():
    source = next((k.ROOT/'KA17 V2.25 Firmware').rglob('Fiio_KA17_xmos_dfu_V225.bin'))
    image = next(i for i in k.load_images(source) if i['id'] == 3)
    stock, custom = k.PeakProgram(image), k.PeakProgram(image)
    # The published 2.26 artifact has illegal lane placement and is rejected
    # by the interpreter. Model the corrected generator's code in memory;
    # never bypass its ISA guard to reproduce old arithmetic-only results.
    replacement, _, _ = patch.Assembler(custom).build()
    data = bytearray(custom.data)
    data[patch.START-k.BASE:patch.END-k.BASE] = replacement
    custom.data = bytes(data)
    rows = []
    for fs in (44100, 48000, 96000, 192000):
        stock_coefficients, _ = stock.run(-12, 20, 10, fs)
        custom_coefficients, _ = custom.run(-12, 20, 10, fs)
        stock_db = k.response(stock_coefficients, 20, fs)
        custom_db = k.response(custom_coefficients, 20, fs)
        # At F0, both definitions of Q must still give the requested gain.
        # Thus this comparison isolates a precision error from Q conventions.
        stock_ideal = k.response(k.recovered_peak(-12, 20, 10, fs), 20, fs)
        custom_ideal = k.response(k.rbj_peak(-12, 20, 10, fs), 20, fs)
        assert abs(stock_ideal+12) < 1e-6 and abs(custom_ideal+12) < 1e-6
        rows.append({'fs':fs, 'stock_center_db':stock_db, 'custom_center_db':custom_db,
                     'stock_error_db':abs(stock_db+12), 'custom_error_db':abs(custom_db+12)})
    assert rows[-1]['stock_error_db'] > 8, 'Stock precision issue not reproduced'
    assert rows[-1]['custom_error_db'] > rows[-1]['stock_error_db']
    print(json.dumps({'scope':'Static coefficient model, before fixed-point conversion',
                      'custom_code':'current generator, corrected lane placement; not a hardware measurement',
                      'f0':20,'q':10,'gain_db':-12,'image':3,'results':rows},indent=2))


if __name__ == '__main__': main()
