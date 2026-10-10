import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ka17_peq_usb as usb


class FakeHID:
    """Replay actual KA17 envelopes, including its zero-filled input reports."""
    def __init__(self, reports):
        self.pending = []
        self.reports = reports
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        self.pending.extend(self.reports)
        return len(data)

    def read(self, size, timeout):
        return self.pending.pop(0) if self.pending else []


class USBProtocolTests(unittest.TestCase):
    def test_crc_and_known_request(self):
        self.assertEqual(usb.crc8(b'123456789'), 0xA1)
        self.assertEqual(usb.packet(usb.PRESET).hex(), 'bb0b00001600c9ee')
        self.assertEqual(usb.SLOTS, {'USER1': 4, 'USER2': 8, 'USER3': 9})

    def test_blank_and_unrelated_reports_do_not_replace_preamp_with_zero(self):
        # Captured from the connected KA17; its response sequence/CRC are zero.
        device = usb.KA17.__new__(usb.KA17)
        device.device = FakeHID([
            bytes.fromhex('01000000000000000000000000000000'),
            bytes.fromhex('01bb0b000016010800ee'),
            bytes.fromhex('01bb0b00001702ffda00ee')])
        device.sequence, device.last_send = 7, 0
        self.assertEqual(device.read(usb.GAIN), bytes.fromhex('ffda'))
        self.assertEqual(len(device.device.writes), 1)

    def test_zero_gain_shelf_is_not_replaced_by_default_peak(self):
        report = bytes.fromhex('01bb0b00001508010000006400470100ee')
        self.assertIsNone(usb.response_payload(report, usb.BAND, 0))
        data = usb.response_payload(report, usb.BAND, 1)
        self.assertEqual(usb.decode_band(data, 1),
                         {'type': 'LOW_SHELF', 'frequency_hz': 100, 'gain_db': 0, 'q': .71})
        self.assertIsNone(usb.response_payload(report[:-1], usb.BAND, 1))

    def test_payload_signed_gain_and_q(self):
        band = {'type': 'PEAK', 'frequency_hz': 70, 'gain_db': -11.5, 'q': .35}
        self.assertEqual(usb.band_payload(0, band).hex(), '00ff8d0046002300')
        self.assertEqual(usb.decode_band(bytes.fromhex('00ff8d0046002300'), 0), band)

    def test_unknown_commands_and_unsupported_values_rejected(self):
        with self.assertRaises(ValueError):
            usb.packet(0x1C, write=True)  # Reset-all is deliberately unsupported.
        doc = json.loads((Path(__file__).resolve().parents[1]/
                          'presets/truthear-zero-oratory1990.json').read_text())
        usb.validate_document(doc)
        for change in ('factory', 'duplicate', 'q_precision', 'out_of_range', 'nan', 'missing'):
            bad = copy.deepcopy(doc)
            if change == 'factory': bad['presets'][1]['slot'] = 'Jazz'
            if change == 'duplicate': bad['presets'][1]['slot'] = 'USER1'
            if change == 'q_precision': bad['presets'][1]['bands'][0]['q'] = .711
            if change == 'out_of_range': bad['presets'][1]['bands'][0]['gain_db'] = 13
            if change == 'nan': bad['presets'][1]['preamp_db'] = float('nan')
            if change == 'missing': bad['presets'][1]['bands'].pop()
            with self.subTest(change=change), self.assertRaises(ValueError):
                usb.validate_document(bad)

    def test_readback_difference_and_backup_overwrite_fail(self):
        before = {'slot': 'USER1', 'preamp_db': -8.1, 'bands': []}
        with self.assertRaises(ValueError):
            usb.compare(before, dict(before, preamp_db=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'backup.json'
            usb.write_json(path, before)
            with self.assertRaises(FileExistsError):
                usb.write_json(path, {})
            self.assertEqual(json.loads(path.read_text()), before)


class APOImportTests(unittest.TestCase):
    def test_comments_bom_disabled_filters_and_neutral_padding(self):
        preset = usb.parse_apo('\ufeff# Test\nPreamp: -2.0 dB\n'
                               'Filter 1: on peq Fc 10 Hz Gain -4.4 dB Q 0.3 # bass\n'
                               'Filter: OFF PK Fc 100 Hz Gain 12 dB Q 1\n'
                               'Filter 2: ON HSC Fc 10000 Hz Gain 0 dB Q 0.71\n', 'USER2')
        self.assertEqual(preset['preamp_db'], -2)
        self.assertEqual(len(preset['bands']), 10)
        self.assertEqual(preset['bands'][0],
                         dict(type='PEAK', frequency_hz=10, gain_db=-4.4, q=.3))
        self.assertEqual(preset['bands'][1]['type'], 'HIGH_SHELF')
        self.assertEqual(usb.decode_band(usb.band_payload(0, preset['bands'][0]), 0),
                         preset['bands'][0])
        self.assertTrue(all(b['gain_db'] == 0 for b in preset['bands'][2:]))

    def test_unsupported_processing_precision_ranges_and_excess_bands_rejected(self):
        valid = 'Filter: ON PK Fc 100 Hz Gain 1 dB Q 1\n'
        for text in ('Include: other.txt\n'+valid, 'Channel: L\n'+valid,
                     'Device: all\n'+valid, 'GraphicEQ: 20 3\n'+valid,
                     'Filter: ON LSC Fc 100 Hz Gain 1 dB\n',
                     'Filter: ON PK Fc 100 Hz Gain 1 dB BW Oct 1\n',
                     valid.replace('Q 1', 'Q 0.711'),
                     valid.replace('100 Hz', '9 Hz'),
                     valid.replace('100 Hz', '100.5 Hz'),
                     valid.replace('1 dB', '13 dB'),
                     valid*11, 'Preamp: -1 dB\nPreamp: -2 dB\n'+valid,
                     '# empty', valid.replace('ON', 'OFF')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                usb.parse_apo(text, 'USER1')
        with self.assertRaises(ValueError):
            usb.parse_apo(valid, None)
        self.assertEqual(usb.parse_apo(valid, 'USER1')['preamp_db'], 0)

    def test_known_apo_files_match_screenshot_bands_and_assignment(self):
        root = Path(__file__).resolve().parents[1]/'presets'
        wanted = json.loads((root/'truthear-nova-zero-users.json').read_text())['presets']
        files = ['truthear-nova-oratory1990-harman', 'truthear-nova-oratory1990-target',
                 'truthear-zero-oratory1990-target']
        loaded = usb.load_presets(apo=[f"{p['slot']}={root/'apo'/(name+'.txt')}"
                                      for p, name in zip(wanted, files)])
        for expected, actual, count in zip(wanted, loaded, (6, 6, 9)):
            self.assertEqual(expected['slot'], actual['slot'])
            self.assertEqual(expected['preamp_db'], actual['preamp_db'])
            self.assertEqual(expected['bands'][:count], actual['bands'][:count])
            self.assertTrue(all(b['gain_db'] == 0 for b in actual['bands'][count:]))
        with self.assertRaises(ValueError):
            usb.load_presets(apo=[f'USER1={root/"apo"/(files[0]+".txt")}']*2)

    def test_bad_input_fails_before_opening_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.txt'
            path.write_text('Include: other.txt\n')
            with patch('sys.argv', ['ka17_peq_usb', 'apply', str(path), '--slot',
                                   'USER1', '--backup', str(Path(directory)/'backup.json')]), \
                    patch.object(usb, 'KA17') as device, self.assertRaises(ValueError):
                usb.main()
            device.assert_not_called()


if __name__ == '__main__':
    unittest.main()
