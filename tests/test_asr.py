# -*- coding: utf-8 -*-
"""ASR 2.0 tests: no models, no audio files from users. A fake Whisper reads an "oracle" of known words from the
sample positions it is given, so segmentation, ownership, retries and fallbacks can be checked exactly."""
import json
import random
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import asr_correct as C  # noqa: E402
import asr_engine as E  # noqa: E402
import asr_metrics as M  # noqa: E402
import asr_quality as Q  # noqa: E402
import asr_segment as S  # noqa: E402
from asr_models import Models  # noqa: E402

SR = 16000


def oracle_audio(seconds):
    """audio[i] = i * 1e-6: the fake model recovers where its slice starts."""
    return (np.arange(int(seconds * SR)) * 1e-6).astype(np.float32)


class FakeWhisper:
    """Returns the oracle words that overlap the slice (cut at the slice edges, like a word half in the audio).
    quality(t0, t1) -> (avg_logprob, no_speech_prob, compression_ratio, text_override or None)."""

    def __init__(self, words, quality=None, fail=None):
        self.words, self.quality, self.fail, self.calls = words, quality, fail, []

    def transcribe(self, clip, **kw):
        if self.fail:
            raise self.fail
        start = round(float(clip[0]) * 1e6) / SR if len(clip) else 0.0
        end = start + len(clip) / SR
        self.calls.append((round(start, 2), round(end, 2), kw.get("initial_prompt")))
        ws = [SimpleNamespace(start=max(a, start) - start, end=min(b, end) - start, word=" " + t)
              for a, b, t in self.words if b > start and a < end]
        lp, ns, cr, override = (self.quality(start, end) if self.quality else (-0.3, 0.05, 1.4, None))
        if override is not None:
            ws = [SimpleNamespace(start=w.start, end=w.end, word=" " + override) for w in ws]
        text = "".join(w.word for w in ws)
        seg = SimpleNamespace(start=0.0, end=len(clip) / SR, text=text, words=ws, avg_logprob=lp,
                              no_speech_prob=ns, compression_ratio=cr)
        return iter([seg] if ws else []), None


def legacy_reference(model, audio, mask, prompt=None):
    """home_analyze.Brain.transcribe as it was before ASR 2.0 (copied verbatim, VAD replaced by the given mask)."""
    edges = np.flatnonzero(np.diff(np.r_[0, mask.astype(np.int8), 0]))
    regions = []
    for a, b in zip(edges[::2], edges[1::2]):
        if regions and a - regions[-1][1] < 0.4 * SR and b - regions[-1][0] < 15 * SR:
            regions[-1][1] = b
        else:
            regions.append([a, b])
    words, pad = [], int(0.2 * SR)
    for a, b in regions:
        if b - a < 0.25 * SR:
            continue
        a0 = max(0, a - pad)
        segs, _ = model.transcribe(audio[a0:b + pad], vad_filter=False, beam_size=5, word_timestamps=True,
                                   condition_on_previous_text=False, language="he", initial_prompt=prompt)
        off = a0 / SR
        for s in segs:
            if s.no_speech_prob < 0.6 and s.avg_logprob > -1.2 and not E.hallucination(s.text):
                words += [[round(w.start + off, 2), round(w.end + off, 2), w.word] for w in (s.words or [])]
    return words


def random_talk(seed, seconds=60.0):
    """Words of 0.15-0.7 s with pauses of 0.05-1.5 s; the mask covers each word (like Silero)."""
    rng = random.Random(seed)
    words, t, i = [], 0.3, 0
    while t < seconds - 2:
        d = rng.uniform(0.15, 0.7)
        words.append((round(t, 3), round(t + d, 3), f"w{i}"))
        t += d + (rng.uniform(0.05, 0.25) if rng.random() < 0.8 else rng.uniform(0.4, 1.5))
        i += 1
    mask = np.zeros(int(seconds * SR), bool)
    for a, b, _ in words:
        mask[int(a * SR):int(b * SR)] = True
    return words, mask


