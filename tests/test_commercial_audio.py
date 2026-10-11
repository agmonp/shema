import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from audio_features import prosody
import asr_update


class AcousticTests(unittest.TestCase):
    def test_known_pitches_and_gain(self):
        t = np.arange(16000) / 16000
        for frequency in (90, 120, 220, 440, 580):
            with self.subTest(frequency=frequency):
                wave = .2 * np.sin(2 * np.pi * frequency * t)
                measured = prosody(wave)
                self.assertAlmostEqual(measured['f0_hz'], frequency, delta=2)
                self.assertGreater(measured['voiced_share'], .9)
                self.assertAlmostEqual(prosody(wave / 2)['intensity_db'],
                                       measured['intensity_db'] - 6.02, delta=.2)

    def test_silence_noise_short_and_nonfinite(self):
        for wave in (np.zeros(16000), np.random.default_rng(4).normal(0, .05, 16000),
                     np.array([]), np.full(16000, np.nan)):
            measured = prosody(wave)
            self.assertNotIn('f0_hz', measured)
            self.assertEqual(measured['voiced_share'], 0)
            json.dumps(measured, allow_nan=False)

    def test_restricted_models_cannot_return_via_updater(self):
        models = [{'id': f'ivrit-ai/whisper-turbo-{kind}-ct2', 'lastModified': '2026-10-10'}
                  for kind in ('ok', 'nc', 'unknown')]
        def response(url):
            if '?' in url:
                return models
            if 'ok-ct2' in url:
                return {'cardData': {'license': 'apache-2.0'}}
            if 'nc-ct2' in url:
                return {'cardData': {'license': 'cc-by-nc-4.0'}}
            return {}
        with patch.object(asr_update, 'hf_json', side_effect=response):
            candidates, _ = asr_update.candidates({'device': 'cpu'})
        self.assertEqual([x['id'] for x in candidates], ['ivrit-ai/whisper-turbo-ok-ct2'])

    def test_analysis_without_emotions_preserves_transcript(self):
        import home_listener as server
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(server, HOME=root, DB=root/'test.sqlite',
                                CONFIG=root/'config.json', AUDIO=root/'audio'):
                server.config()
                server.migrate()
                cid = server.store_chunk(b'test', 'test-phone', '2026-10-11T10:00:00', 'wav')
                with server.db() as db:
                    row = dict(db.execute('SELECT * FROM chunks WHERE id=?', (cid,)).fetchone())
                server.save_analysis(row, datetime(2026, 10, 11, 10), {
                    'utterances': [{'t0': 0, 't1': 2, 'speaker': None, 'name': None,
                                    'text': 'בדיקת תמלול', 'prosody': {'f0_hz': 220},
                                    'emotion': {}, 'dims': {}, 'emb': None}], 'sounds': []})
                with server.db() as db:
                    result = db.execute('SELECT text, f0_hz, emotion, arousal, valence FROM utterances').fetchone()
                self.assertEqual(result['text'], 'בדיקת תמלול')
                self.assertEqual(result['f0_hz'], 220)
                self.assertIsNone(result['emotion'])
                self.assertIsNone(result['arousal'])
                self.assertIsNone(result['valence'])


if __name__ == '__main__':
    unittest.main()
