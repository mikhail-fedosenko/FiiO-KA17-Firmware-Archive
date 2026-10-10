import copy
import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main()