def engine(cfg, models_map, device="cuda"):
    def factory(name, dev, compute):
        m = models_map.get((name, dev)) or models_map.get(name)
        if isinstance(m, Exception):
            raise m
        if m is None:
            raise FileNotFoundError(name)
        return m
    return E.Engine(cfg, device, models=Models(device, keep="never", factory=factory))


class SegmentationTests(unittest.TestCase):
    def test_legacy_mode_equals_old_code(self):
        for seed in range(8):
            words, mask = random_talk(seed)
            audio = oracle_audio(60)
            ref = legacy_reference(FakeWhisper(words), audio, mask, prompt="ניר, שמע")
            got, trace = engine({}, {E.PRIMARY: FakeWhisper(words)}).transcribe(audio, prompt="ניר, שמע", mask=mask)
            self.assertEqual(ref, got, seed)
            self.assertEqual(trace["mode"], "legacy")

    def test_no_word_stored_twice_with_context_or_overlap(self):
        for preset in ("pad05", "pad08", "merge", "overlap", "short"):
            for seed in range(6):
                words, mask = random_talk(100 + seed)
                audio = oracle_audio(60)
                cfg = {"asr": {"segmentation": preset}}
                got, _ = engine(cfg, {E.PRIMARY: FakeWhisper(words)}).transcribe(audio, mask=mask)
                texts = [w[2].strip() for w in got]
                self.assertEqual(len(texts), len(set(texts)), (preset, seed))
                kept = S.windows(S.regions_from_mask(mask, S.PRESETS[preset]["merge_gap"],
                                                     S.PRESETS[preset]["max_merge"]), len(audio), S.PRESETS[preset])
                expect = {t for a, b, t in words if any(w["a"] / SR <= a and b <= w["b"] / SR + 1e-6 for w in kept)}
                self.assertTrue(expect <= set(texts), (preset, seed, sorted(expect - set(texts))[:5]))

    def test_timestamps_are_absolute(self):
        words, mask = random_talk(7)
        for preset in ("legacy", "pad08", "overlap"):
            got, _ = engine({"asr": {"segmentation": preset}}, {E.PRIMARY: FakeWhisper(words)}).transcribe(
                oracle_audio(60), mask=mask)
            truth = {t: (a, b) for a, b, t in words}
            for a, b, t in got:
                ta, tb = truth[t.strip()]
                self.assertGreaterEqual(a, ta - 0.011)
                self.assertLessEqual(b, tb + 0.011)

    def test_long_region_is_split_into_overlapping_windows(self):
        mask = np.ones(50 * SR, bool)
        wins = S.windows(S.regions_from_mask(mask, 0.8, 28), len(mask), S.PRESETS["overlap"])
        self.assertGreater(len(wins), 2)
        for w1, w2 in zip(wins, wins[1:]):
            self.assertLess(w2["a"], w1["b"])                  # pieces overlap
            self.assertAlmostEqual(w1["hi"], w2["lo"])          # ownership touches, never overlaps

    def test_short_answers_dropped_by_legacy_kept_by_short(self):
        words = [(1.0, 1.15, "כן"), (5.0, 5.6, "בסדר")]
        mask = np.zeros(8 * SR, bool)
        for a, b, _ in words:
            mask[int(a * SR):int(b * SR)] = True
        legacy, _ = engine({}, {E.PRIMARY: FakeWhisper(words)}).transcribe(oracle_audio(8), mask=mask)
        short, _ = engine({"asr": {"segmentation": "short"}}, {E.PRIMARY: FakeWhisper(words)}).transcribe(
            oracle_audio(8), mask=mask)
        self.assertEqual([w[2].strip() for w in legacy], ["בסדר"])
        self.assertEqual([w[2].strip() for w in short], ["כן", "בסדר"])

    def test_reconcile_drops_only_true_repeats(self):
        w = [[1.0, 1.4, " שלום"], [1.05, 1.42, "שלום"], [1.1, 1.5, " מה"], [3.0, 3.3, " שלום"]]
        self.assertEqual([x[2] for x in S.reconcile(w)], [" שלום", " מה", " שלום"])

    def test_silence_only_gives_nothing(self):
        got, trace = engine({"asr": {"mode": "adaptive"}}, {E.PRIMARY: FakeWhisper([]), E.SECONDARY: FakeWhisper([])}) \
            .transcribe(np.zeros(10 * SR, np.float32), mask=np.zeros(10 * SR, bool))
        self.assertEqual(got, [])
        self.assertEqual(trace["windows"], [])


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.words = [(1.0, 1.5, "אני"), (1.6, 2.2, "בבית"), (6.0, 6.5, "ניר"), (6.6, 7.4, "התקשר")]
        self.mask = np.zeros(10 * SR, bool)
        for a, b, _ in self.words:
            self.mask[int(a * SR):int(b * SR)] = True

    def bad_second_window(self, start, end):
        return (-1.1, 0.1, 1.5, "בלה") if start > 4 else (-0.2, 0.05, 1.4, None)

    def test_adaptive_retries_only_flagged_windows_and_keeps_trace(self):
        prim = FakeWhisper(self.words, self.bad_second_window)
        sec = FakeWhisper(self.words)
        got, trace = engine({"asr": {"mode": "adaptive"}}, {E.PRIMARY: prim, E.SECONDARY: sec}).transcribe(
            oracle_audio(10), mask=self.mask)
        self.assertEqual([w[2].strip() for w in got], ["אני", "בבית", "ניר", "התקשר"])
        self.assertEqual(len(sec.calls), 1)
        w2 = trace["windows"][1]
        self.assertEqual(w2["model"], E.SECONDARY)
        self.assertIn("low_logprob", w2["flags"])
        self.assertEqual(trace["windows"][0]["model"], E.PRIMARY)

    def test_retry_uses_original_audio_with_more_context(self):
        sec = FakeWhisper(self.words)
        eng = engine({"asr": {"mode": "adaptive"}}, {E.PRIMARY: FakeWhisper(self.words, self.bad_second_window),
                                                     E.SECONDARY: sec})
        raw = oracle_audio(10)
        filtered = raw.copy()
        eng.transcribe(filtered, mask=self.mask, raw=raw)
        a, b, _ = sec.calls[0]
        self.assertAlmostEqual(a, 6.0 - 0.2 - 0.5, places=2)
        self.assertAlmostEqual(b, 7.4 + 0.2 + 0.5, places=2)

    def test_secondary_missing_keeps_primary_and_marks_uncertain(self):
        got, trace = engine({"asr": {"mode": "adaptive"}}, {E.PRIMARY: FakeWhisper(self.words, self.bad_second_window)}) \
            .transcribe(oracle_audio(10), mask=self.mask)
        self.assertEqual([w[2].strip() for w in got], ["אני", "בבית", "בלה", "בלה"])
        self.assertTrue(trace["windows"][1]["uncertain"])
        self.assertTrue(any("secondary failed" in e for e in trace["events"]))

    def test_secondary_out_of_memory_is_survived(self):
        oom = FakeWhisper(self.words, fail=RuntimeError("CUDA failed with error out of memory"))
        eng = engine({"asr": {"mode": "adaptive"}}, {E.PRIMARY: FakeWhisper(self.words, self.bad_second_window),
                                                     E.SECONDARY: oom})
        got, trace = eng.transcribe(oracle_audio(10), mask=self.mask)
        self.assertEqual(len(got), 4)
        self.assertNotIn(E.SECONDARY, eng.models.loaded)
        self.assertEqual(list(eng.models.loaded), [E.PRIMARY])

    def test_cuda_unavailable_falls_back_to_cpu(self):
        eng = engine({}, {(E.PRIMARY, "cuda"): RuntimeError("CUDA driver version is insufficient"),
                          (E.PRIMARY, "cpu"): FakeWhisper(self.words)})
        got, _ = eng.transcribe(oracle_audio(10), mask=self.mask)
        self.assertEqual(len(got), 4)
        self.assertEqual(eng.models.where[E.PRIMARY], "cpu/int8")

    def test_large_only_and_dual_test(self):
        prim, sec = FakeWhisper(self.words), FakeWhisper(self.words)
        engine({"asr": {"mode": "large_only"}}, {E.PRIMARY: prim, E.SECONDARY: sec}).transcribe(oracle_audio(10), mask=self.mask)
        self.assertEqual((len(prim.calls), len(sec.calls)), (0, 2))
        prim, sec = FakeWhisper(self.words, self.bad_second_window), FakeWhisper(self.words)
        got, trace = engine({"asr": {"mode": "dual_test"}}, {E.PRIMARY: prim, E.SECONDARY: sec}).transcribe(
            oracle_audio(10), mask=self.mask)
        self.assertEqual(len(sec.calls), 2)
        self.assertEqual([w[2].strip() for w in got][2:], ["בלה", "בלה"])          # dual_test never changes the output
        self.assertEqual(trace["windows"][1]["secondary_text"].split(), ["ניר", "התקשר"])

    def test_noisy_window_both_bad_stays_uncertain_without_mixing(self):
        bad = lambda s, e: (-1.15, 0.5, 2.6, "חרא")   # noqa: E731
        got, trace = engine({"asr": {"mode": "adaptive"}}, {E.PRIMARY: FakeWhisper(self.words, bad),
                                                            E.SECONDARY: FakeWhisper(self.words, bad)}) \
            .transcribe(oracle_audio(10), mask=self.mask)
        self.assertTrue(all(w["uncertain"] for w in trace["windows"]))
        self.assertTrue(all(w["model"] == E.PRIMARY for w in trace["windows"]))


