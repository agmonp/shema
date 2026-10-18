# -*- coding: utf-8 -*-
r"""asr_engine.py -- audio -> timed Hebrew words, the way production does it (home_analyze.Brain.transcribe calls this,
and so does the benchmark, so both always run the same code).

config.json "asr" (every key optional; nothing set = the behaviour before ASR 2.0):
  "mode":            "legacy"      the production model on every window (default)
                     "large_only"  the secondary model on every window instead (comparison)
                     "dual_test"   both models on every window; the primary's words are kept, the other reading is traced
                     "adaptive"    the primary everywhere; suspicious windows are decoded again by the secondary and
                                   the better-supported reading is kept (asr_quality.choose)
  "segmentation":    a preset of asr_segment.PRESETS ("legacy", "pad05", "pad08", "merge", "overlap", "short")
  "seg":             single overrides, e.g. {"pad": 0.5}
  "secondary_model": default ivrit-ai/whisper-large-v3-ct2 (must be installed first: asr_models.py --install)
  "keep_secondary":  "auto" | "always" | "never"
  "retry_pad":       extra seconds of context around a window decoded again (default 0.5)
  "retry_source":    "raw" = the recording as heard (default), "same" = the signal the primary saw (Demucs output)
  "quality":         limits for asr_quality.flags
  "mark_uncertain":  true (default): flags are stored with the utterance; the transcript itself does not change

The words are always [[start s, end s, text], ...]; the trace says, per window, which model's reading was kept and why.
"""
import os
import time

import numpy as np

import asr_quality as Q
import asr_segment as S
from asr_models import PRIMARY, SECONDARY, Models, is_oom, log

SR = 16000
# Decoding knobs. The defaults are production; the environment overrides exist for asr_bench experiments only
# ("+beam=8", "+keeplp=-1.0", "+nsp=0.8" in a bench system name) and are never set by the server.
BEAM = int(os.getenv("SHEMA_ASR_BEAM") or 5)
KEEP_LOGPROB = float(os.getenv("SHEMA_ASR_KEEP_LP") or -1.2)       # a segment below this mean log-probability is dropped
KEEP_NOSPEECH = float(os.getenv("SHEMA_ASR_NOSPEECH") or 0.6)      # ... or above this no-speech probability
SPKCUT = float(os.getenv("SHEMA_ASR_SPKCUT") or 0)    # >0: cut speech regions where the voice changes (asr_segment)
MODES = ("legacy", "large_only", "dual_test", "adaptive")

# Whisper writes these on silence / noise (subtitle credits in its training data).
HALLUCINATIONS = {"תודה רבה", "תודה", "תודה רבה לכם", "תודה רבה לצפייה", "תודה שצפיתם", "תודה על הצפייה",
                  "כתוביות", "תרגום", "מתורגמן", "שבת שלום", "thank you", "thanks for watching", "you"}


def hallucination(text):
    import re
    t = re.sub(r"[‏‪-‮.,!?״\"' ]+", " ", text).strip().lower()
    return t in HALLUCINATIONS


def settings(cfg):
    a = dict(cfg.get("asr") or {})
    mode = a.get("mode") if a.get("mode") in MODES else "legacy"
    return {"mode": mode,
            "primary": cfg.get("whisper_model") or PRIMARY,
            "secondary": a.get("secondary_model") or SECONDARY,
            "seg_name": a.get("segmentation") or "legacy",
            "seg": S.settings(a.get("segmentation"), a.get("seg")),
            "keep": a.get("keep_secondary") or "auto",
            "retry_pad": float(a.get("retry_pad", 0.5)),
            "retry_source": a.get("retry_source") or "raw",
            "limits": Q.limits(a.get("quality")),
            "mark": a.get("mark_uncertain", True) is not False}


