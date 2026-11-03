import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from genre_classification_claim_audit.audit import audit, claims, evidence, main, GENERIC
from genre_classification_claim_audit.phrases import GENRE, NOGENRE

EXPECTED_POS = ('music genre classification', 'classifies music by genre', 'classifies songs by genre', 'classifies audio by genre', 'classifies music genre', 'detects music genre', 'detects the genre of music', 'detects the genre of a song', 'detects song genre', 'identifies music genre', 'identifies the genre of music', 'identifies song genre', 'predicts music genre', 'predicts the genre of a song', 'predicts song genre', 'estimates music genre', 'classifies a song by genre', 'classifies a track by genre', 'classifies tracks by genre', 'genre classification of music', 'genre classification of songs', 'music genre detection', 'song genre detection', 'music genre identification', 'song genre identification', 'music genre prediction', 'song genre prediction', 'recognizes music genre', 'recognises music genre', 'recognizes the genre of music', 'labels music by genre', 'labels songs by genre', 'tags music by genre', 'assigns a genre to music', 'assigns genres to songs', 'determines music genre', 'determines the genre of a song', 'determines song genre', 'detects musical genre', 'identifies musical genre', 'predicts musical genre', 'classifies musical genre', 'classifies music into genres', 'sorts music by genre', 'categorizes music by genre', 'categorises music by genre', 'groups music by genre', 'genre detection', 'genre identification', 'automatic genre classification')
EXPECTED_NEG = ('no music genre classification', 'does not classify music by genre', 'without music genre classification', 'does not detect music genre', 'does not identify music genre', 'does not predict music genre', 'does not classify songs by genre', 'does not classify audio by genre', 'does not detect song genre', 'does not identify song genre', 'does not predict song genre', 'no genre classification', 'does not classify music genre', 'does not detect the genre of music', 'does not identify the genre of music', 'does not predict the genre of a song', 'does not determine music genre', 'does not determine song genre', 'does not label music by genre', 'does not tag music by genre', 'music genre classification not supported', 'genre classification not supported', 'no genre detection', 'does not detect musical genre')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            status = main([str(self.root), *args])
        return status, out.getvalue()

    def test_phrase_oracle(self):
        path = Path(__file__).resolve().parents[1] / 'genre_classification_claim_audit/phrases.py'
        literals = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(path.read_text()).body if isinstance(n, ast.Assign)}
        self.assertEqual(literals['GENRE'], EXPECTED_POS)
        self.assertEqual(literals['NOGENRE'], EXPECTED_NEG)
        self.assertEqual(GENRE, EXPECTED_POS)
        self.assertEqual(NOGENRE, EXPECTED_NEG)
        self.assertEqual(len(GENRE), 50)
        self.assertEqual(len(NOGENRE), 24)
        for phrase in EXPECTED_POS:
            self.assertEqual(claims(phrase), (True, False), phrase)
        for phrase in EXPECTED_NEG:
            self.assertEqual(claims(phrase), (False, True), phrase)

    def test_good_bad_denial(self):
        self.put('README.md', 'music genre classification')
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(audit(self.root)['findings'], [{'id': 'documented-genre-classification-claim-false', 'severity': 'HIGH', 'message': 'Affirmative documentation lacks production call evidence.'}])
        self.put('app.py', 'engine.classify_genre(audio)')
        self.assertEqual(self.cli()[0], 0)
        self.put('README.md', 'no music genre classification')
        self.assertEqual(self.cli()[0], 2)
        finding = audit(self.root)['findings'][0]
        self.assertEqual(finding['id'], 'documented-no-genre-classification-claim-false')
        self.assertEqual(finding['severity'], 'HIGH')

    def test_no_source_asymmetry(self):
        self.put('README.md', 'no music genre classification')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
        self.put('README.md', 'music genre classification')
        self.assertEqual(self.cli()[0], 2)
        self.put('README.md', 'A utility')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_test_only(self):
        self.put('README.md', 'music genre classification')
        for name in ['tests/helper.py', 'test_app.py', 'app_test.py']:
            with self.subTest(name=name):
                path = self.put(name, 'engine.detect_genre(x)')
                self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
                self.assertEqual(self.cli()[0], 0)
                self.assertEqual(self.cli('--fail-on', 'MEDIUM')[0], 2)
                path.unlink()

    def test_markdown(self):
        for fence in ['```', '~~~', '   ````']:
            self.assertEqual(claims(fence + '\nmusic genre classification\n' + fence), (False, False))
        self.assertEqual(claims('`music genre classification`'), (True, False))
        self.assertEqual(claims('MUSIC-GENRE   classification'), (True, False))
        self.assertEqual(claims("doesn't classify music by genre"), (False, True))
        self.assertEqual(claims('music genre\n\nclassification'), (False, False))
        self.assertEqual(claims('xmusic genre classificationx'), (False, False))
        self.put('nested/docs/page.md', 'music genre classification')
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli('--ignore', 'nested')[0], 0)
        self.put('other.md', 'music genre classification')
        self.assertEqual(self.cli('--ignore', 'nested')[0], 0)

    def test_every_generic_route_and_alias(self):
        for operation in GENERIC:
            for code in ['engine.' + operation + '(x)', 'from lib import ' + operation + '\n' + operation + '(x)', 'from lib import ' + operation + ' as op\nop(x)', 'import lib as q\nq.' + operation + '(x)']:
                with self.subTest(code=code):
                    self.assertTrue(evidence(code))
            self.assertFalse(evidence(operation + '(x)'))
            self.assertFalse(evidence('def ' + operation + '(x): pass\nengine.' + operation + '(x)'))
            self.assertFalse(evidence('from lib import ' + operation + ' as op\ndef op(x): pass\nop(x)'))

    def test_classifier_routes(self):
        for cls in ['GenreClassifier', 'MusicGenreClassifier', 'SongGenreClassifier', 'AudioGenreClassifier']:
            for code in [f'c = {cls}()\nc.predict(x)', f'{cls}().predict(x)', f'c = lib.{cls}()\nc.predict(x)', f'from lib import {cls} as C\nc = C()\nc.predict(x)', f'from lib import {cls} as C\nC().predict(x)', f'c: object = {cls}()\nc.predict(x)']:
                self.assertTrue(evidence(code), code)
            self.assertFalse(evidence(f'class {cls}: pass\nc = lib.{cls}()\nc.predict(x)'))
            self.assertFalse(evidence(f'def {cls}(): pass\n{cls}().predict(x)'))
        self.assertTrue(evidence('def predict(x): pass\nc = GenreClassifier()\nc.predict(x)'))
        self.assertFalse(evidence('from lib import GenreClassifier as C\nclass C: pass\nC().predict(x)'))

    def test_not_evidence(self):
        cases = [
            'import genre', 'from genre import GenreClassifier',
            'librosa.load(x)', 'soundfile.read(x)', 'wave.open(x).readframes(2)', 'torchaudio.load(x)',
            'mic.listen(x)', 'sounddevice.rec(100)', 'pyaudio.PyAudio().open().read(2)', 'audio.play(x)',
            'whisper.transcribe(x)', 'engine.recognize_google(x)', 'engine.stt(x)', 'engine.say(x)',
            'webrtcvad.Vad().is_speech(x)', 'silero.get_speech_timestamps(x)', 'pyannote.segmentation(x)',
            'pvporcupine.create()', 'm = openwakeword.Model(); m.predict(x)', 'e.detect_keyword(x)',
            'speechbrain.verify_files(x, y)', 'resemblyzer.VoiceEncoder().embed_utterance(x)', 'e.verify_speaker(x)',
            'pyannote.Pipeline.from_pretrained("diarization")(x)', 'e.diarize(x)',
            'noisereduce.reduce_noise(x)', 'df.enhance(x)', 'e.suppress_noise(x)', 'e.remove_noise(x)',
            'acoustid.fingerprint_file(x)', 'd = Dejavu(); d.recognize(x)', 'e.fingerprint_audio(x)',
            'm = PANNs.AudioTagging(); m.inference(x)', 'YAMNet()(x)', 'e.detect_sound_event(x)',
            'demucs.separate(x)', 's = spleeter.Separator(); s.separate(x)', 'e.separate_stems(x)',
            'librosa.beat.beat_track(x)', 'librosa.feature.tempo(x)', 'aubio.tempo()(x)', 'essentia.RhythmExtractor()(x)', 'e.detect_beats(x)',
            'librosa.piptrack(x)', 'librosa.yin(x)', 'crepe.predict(x)', 'aubio.pitch()(x)', 'x.to_pitch()', 'e.detect_pitch(x)',
            'librosa.onset.onset_detect(x)', 'librosa.onset.onset_strength(x)', 'e.detect_onsets(x)',
            'librosa.feature.chroma_cqt(x)', 'librosa.feature.chroma_cens(x)', 'librosa.feature.chroma_stft(x)', 'librosa.feature.mfcc(x)', 'librosa.feature.spectral_centroid(x)', 'essentia.Chromagram()(x)', 'librosa.feature.zero_crossing_rate(x)',
            'essentia.ChordsDetection()(x)', 'essentia.ChordsDetectionBeats()(x)', 'e.detect_chords(x)',
            'essentia.KeyExtractor()(x)', 'e.detect_key(x)', 'basic_pitch.predict(x)',
            'p = PianoTranscription(); p.transcribe(x)', 'e.transcribe_music(x)', 'e.audio_to_midi(x)', 'e.detect_notes(x)',
            'e.generate_audio(x)', 'e.synthesize(x)', 'e.detect_instrument(x)', 'e.identify_instrument(x)',
            'e.detect_mood(x)', 'e.recognize_emotion(x)', 'e.tag_audio(x)', 'model.predict(x)', 'model.forward(x)', 'e.classify(x)',
            'pipeline("audio-classification")(x)', 'pretty_midi.PrettyMIDI(); pretty_midi.Instrument(0); pretty_midi.Note(1,2,3,4)',
            'music21.Note(x); music21.Stream(x); music21.Part(x)', 'music21.Stream(x).show()', 'verovio.toolkit().renderToSVG()',
            'hashlib.md5(data)', 'hashlib.sha256(data)', 'e.filter(x)', 'e.equalize(x)', 'e.mix(x)', 'e.normalize(x)',
            'e.detect_language(x)', 'e.translate(x)', 'import musicgenre',
            'c = GenreClassifier()', 'OtherClassifier().predict(x)', 'c = GenreClassifier(); other.predict(x)',
            'subprocess.run(["genre-cli", x])', 'x = "lib.classify_genre(x)"', 'engine.classify_genre', 'not valid python!',
            'class Engine:\n def classify_genre(self, x): pass\nengine.classify_genre(x)',
        ]
        for code in cases:
            with self.subTest(code=code):
                self.assertFalse(evidence(code))

    def test_single_module(self):
        self.put('README.md', 'music genre classification')
        self.put('first.py', 'c = GenreClassifier()')
        self.put('second.py', 'c.predict(x)')
        self.assertEqual(self.cli()[0], 2)
        self.put('first.py', 'from lib import classify_genre')
        self.put('second.py', 'classify_genre(x)')
        self.assertEqual(self.cli()[0], 2)

    def test_exclusions_and_symlinks(self):
        self.put('README.md', 'music genre classification')
        for name in ['fixtures/app.py', 'docs/app.py', 'examples/app.py']:
            self.put(name, 'e.classify_genre(x)')
        external = self.put('ignored/app.py', 'e.classify_genre(x)')
        (self.root / 'link.py').symlink_to(external)
        (self.root / 'linked').symlink_to(external.parent, target_is_directory=True)
        self.assertEqual(self.cli('--ignore', 'ignored')[0], 2)
        self.put('app.py', 'e.classify_genre(x)')
        self.assertEqual(self.cli('--ignore', 'app.py', '--ignore', 'ignored')[0], 2)
        self.assertEqual(self.cli('--ignore', 'app', '--ignore', 'ignored')[0], 0)

    def test_json_verbose_errors(self):
        self.put('README.md', 'music genre classification')
        status, output = self.cli('--json')
        result = json.loads(output)
        self.assertEqual(status, 2)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertTrue(result['findings'][0]['message'])
        self.assertIn('production_evidence', self.cli('--verbose')[1])
        self.assertEqual(self.cli('--fail-on', 'WRONG')[0], 1)
        self.assertEqual(self.cli('--unknown')[0], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.root / 'missing')]), 1)
            self.assertEqual(main([]), 1)
        (self.root / 'README.md').write_bytes(b'\xff')
        self.assertEqual(self.cli()[0], 1)

    def test_entry_points(self):
        result = subprocess.run([sys.executable, '-m', 'genre_classification_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), '0.1.0')
        project = Path(__file__).resolve().parents[1]
        self.assertIn('genre-classification-claim-audit = "genre_classification_claim_audit.audit:main"', (project / 'pyproject.toml').read_text())

    def test_self_audit_readme(self):
        project = Path(__file__).resolve().parents[1]
        text = (project / 'README.md').read_text()
        self.assertEqual(claims(text), (False, False))
        self.assertEqual(audit(project)['verdict'], 'PASS')


if __name__ == '__main__':
    unittest.main()