class QualityTests(unittest.TestCase):
    def test_repetition(self):
        self.assertTrue(Q.repetition("כן כן כן"))
        self.assertTrue(Q.repetition("אני הולך אני הולך אני הולך הביתה"))
        self.assertFalse(Q.repetition("כן כן, בסדר גמור"))

    def test_flags_and_choose(self):
        seg = SimpleNamespace(start=0, end=2, avg_logprob=-0.2, no_speech_prob=0.05, compression_ratio=1.3)
        good = Q.window_signals([seg], 2.0, [[0, 0.5, " שלום"], [0.6, 1.0, " לך"]])
        self.assertEqual(Q.flags(good), [])
        empty = Q.window_signals([], 2.0, [])
        self.assertEqual(Q.flags(empty), ["empty"])
        p = {"model": "p", "sig": dict(empty), "flags": ["empty"], "words": []}
        s = {"model": "s", "sig": dict(good), "flags": [], "words": [[0, 1, "x"]]}
        chosen, _, unc = Q.choose(p, s)
        self.assertEqual((chosen["model"], unc), ("s", False))
        chosen, reason, unc = Q.choose(dict(p, sig=dict(good, text="שלום לך"), flags=["low_logprob"]),
                                       dict(s, sig=dict(good, text="שלום לך")))
        self.assertTrue(reason.startswith("agree"))
        self.assertEqual(chosen["model"], "p")


