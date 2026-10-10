"""Regression for the actual published firmware's illegal stack-memory bundles."""
import unittest

import ka17_peq_analyze as k
import ka17_patch_peak as patch
from ka17_xs3_lanes import stack_lane_violations


class StackLaneRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = next((k.ROOT/'KA17 V2.25 Firmware').rglob('Fiio_KA17_xmos_dfu_V225.bin'))
        cls.images = [im for im in k.load_images(source) if im['id'] in (3, 6, 7)]
        cls.shipped = (k.ROOT/'patches/v226-peak-q-experimental/Fiio_KA17_V226_PEAK_Q_EXPERIMENTAL.bin').read_bytes().translate(k.SWAP)

    def test_stock_peak_has_no_misplaced_stack_access(self):
        for im in self.images:
            with self.subTest(image=im['id']):
                data = im['tile1'][k.PEAK-k.BASE:k.FLOAT_END-k.BASE]
                self.assertEqual(stack_lane_violations(data, k.PEAK), [])

    def test_shipped_artifact_has_five_illegal_bundles_per_image(self):
        for im in self.images:
            with self.subTest(image=im['id']):
                start = im['tile1_offset']+k.PEAK-k.BASE
                data = self.shipped[start:start+k.FLOAT_END-k.PEAK]
                errors = stack_lane_violations(data, k.PEAK)
                self.assertEqual([int(e['address'], 16) for e in errors],
                                 [0x82350, 0x823A4, 0x823CC, 0x823DC, 0x82400])

    def test_generated_replacement_obeys_stack_lane_rule(self):
        for im in self.images:
            with self.subTest(image=im['id']):
                replacement, _, _ = patch.Assembler(k.PeakProgram(im)).build()
                self.assertEqual(stack_lane_violations(replacement, patch.START), [])

    def test_interpreter_rejects_shipped_code_even_with_flat_gain(self):
        for im in self.images:
            with self.subTest(image=im['id']):
                program = k.PeakProgram(im)
                start = im['tile1_offset']
                program.data = self.shipped[start:start+im['tile1_size']]
                with self.assertRaisesRegex(ValueError, 'Illegal XS3 lane at 0x82350'):
                    program.run(0, 1000, 1)


if __name__ == '__main__':
    unittest.main()
