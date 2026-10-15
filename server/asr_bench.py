# -*- coding: utf-8 -*-
r"""asr_bench.py -- the same recordings through the production transcription, under several settings, scored the same way.

    python -X utf8 asr_bench.py --gold            [--systems legacy,adaptive] [--out DIR]
    python -X utf8 asr_bench.py --fleurs DIR      [--limit 200] [--concat 30] [--conditions clean,opus12,opus12+brown5]
    python -X utf8 asr_bench.py --gold-dir DIR    any folder of audio + .txt references (kept outside git)

Inputs (never committed: real recordings stay in the data folder or outside the repository)
  gold    <data>/gold/*.ogg|wav|opus|m4a|mp3 + same-name .txt (the /home screen's "add to gold set"), optional same-name
          .json: {"condition": "car", "entities": ["ניר"], "aliases": {"canon": ["variant"]}, "speech": [[t0, t1], ...],
          "silence": true}. gold/aliases.json = aliases for every item.
  fleurs  Google FLEURS Hebrew (CC-BY-4.0) folder with test.tsv and test/*.wav. --concat N joins sentences into ~N s
          recordings with short pauses, like a phone segment, so segmentation and boundaries are exercised.
  probes  always: synthetic silence and noise (no speech at all) -> how many words are invented.
Conditions (synthetic, applied to every item): clean | opus12 | opus24 | opus32 (ffmpeg libopus, 16 kHz mono, voip)
  and +pinkSNR / +brownSNR (brown = low rumble, a stand-in for a car; SNR in dB), e.g. opus12+brown5.
Systems: legacy | large_only | dual_test | adaptive, each optionally "+seg=<preset>" (asr_segment.PRESETS) and
  "+demucs" (production's music check + Demucs before ASR). Each system runs in its own process so its memory is its own.

Output (--out, default <data>/bench/<time>): results.json (everything), items.csv (one row per item x system),
summary.csv (one row per system x condition), report.md (readable comparison, with paired bootstrap intervals).
"""
import argparse, csv, ctypes, json, os, random, re, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

import numpy as np

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
import asr_metrics as M  # noqa: E402

SR = 16000
AUDIO_EXT = (".ogg", ".opus", ".wav", ".m4a", ".mp3", ".flac")


# ------------------------------------------------------------------ inputs
def gold_items(folder):
    folder = Path(folder)
    if not folder.exists():
        return []
    shared = {}
    if (folder / "aliases.json").exists():
        shared = json.loads((folder / "aliases.json").read_text(encoding="utf-8"))
    out = []
    for a in sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXT):
        t = a.with_suffix(".txt")
        meta = {}
        if a.with_suffix(".json").exists():
            try:
                meta = json.loads(a.with_suffix(".json").read_text(encoding="utf-8"))
            except ValueError:
                meta = {}
        if not t.exists() and not meta.get("silence"):
            continue
        ref = t.read_text(encoding="utf-8").strip() if t.exists() else ""
        if not ref and not meta.get("silence"):
            continue
        out.append({"id": "gold/" + a.stem, "path": str(a), "ref": ref, "condition": meta.get("condition") or "gold",
                    "entities": meta.get("entities") or [], "aliases": dict(shared, **(meta.get("aliases") or {})),
                    "speech": meta.get("speech"), "silence": bool(meta.get("silence"))})
    return out