class MetricsTests(unittest.TestCase):
    def test_wer_parts(self):
        c = M.wer_counts("אני הולך הביתה עכשיו", "אני הלך הביתה עכשיו מהר")
        self.assertEqual((c["S"], c["D"], c["I"], c["N"]), (1, 0, 1, 4))
        c = M.wer_counts("אני הולך הביתה", "אני")
        self.assertEqual((c["D"], c["N"]), (2, 3))

    def test_normalisation_is_lenient_and_identical_for_all(self):
        self.assertEqual(M.DEFAULT.text("שָׁלוֹם, עולם!"), M.DEFAULT.text("שלום עולמ"))
        self.assertEqual(M.DEFAULT.text('צה"ל'), M.DEFAULT.text("צהל"))
        self.assertEqual(M.DEFAULT.text("‏תל-אביב"), "תל אביב")
        self.assertEqual(M.rate(M.wer_counts("", "")), 0.0)
        self.assertEqual(M.rate(M.wer_counts("", "תודה")), 1.0)

    def test_aliases_and_strict_terms(self):
        n = M.Norm(aliases={"וואטסאפ": ["ווטסאפ", "whatsapp"]})
        self.assertEqual(M.rate(M.wer_counts("שלחתי בוואטסאפ", "שלחתי בווטסאפ", n)), 0.0)
        th = M.term_hits("ניר שלח 25 קבצים ב-Slack", "ניר שלח 26 קבצים בסלאק", terms=["ניר"])
        self.assertEqual(th["entities"], [1, 1])
        self.assertEqual(th["numbers"], [0, 1])
        self.assertEqual(th["latin"], [0, 1])

    def test_timestamps_and_coverage(self):
        ts = M.timestamp_issues([[0, 0.5, "a"], [0.3, 0.6, "b"], [1, 5, "c"], [6, 5.5, "d"]], audio_s=5.0)
        self.assertEqual((ts["overlap"], ts["too_long"], ts["backwards"], ts["outside"]), (1, 1, 1, 1))
        self.assertAlmostEqual(M.coverage([[1, 2, "x"]], [[1, 3]], tol=0), 0.5)