class Engine:
    def __init__(self, cfg, device, compute=None, models=None, vad_cfg=None):
        self.st = settings(cfg)
        self.models = models or Models(device, compute, keep=self.st["keep"])
        self._vad_cfg = vad_cfg
        self.trace = None

    @property
    def model_name(self):
        return self.st["secondary"] if self.st["mode"] == "large_only" else self.st["primary"]

    def _spk_embed(self):
        if getattr(self, "_spk", None) is None:
            import voice_embed as VE
            ex = VE.load_extractors(["eres2netv2"])["eres2netv2"]
            self._spk = lambda wave: VE.embed(ex, wave)
        return self._spk

    def mask(self, audio):
        import voice_embed as VE
        if self._vad_cfg is None:
            self._vad_cfg = VE.make_vad()
        return VE.voiced_mask(self._vad_cfg, audio)

    def _decode(self, model_name, clip, prompt):
        m = self.models.get(model_name)
        segs, _ = m.transcribe(clip, vad_filter=False, beam_size=BEAM, word_timestamps=True,
                               condition_on_previous_text=False, language="he", initial_prompt=prompt)
        return list(segs)          # the generator decodes lazily: materialise here so errors surface here

    def _read(self, model_name, audio, a0, b0, prompt, win):
        """One model on one slice -> candidate {"model", "words", "sig", "flags"} (production keep-filter applied)."""
        t = time.time()
        segs = self._decode(model_name, audio[a0:b0], prompt)
        off = a0 / SR
        words = []
        for s in segs:
            if s.no_speech_prob < KEEP_NOSPEECH and s.avg_logprob > KEEP_LOGPROB and not hallucination(s.text):
                for w in (s.words or []):
                    ww = [round(w.start + off, 2), round(w.end + off, 2), w.word]
                    if S.owns(win, ww):
                        words.append(ww)
            else:
                try:
                    s._dropped = True
                except AttributeError:
                    pass
        sig = Q.window_signals(segs, (win["b"] - win["a"]) / SR, words)
        return {"model": model_name, "words": words, "sig": sig, "flags": Q.flags(sig, self.st["limits"]),
                "took": round(time.time() - t, 2)}

    def transcribe(self, audio, prompt=None, raw=None, mask=None):
        """-> (words, trace). raw = the recording before music removal (used for the adaptive second reading)."""
        st, mode = self.st, self.st["mode"]
        if mask is None:
            mask = self.mask(S.vad_view(audio) if st["seg"]["vad_norm"] else audio)
        regions = S.regions_from_mask(mask, st["seg"]["merge_gap"], st["seg"]["max_merge"])
        if SPKCUT > 0:
            regions = S.split_regions(audio, regions, self._spk_embed(), SPKCUT)
        wins = S.windows(regions, len(audio), st["seg"])
        first = self.model_name
        words, trace = [], {"mode": mode, "segmentation": st["seg_name"], "primary": first, "windows": [],
                            "events": self.models.events}
        retry_src = raw if (raw is not None and st["retry_source"] == "raw" and len(raw) == len(audio)) else audio
        for win in wins:
            p = self._read(first, audio, win["a0"], win["b0"], prompt, win)
            chosen, reason, uncertain, second = p, None, bool(p["flags"]), None
            if mode == "dual_test" or (mode == "adaptive" and p["flags"]):
                rp = int(st["retry_pad"] * SR)
                src = retry_src if mode == "adaptive" else audio
                a0, b0 = max(0, win["a0"] - rp), min(len(audio), win["b0"] + rp)
                # the wider slice may reach a neighbour's words: ownership keeps only this window's span
                w2 = dict(win, lo=win["lo"] if win["lo"] is not None else (win["a0"] / SR),
                          hi=win["hi"] if win["hi"] is not None else (win["b0"] / SR))
                try:
                    second = self._read(st["secondary"], src, a0, b0, prompt, w2)
                except Exception as exc:  # noqa: BLE001
                    self.models.events.append(f"secondary failed: {exc!r}"[:200])
                    if is_oom(exc):
                        self.models.unload_all(keep=first)
                    log(self.models.events[-1])
                    second = None
                if mode == "adaptive":
                    chosen, reason, uncertain = Q.choose(p, second, st["limits"])
                else:
                    reason = "dual_test: primary kept"
            words += chosen["words"]
            trace["windows"].append({
                "t0": round(win["a"] / SR, 2), "t1": round(win["b"] / SR, 2), "model": chosen["model"],
                "flags": p["flags"], "uncertain": uncertain, "reason": reason,
                "sig": {k: v for k, v in p["sig"].items() if k != "text"},
                "primary_text": p["sig"]["text"], "took": p["took"],
                **({"secondary_text": second["sig"]["text"], "secondary_flags": second["flags"],
                    "secondary_took": second["took"]} if second else {})})
        if mode in ("adaptive", "dual_test"):
            self.models.release(st["secondary"])
        if st["seg"]["own"] or mode == "adaptive":
            words = S.reconcile(words)
        self.trace = trace
        return words, trace


def utterance_info(u, trace):
    """The trace windows that overlap utterance u -> {"models": [...], "uncertain": bool, "flags": [...]}."""
    if not trace:
        return None
    ws = [w for w in trace["windows"] if w["t0"] < u["t1"] + 0.3 and u["t0"] - 0.3 < w["t1"]]
    if not ws:
        return None
    flags = sorted({f for w in ws for f in w["flags"]})
    return {"models": sorted({w["model"] for w in ws}), "uncertain": any(w["uncertain"] for w in ws),
            "flags": flags, "mode": trace["mode"]}