def fleurs_items(folder, limit=None, seed=7):
    folder = Path(folder)
    rows = []
    with open(folder / "test.tsv", encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4 and (folder / "test" / p[1]).exists():
                rows.append({"id": "fleurs/" + p[1][:-4], "path": str(folder / "test" / p[1]),
                             "ref": p[2].strip().strip('"').replace('""', '"'), "condition": "fleurs", "entities": [],
                             "aliases": {}, "speech": None, "silence": False, "sentence": p[0]})
    seen, uniq = set(), []                       # FLEURS reads each sentence 2-3 times: keep one reading per sentence
    for r in rows:
        if r["sentence"] not in seen:
            seen.add(r["sentence"])
            uniq.append(r)
    random.Random(seed).shuffle(uniq)
    return uniq[:limit] if limit else uniq


def read(path):
    import voice_embed as VE
    a = VE.read_audio(path, max_s=100000)
    return a if a is not None else np.zeros(0, np.float32)


def concat(items, target_s, seed=11):
    """Sentences -> ~target_s recordings: 0.3-1.2 s pauses with a quiet floor; the speech times are known."""
    rng = np.random.default_rng(seed)
    out, cur, parts, t = [], [], [], 0.0
    for it in items:
        a = read(it["path"])
        if not len(a):
            continue
        a = set_level(_trim(a), -31.0)          # sentences at one level first, so the -60 dB pause floor stays quiet
        if cur and t + len(a) / SR > target_s:
            out.append(_join(cur, parts, len(out)))
            cur, parts, t = [], [], 0.0
        gap = rng.uniform(0.3, 1.2) if cur else rng.uniform(0.2, 0.5)
        cur.append(rng.normal(0, 10 ** (-60 / 20), int(gap * SR)).astype(np.float32))
        parts.append((t + gap, t + gap + len(a) / SR, it))
        cur.append(a)
        t += gap + len(a) / SR
    if cur:
        out.append(_join(cur, parts, len(out)))
    return out


def _trim(a, db=-45):
    """FLEURS files carry up to a second of silence on each side; keep 0.15 s of it."""
    frame = 320
    e = np.array([np.sqrt(np.mean(a[i:i + frame] ** 2) + 1e-12) for i in range(0, len(a), frame)])
    on = np.flatnonzero(20 * np.log10(e) > db)
    if not len(on):
        return a
    return a[max(0, on[0] * frame - 2400):min(len(a), (on[-1] + 1) * frame + 2400)]


def _join(chunks, parts, n):
    audio = np.concatenate(chunks + [np.zeros(int(0.3 * SR), np.float32)])
    return {"id": f"fleurs-cat/{n:03d}", "audio": audio, "ref": " ".join(p[2]["ref"] for p in parts),
            "speech": [[round(a, 2), round(b, 2)] for a, b, _ in parts], "condition": "fleurs-cat", "entities": [],
            "aliases": {}, "silence": False, "sources": [p[2]["id"] for p in parts]}


def probes(seed=3):
    """No speech at all: what the system writes here is invented."""
    rng = np.random.default_rng(seed)
    n = 20 * SR
    white = rng.normal(0, 1, n)
    pink = _colored(white, 1.0)
    brown = _colored(white, 2.0)
    mk = lambda x, db: (x / (np.sqrt(np.mean(x ** 2)) + 1e-12) * 10 ** (db / 20)).astype(np.float32)  # noqa: E731
    return [{"id": "probe/silence", "audio": np.zeros(n, np.float32)},
            {"id": "probe/pink-45dB", "audio": mk(pink, -45)},
            {"id": "probe/brown-30dB", "audio": mk(brown, -30)},
            {"id": "probe/white-40dB", "audio": mk(white, -40)}]


def _colored(white, alpha):
    f = np.fft.rfft(white)
    k = np.arange(len(f))
    k[0] = 1
    return np.fft.irfft(f / k ** (alpha / 2), n=len(white))


# ------------------------------------------------------------------ conditions
def apply_condition(audio, cond, rng):
    """'opus12+brown5' -> encode / decode at 12 kbps, then brown noise at 5 dB SNR (noise is added before the codec,
    as in a car: the phone hears noise + voice and encodes both)."""
    codec, noise, snr, level = "clean", None, None, None
    for part in cond.split("+"):
        m = re.fullmatch(r"(pink|brown|white)(-?\d+)", part)
        lv = re.fullmatch(r"lvl(-\d+)", part)
        if m:
            noise, snr = m.group(1), float(m.group(2))
        elif lv:
            level = float(lv.group(1))
        elif part:
            codec = part
    a = audio.astype(np.float32)
    if level is not None:                 # "lvl-50": a quiet speaker (speech RMS at -50 dBFS)
        a = set_level(a, level)
    if noise and len(a):
        n = rng.normal(0, 1, len(a))
        n = _colored(n, {"white": 0.0, "pink": 1.0, "brown": 2.0}[noise])
        ps = np.mean(a ** 2) + 1e-12
        n = n / (np.sqrt(np.mean(n ** 2)) + 1e-12) * np.sqrt(ps / 10 ** (snr / 10))
        a = (a + n).astype(np.float32)
        peak = np.max(np.abs(a))
        if peak > 0.99:
            a = a / peak * 0.99
    if codec.startswith("opus") and len(a):
        a = opus_roundtrip(a, int(codec[4:]))
    return a


def set_level(a, db):
    """Scale so the RMS of the louder half of 20 ms frames (the speech, not the pauses) sits at db dBFS."""
    if not len(a):
        return a
    fr = a[:len(a) // 320 * 320].reshape(-1, 320) if len(a) >= 320 else a.reshape(1, -1)
    e = np.sqrt(np.mean(fr ** 2, axis=1))
    act = np.sqrt(np.mean(np.sort(e)[len(e) // 2:] ** 2)) + 1e-12
    out = a * (10 ** (db / 20) / act)
    peak = float(np.max(np.abs(out)))
    return (out / peak * 0.99 if peak > 0.99 else out).astype(np.float32)


def opus_roundtrip(a, kbps):
    """The phone's format (Opus, 16 kHz mono, speech-tuned). An approximation of Android's MediaCodec encoder."""
    import voice_embed as VE
    pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes()
    enc = subprocess.run([VE.FF, "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "libopus",
                          "-b:a", f"{kbps}k", "-application", "voip", "-f", "ogg", "-"], input=pcm, capture_output=True,
                         creationflags=0x08000000 if os.name == "nt" else 0).stdout
    dec = subprocess.run([VE.FF, "-v", "error", "-i", "-", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], input=enc,
                         capture_output=True, creationflags=0x08000000 if os.name == "nt" else 0).stdout
    out = np.frombuffer(dec, np.int16).astype(np.float32) / 32768.0
    return out[:len(a)] if len(out) >= len(a) else np.pad(out, (0, len(a) - len(out)))


# ------------------------------------------------------------------ memory
def peak_ram_mb():
    if os.name != "nt":
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.PeakWorkingSetSize / 2 ** 20, 1)


class GpuWatch:
    """Whole-card memory in use, sampled every 0.5 s with nvidia-smi (Windows does not report per-process GPU memory).
    peak - baseline = this run's share only while nothing else on the card changes, so it is labelled approximate."""

    def __init__(self):
        self.samples, self.stop = [], threading.Event()
        self.base = self._read()
        self.t = threading.Thread(target=self._loop, daemon=True)
        if self.base is not None:
            self.t.start()

    def _read(self):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=5, creationflags=0x08000000 if os.name == "nt" else 0)
            return float(r.stdout.split()[0])
        except Exception:  # noqa: BLE001
            return None

    def _loop(self):
        while not self.stop.wait(0.5):
            v = self._read()
            if v is not None:
                self.samples.append(v)

    def result(self):
        self.stop.set()
        if self.base is None:
            return {"gpu": None}
        peak = max(self.samples or [self.base])
        return {"gpu_card_base_mb": self.base, "gpu_card_peak_mb": peak, "gpu_delta_mb_approx": round(peak - self.base)}


# ------------------------------------------------------------------ one system (child process)
def parse_system(name):
    s = {"name": name, "mode": "legacy", "seg": "legacy", "demucs": False}
    for part in name.split("+"):
        if part in ("legacy", "large_only", "dual_test", "adaptive"):
            s["mode"] = part
        elif part.startswith("seg="):
            s["seg"] = part[4:]
        elif part == "demucs":
            s["demucs"] = True             # production rule: Demucs only when the sound tagger hears music
        elif part == "demucsall":
            s["demucs"] = "all"            # experiment: Demucs vocals on every recording
        elif part:
            raise SystemExit(f"unknown system part {part!r}")
    return s


def run_system(system, manifest, out_path, device=None):
    import torch  # noqa: F401  (cublas for CTranslate2)
    import asr_engine
    import home_analyze as HA
    from paths import device as _device
    sysd = parse_system(system)
    cfg = HA.home_config()
    cfg["asr"] = dict(cfg.get("asr") or {}, mode=sysd["mode"], segmentation=sysd["seg"])
    cfg["asr"].pop("seg", None)
    dev = device or _device()
    gpu = GpuWatch()
    t_load = time.time()
    eng = asr_engine.Engine(cfg, dev, cfg.get("asr_compute") or ("float16" if dev == "cuda" else "int8"))
    eng.models.get(eng.model_name)
    load_s = round(time.time() - t_load, 1)
    prompt = HA.asr_prompt(cfg)
    pre = None
    if sysd["demucs"]:
        class Pre(HA.Brain):                       # only the music check + Demucs parts of the production Brain
            def __init__(self, d):
                self.dev = d
        pre = Pre(dev)
    rows = []
    items = json.load(open(manifest, encoding="utf-8"))
    for it in items:
        audio = np.load(it["npy"])
        t = time.time()
        raw = None
        if pre is not None and len(audio):
            if sysd["demucs"] == "all":
                raw, audio = audio, pre.unmusic(audio)
            else:
                events, _, _ = pre.sounds(audio)
                if any(e["tag"] in HA.MUSIC_HE for e in events):
                    raw, audio = audio, pre.unmusic(audio)
        words, trace = eng.transcribe(audio, prompt=prompt, raw=raw) if len(audio) else ([], {"windows": []})
        took = time.time() - t
        rows.append({"id": it["id"], "condition": it["condition"], "hyp": "".join(w[2] for w in words).strip(),
                     "words": words, "took_s": round(took, 3), "audio_s": round(len(audio) / SR, 2),
                     "windows": len(trace["windows"]),
                     "flagged": sum(1 for w in trace["windows"] if w["flags"]),
                     "uncertain": sum(1 for w in trace["windows"] if w.get("uncertain")),
                     "secondary_used": sum(1 for w in trace["windows"] if w["model"] != trace.get("primary")),
                     "secondary_runs": sum(1 for w in trace["windows"] if "secondary_text" in w)})
    res = {"system": system, "device": dev, "where": eng.models.where, "load_s": load_s, "rows": rows,
           "events": eng.models.events, "peak_ram_mb": peak_ram_mb(), **gpu.result()}
    json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)


# ------------------------------------------------------------------ scoring
def score(item, row):
    norm = M.Norm(aliases=item.get("aliases"))
    w = M.wer_counts(item["ref"], row["hyp"], norm)
    c = M.cer_counts(item["ref"], row["hyp"], norm)
    out = {"id": item["id"], "condition": row["condition"], "ref_words": w["N"], "hyp_words": w["hyp"],
           "S": w["S"], "D": w["D"], "I": w["I"], "wer": round(M.rate(w), 4),
           "cer_N": c["N"], "cer_err": c["S"] + c["D"] + c["I"], "cer": round(M.rate(c), 4),
           "took_s": row["took_s"], "audio_s": row["audio_s"], "flagged": row["flagged"], "uncertain": row["uncertain"],
           "secondary_used": row["secondary_used"], "secondary_runs": row["secondary_runs"], "hyp": row["hyp"]}
    terms = list(item.get("entities") or [])
    th = M.term_hits(item["ref"], row["hyp"], terms, item.get("aliases"))
    for k in ("entities", "numbers", "latin"):
        out[k + "_hit"], out[k + "_n"] = th[k]
    ts = M.timestamp_issues(row["words"], row["audio_s"])
    out["ts_issues"] = ts["backwards"] + ts["overlap"] + ts["too_long"] + ts["outside"]
    cov = M.coverage(row["words"], item["speech"]) if item.get("speech") else None
    out["coverage"] = round(cov, 4) if cov is not None else None
    return out


def aggregate(rows):
    g = {}
    for r in rows:
        k = (r["system"], r["condition"])
        a = g.setdefault(k, {"system": r["system"], "condition": r["condition"], "items": 0, "N": 0, "S": 0, "D": 0, "I": 0,
                             "cer_N": 0, "cer_err": 0, "took_s": 0.0, "audio_s": 0.0, "flagged": 0, "uncertain": 0,
                             "secondary_used": 0, "secondary_runs": 0, "ts_issues": 0, "hyp_words": 0,
                             "entities_hit": 0, "entities_n": 0, "numbers_hit": 0, "numbers_n": 0, "latin_hit": 0,
                             "latin_n": 0, "cov": []})
        a["items"] += 1
        a["N"] += r["ref_words"]
        for f in ("S", "D", "I", "cer_N", "cer_err", "took_s", "audio_s", "flagged", "uncertain", "secondary_used",
                  "secondary_runs", "ts_issues", "hyp_words", "entities_hit", "entities_n", "numbers_hit", "numbers_n",
                  "latin_hit", "latin_n"):
            a[f] += r[f]
        if r["coverage"] is not None:
            a["cov"].append(r["coverage"])
    out = []
    for a in g.values():
        n = a["N"] or 1
        out.append({"system": a["system"], "condition": a["condition"], "items": a["items"], "ref_words": a["N"],
                    "wer": round((a["S"] + a["D"] + a["I"]) / n, 4), "sub_rate": round(a["S"] / n, 4),
                    "del_rate": round(a["D"] / n, 4), "ins_rate": round(a["I"] / n, 4),
                    "cer": round(a["cer_err"] / (a["cer_N"] or 1), 4),
                    "entity_acc": round(a["entities_hit"] / a["entities_n"], 3) if a["entities_n"] else None,
                    "number_acc": round(a["numbers_hit"] / a["numbers_n"], 3) if a["numbers_n"] else None,
                    "latin_acc": round(a["latin_hit"] / a["latin_n"], 3) if a["latin_n"] else None,
                    "coverage": round(float(np.mean(a["cov"])), 4) if a["cov"] else None,
                    "ts_issues_per_100w": round(100 * a["ts_issues"] / max(a["hyp_words"], 1), 2),
                    "rtf": round(a["took_s"] / max(a["audio_s"], 1e-6), 4), "took_s": round(a["took_s"], 1),
                    "audio_s": round(a["audio_s"], 1), "flagged_windows": a["flagged"],
                    "uncertain_windows": a["uncertain"], "secondary_runs": a["secondary_runs"],
                    "secondary_used": a["secondary_used"]})
    return sorted(out, key=lambda x: (x["condition"], x["system"]))


def paired_bootstrap(rows, base, other, cond, n=2000, seed=5):
    """95 % interval of (other WER - base WER) over items resampled with replacement; negative = other is better."""
    b = {r["id"]: r for r in rows if r["system"] == base and r["condition"] == cond}
    o = {r["id"]: r for r in rows if r["system"] == other and r["condition"] == cond}
    ids = sorted(set(b) & set(o))
    if len(ids) < 5:
        return None
    eb = np.array([b[i]["S"] + b[i]["D"] + b[i]["I"] for i in ids], float)
    eo = np.array([o[i]["S"] + o[i]["D"] + o[i]["I"] for i in ids], float)
    nn = np.array([b[i]["ref_words"] for i in ids], float)
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        k = rng.integers(0, len(ids), len(ids))
        diffs.append(eo[k].sum() / max(nn[k].sum(), 1) - eb[k].sum() / max(nn[k].sum(), 1))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"diff": round(float(eo.sum() / nn.sum() - eb.sum() / nn.sum()), 4), "lo": round(float(lo), 4),
            "hi": round(float(hi), 4), "items": len(ids)}


def report(out, meta, summary, rows, probe_rows, sysinfo):
    base = meta["systems"][0]
    L = [f"# ASR benchmark {meta['started']}", "",
         f"Systems: {', '.join(meta['systems'])} (baseline = **{base}**). Device: {sysinfo.get(base, {}).get('device')}.",
         f"Inputs: {meta['inputs']}. Conditions: {', '.join(meta['conditions'])}.",
         "All systems: same audio, same Silero VAD, same keep-filter, same normalisation (asr_metrics.Norm).",
         "WER = (S+D+I)/reference words. Measured numbers only; flags/uncertain are heuristic counts, not accuracy.", ""]
    conds = sorted({s["condition"] for s in summary})
    for c in conds:
        L += [f"## {c}", "", "| system | items | ref words | WER | CER | sub | del | ins | ents | nums | latin | coverage |"
              " RTF | flagged | 2nd runs | 2nd kept | vs baseline (95% CI) |",
              "|" + "---|" * 17]
        for s in [x for x in summary if x["condition"] == c]:
            ci = paired_bootstrap(rows, base, s["system"], c) if s["system"] != base else None
            cis = f"{ci['diff']:+.2%} [{ci['lo']:+.2%}, {ci['hi']:+.2%}]" if ci else ("—" if s["system"] == base else "n<5")
            f = lambda v: "—" if v is None else (f"{v:.1%}" if isinstance(v, float) else str(v))  # noqa: E731
            L.append(f"| {s['system']} | {s['items']} | {s['ref_words']} | {s['wer']:.2%} | {s['cer']:.2%} | "
                     f"{s['sub_rate']:.2%} | {s['del_rate']:.2%} | {s['ins_rate']:.2%} | {f(s['entity_acc'])} | "
                     f"{f(s['number_acc'])} | {f(s['latin_acc'])} | {f(s['coverage'])} | {s['rtf']:.3f} | "
                     f"{s['flagged_windows']} | {s['secondary_runs']} | {s['secondary_used']} | {cis} |")
        L.append("")
    L += ["## No speech (invented words)", "", "| system | " + " | ".join(p["id"] for p in probe_rows[:4]) + " |",
          "|---|" + "---|" * 4]
    for sname in meta["systems"]:
        pr = [r for r in probe_rows if r["system"] == sname]
        L.append(f"| {sname} | " + " | ".join(f"{len(r['hyp'].split())} words" + (f": {r['hyp'][:40]}" if r["hyp"] else "")
                                             for r in pr) + " |")
    L += ["", "## Cost", "", "| system | where | load s | peak RAM MB | GPU card delta MB (approx.) | events |", "|---|---|---|---|---|---|"]
    for sname in meta["systems"]:
        si = sysinfo.get(sname, {})
        L.append(f"| {sname} | {si.get('where')} | {si.get('load_s')} | {si.get('peak_ram_mb')} | "
                 f"{si.get('gpu_delta_mb_approx', '—')} | {'; '.join(si.get('events') or [])[:120]} |")
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ driver
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", action="store_true", help="the data folder's gold set")
    ap.add_argument("--gold-dir")
    ap.add_argument("--fleurs")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concat", type=float, default=0, help="join FLEURS sentences into recordings of about N s")
    ap.add_argument("--conditions", default="clean")
    ap.add_argument("--level", type=float, help="speech level (dBFS) every FLEURS item is set to first; default -31, the "
                    "median of the phone recordings measured 2026-10-15 (FLEURS files are ~-60 dBFS, below any phone)")
    ap.add_argument("--systems", default="legacy,adaptive")
    ap.add_argument("--no-probes", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--device", choices=["cuda", "cpu"])
    ap.add_argument("--worker", nargs=2, metavar=("SYSTEM", "MANIFEST"))
    ap.add_argument("--worker-out")
    a = ap.parse_args()
    if a.worker:
        return run_system(a.worker[0], a.worker[1], a.worker_out, a.device)
    from paths import DATA
    items = []
    if a.gold:
        items += gold_items(DATA / "gold")
    if a.gold_dir:
        items += gold_items(a.gold_dir)
    if a.fleurs:
        fl = fleurs_items(a.fleurs, a.limit)
        fl = concat(fl, a.concat) if a.concat else fl
        lvl = -31.0 if a.level is None else a.level
        for it in fl:
            it["audio"] = set_level(it["audio"] if "audio" in it else read(it["path"]), lvl)
        items += fl
    if not items:
        print(json.dumps({"ok": False, "msg": "no benchmark items: the gold set is empty and no other input was given. "
                          "Add sentences from the /home screen ('add to gold set') or pass --fleurs / --gold-dir."},
                         ensure_ascii=False))
        return 2
    systems = [s.strip() for s in a.systems.split(",") if s.strip()]
    for s in systems:
        parse_system(s)
    conditions = [c.strip() for c in a.conditions.split(",") if c.strip()]
    started = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(a.out) if a.out else DATA / "bench" / started
    (out / "audio").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(13)
    manifest, by_key = [], {}
    for it in items:
        base_audio = it["audio"] if "audio" in it else read(it["path"])
        for c in conditions:
            key = f"{c}|{it['id']}"
            npy = out / "audio" / (re.sub(r"[^\w.-]", "_", key) + ".npy")
            np.save(npy, apply_condition(base_audio, c, rng))
            manifest.append({"id": it["id"], "condition": c, "npy": str(npy)})
            by_key[key] = it
    if not a.no_probes:
        for p in probes():
            npy = out / "audio" / (p["id"].replace("/", "_") + ".npy")
            np.save(npy, p["audio"])
            manifest.append({"id": p["id"], "condition": "probe", "npy": str(npy)})
    json.dump(manifest, open(out / "manifest.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(items)} items x {len(conditions)} conditions -> {out}", flush=True)
    sysinfo, scored, probe_rows = {}, [], []
    for s in systems:
        wo = out / ("system_" + re.sub(r"[^\w.-]", "_", s) + ".json")
        t = time.time()
        cmd = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--worker", s, str(out / "manifest.json"),
               "--worker-out", str(wo)] + (["--device", a.device] if a.device else [])
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0 or not wo.exists():
            print(f"system {s} failed:\n{p.stderr[-2000:]}", flush=True)
            sysinfo[s] = {"failed": p.stderr[-500:]}
            continue
        r = json.load(open(wo, encoding="utf-8"))
        sysinfo[s] = {k: v for k, v in r.items() if k != "rows"}
        for row in r["rows"]:
            if row["condition"] == "probe":
                probe_rows.append(dict(row, system=s))
                continue
            sc = score(by_key[f"{row['condition']}|{row['id']}"], row)
            sc["system"] = s
            scored.append(sc)
        print(f"system {s}: {time.time() - t:.0f}s", flush=True)
    summary = aggregate(scored)
    meta = {"started": started, "systems": systems, "conditions": conditions,
            "inputs": {"gold": a.gold, "gold_dir": a.gold_dir, "fleurs": a.fleurs, "limit": a.limit, "concat": a.concat,
                       "items": len(items)}}
    json.dump({"meta": meta, "systems": sysinfo, "summary": summary, "items": scored, "probes": probe_rows},
              open(out / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for name, rows in (("items.csv", scored), ("summary.csv", summary)):
        if rows:
            with open(out / name, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    report(out, meta, summary, scored, probe_rows, sysinfo)
    print((out / "report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