class CorrectionTests(unittest.TestCase):
    cfg = {"asr_terms": ["ניר"],
           "asr_glossary": [{"term": "WhatsApp", "variants": ["וואטסאפ", "ווטסאפ"], "kind": "company"},
                            {"term": "תל השומר", "variants": ["תל שומר"], "kind": "place"},
                            {"term": "Tailscale", "kind": "tech"},
                            {"term": "אין", "variants": ["לא"]}, {"term": "חמש", "variants": ["5"]}],
           "asr": {"correct": {"enabled": True}}}

    def test_off_by_default(self):
        self.assertEqual(C.correct("שלחתי בוואטסאפ", {"asr_glossary": self.cfg["asr_glossary"]})[1], [])

    def test_variants_prefixes_case_and_log(self):
        new, ch, raw = C.correct("שלחתי לו בוואטסאפ , ואז tailscale נפל בתל שומר.", self.cfg)
        self.assertEqual(new, "שלחתי לו בWhatsApp, ואז Tailscale נפל בתל השומר.")
        self.assertEqual(raw, "שלחתי לו בוואטסאפ , ואז tailscale נפל בתל שומר.")
        self.assertEqual({c["rule"] for c in ch}, {"glossary", "case", "spacing"})

    def test_never_touches_negations_or_numbers(self):
        new, ch, _ = C.correct("לא היו 5 אנשים", self.cfg)
        self.assertEqual(new, "לא היו 5 אנשים")
        self.assertEqual(ch, [])
        self.assertTrue(C.check_entry({"term": "אין", "variants": ["לא"]}))

    def test_prompt_keeps_old_terms_first(self):
        self.assertEqual(C.prompt_terms(self.cfg)[:2], ["ניר", "WhatsApp"])
        self.assertEqual(C.prompt_terms({"asr_terms": ["a", "b"]}), ["a", "b"])

    def test_llm_only_says_yes_or_no(self):
        cfg = dict(self.cfg, asr={"correct": {"enabled": True, "llm": True}}, asr_glossary=[{"term": "דורית"}])
        new, ch, _ = C.correct("דיברתי עם דורות אתמול", cfg, ask=lambda p: '{"approve": [0]}')
        self.assertEqual(new, "דיברתי עם דורית אתמול")
        self.assertEqual(ch[0]["rule"], "llm")
        new, ch, _ = C.correct("דיברתי עם דורות אתמול", cfg, ask=lambda p: '{"approve": [5, "x"]}')
        self.assertEqual((new, ch), ("דיברתי עם דורות אתמול", []))

    def test_llm_unavailable_changes_nothing(self):
        def down(p):
            raise ConnectionError("ollama not running")
        cfg = dict(self.cfg, asr={"correct": {"enabled": True, "llm": True}}, asr_glossary=[{"term": "דורית"}])
        self.assertEqual(C.correct("דיברתי עם דורות", cfg, ask=down)[0], "דיברתי עם דורות")

    def test_ordinary_words_without_variants_are_left_alone(self):
        cfg = {"asr_glossary": [{"term": "ניר"}], "asr": {"correct": {"enabled": True}}}
        self.assertEqual(C.correct("קניתי נייר", cfg)[0], "קניתי נייר")


class PipelineTests(unittest.TestCase):
    def test_annotate_keeps_speaker_and_media(self):
        import home_analyze as HA
        U = [{"t0": 1.0, "t1": 2.0, "speaker": "owner", "text": "שלחתי בוואטסאפ", "media": None},
             {"t0": 3.0, "t1": 4.0, "speaker": None, "text": "", "media": "טלוויזיה", "media_text": "וואטסאפ"}]
        trace = {"mode": "adaptive", "windows": [{"t0": 0.9, "t1": 2.1, "model": E.SECONDARY, "flags": ["low_logprob"],
                                                  "uncertain": True}]}
        HA.asr_annotate(U, trace, cfg=dict(CorrectionTests.cfg))
        self.assertEqual((U[0]["speaker"], U[0]["text"], U[0]["text_raw"]), ("owner", "שלחתי בWhatsApp", "שלחתי בוואטסאפ"))
        self.assertTrue(U[0]["asr"]["uncertain"])
        self.assertEqual(U[0]["asr"]["models"], [E.SECONDARY])
        self.assertNotIn("asr", U[1])
        self.assertEqual(U[1]["media_text"], "וואטסאפ")

    def test_corrupt_and_empty_audio(self):
        import home_analyze as HA
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "x.ogg"
            bad.write_bytes(b"OggS-not-really")
            empty = Path(d) / "e.wav"
            empty.write_bytes(b"")
            for p in (bad, empty):
                r = HA.analyse(None, str(p))
                self.assertTrue(r["empty"])
                self.assertEqual(r["utterances"], [])

    def test_storage_keeps_raw_and_trace_and_deletion_still_works(self):
        import home_listener as server
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(server, HOME=root, DB=root / "t.sqlite", CONFIG=root / "config.json", AUDIO=root / "audio"):
                server.config()
                server.migrate()
                cid = server.store_chunk(b"test", "phone", "2026-10-15T10:00:00", "wav")
                with server.db() as db:
                    row = dict(db.execute("SELECT * FROM chunks WHERE id=?", (cid,)).fetchone())
                base = {"speaker": "p1", "name": "דנה", "prosody": {}, "emotion": {}, "dims": {}, "emb": None}
                server.save_analysis(row, datetime(2026, 10, 15, 10), {"sounds": [], "utterances": [
                    dict(base, t0=0, t1=2, text="שלחתי בWhatsApp", text_raw="שלחתי בוואטסאפ",
                         asr={"models": [E.PRIMARY], "uncertain": True, "flags": ["low_logprob"]}),
                    dict(base, t0=3, t1=4, text="בלי שינוי")]})
                with server.db() as db:
                    rows = [dict(r) for r in db.execute("SELECT text, text_raw, asr, speaker FROM utterances ORDER BY t0")]
                self.assertEqual(rows[0]["text_raw"], "שלחתי בוואטסאפ")
                self.assertTrue(json.loads(rows[0]["asr"])["uncertain"])
                self.assertIsNone(rows[1]["text_raw"])
                self.assertIsNone(rows[1]["asr"])
                server.set_optout("p1", True)
                with server.db() as db:
                    self.assertEqual(db.execute("SELECT count(*) FROM utterances").fetchone()[0], 0)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        import asr_update as U
        self.U = U
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = Path(self.dir.name) / "config.json"
        self.cfg.write_text(json.dumps({"whisper_model": "cur"}), encoding="utf-8")
        self.p = patch.multiple(U, CONFIG=self.cfg, gold_items=lambda: [{"x": 1}] * 50)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.dir.cleanup()

    @staticmethod
    def res(wer, words=400, by=None):
        return {"wer": wer, "words": words, "by_condition": by or {"home": {"wer": wer, "words": words}}, "at": "2026-10-15"}

    def test_gate(self):
        g = self.U.gate
        self.assertFalse(g(self.res(0.30, 100), self.res(0.10, 100))[0])               # too few words
        self.assertFalse(g(self.res(0.30), self.res(0.28))[0])                         # < 10 % better
        self.assertTrue(g(self.res(0.30), self.res(0.25))[0])
        cur = self.res(0.30, by={"home": {"wer": 0.30, "words": 300}, "car": {"wer": 0.20, "words": 100}})
        cand = self.res(0.25, by={"home": {"wer": 0.22, "words": 300}, "car": {"wer": 0.25, "words": 100}})
        ok, why = g(cur, cand)
        self.assertFalse(ok)
        self.assertIn("car", why)

    def test_nominated_old_model_evaluated_switch_and_rollback(self):
        self.U.nominate("old-but-good")
        wers = {"cur": self.res(0.30), "old-but-good": self.res(0.24)}
        with patch.object(self.U, "candidates", return_value=([], "")):
            r = self.U.run(force=True, evaluate_fn=lambda m, items: wers[m], installed_fn=lambda m: True)
        self.assertTrue(r.get("switched"))
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual((cfg["whisper_model"], cfg["whisper_model_prev"]), ("old-but-good", "cur"))
        self.assertEqual(cfg["asr_check"]["nominated"], [])
        rb = self.U.rollback()
        self.assertTrue(rb["ok"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(cfg["whisper_model"], "cur")
        self.assertEqual([s["why"] for s in cfg["asr_check"]["switches"]][-1], "rollback")

    def test_misses_never_switch_checks_off_and_nothing_is_downloaded(self):
        found = ([{"id": "new-ct2", "modified": "2027", "license": "apache-2.0"}], "")
        with patch.object(self.U, "candidates", return_value=found):
            for _ in range(5):
                r = self.U.run(force=True, evaluate_fn=lambda m, i: self.fail("must not evaluate"), installed_fn=lambda m: False)
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertTrue(cfg["asr_check"]["enabled"])
        self.assertEqual(r["not_installed"], [])                 # seen once: not re-proposed every time
        self.assertIn("new-ct2", cfg["asr_check"]["seen"])

    def test_newer_is_not_enough(self):
        found = ([{"id": "newer", "modified": "2027", "license": "apache-2.0"}], "")
        wers = {"cur": self.res(0.30), "newer": self.res(0.29)}
        with patch.object(self.U, "candidates", return_value=found):
            r = self.U.run(force=True, evaluate_fn=lambda m, i: wers[m], installed_fn=lambda m: True)
        self.assertFalse(r.get("switched"))
        self.assertEqual(json.loads(self.cfg.read_text(encoding="utf-8"))["whisper_model"], "cur")


class BenchTests(unittest.TestCase):
    def test_missing_gold_is_reported_not_crashing(self):
        import asr_bench as B
        self.assertEqual(B.gold_items(Path(tempfile.gettempdir()) / "no-such-gold-dir-xyz"), [])
        with patch.object(sys, "argv", ["asr_bench.py", "--gold-dir", str(Path(tempfile.gettempdir()) / "no-such-x")]):
            self.assertEqual(B.main(), 2)

    def test_gold_reader_and_score(self):
        import asr_bench as B
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "a.wav").write_bytes(b"RIFF")
            (p / "a.txt").write_text("ניר שלח 3 קבצים", encoding="utf-8")
            (p / "a.json").write_text(json.dumps({"condition": "car", "entities": ["ניר"]}), encoding="utf-8")
            (p / "b.wav").write_bytes(b"RIFF")                       # no reference: skipped
            items = B.gold_items(p)
        self.assertEqual([(i["id"], i["condition"]) for i in items], [("gold/a", "car")])
        row = {"condition": "car", "hyp": "ניר שלח שלושה קבצים", "words": [[0, 0.5, "ניר"]], "took_s": 1.0,
               "audio_s": 2.0, "flagged": 0, "uncertain": 0, "secondary_used": 0, "secondary_runs": 0}
        sc = B.score(items[0], row)
        self.assertEqual((sc["S"], sc["entities_hit"], sc["numbers_hit"], sc["numbers_n"]), (1, 1, 0, 1))

    def test_system_names(self):
        import asr_bench as B
        self.assertEqual(B.parse_system("adaptive+seg=pad05+demucs"),
                         {"name": "adaptive+seg=pad05+demucs", "mode": "adaptive", "seg": "pad05", "demucs": True})
        with self.assertRaises(SystemExit):
            B.parse_system("turbo-x")


if __name__ == "__main__":
    unittest.main()
