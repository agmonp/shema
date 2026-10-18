# Shema ASR 2.0: measured Hebrew transcription upgrade

Branch `feat/asr-2.0`. Everything new is behind `config.json` flags. **With no new keys set, transcription is
bit-identical to before** (test `test_legacy_mode_equals_old_code`). Nothing leaves the PC: no audio, text or
glossary is sent anywhere. The only network use is downloading a model when the user presses "install", and the
model-list check that `asr_update` already did.

## 1. Baseline: the pipeline as it was (Phase A)

**Phone** (`android/.../ListenService.kt`, `Vad.kt`; the same in `commercial/android`):

| Setting | Value |
|---|---|
| Audio source | `VOICE_RECOGNITION`, 16 kHz mono PCM16 |
| VAD | Silero v4 ONNX, 512-sample frames (32 ms) |
| Segment start | p ≥ 0.5 for 3 frames; pre-roll 16 frames (0.51 s) |
| Segment continues | while p ≥ 0.35 |
| Segment end | 25 quiet frames (0.8 s), or 940 frames (30.08 s) |
| Format | Opus 12 kbps in Ogg (AAC-LC 24 kbps .m4a if there is no Opus encoder) |

**PC** (`home_analyze.py`; the live copy in `lifegraph-beinspace-20260916` is identical in these parts):

| Stage | Setting |
|---|---|
| Decode | ffmpeg → 16 kHz mono float32 |
| Sound tags | sound tagger runs first; when music is heard, Demucs `htdemucs` "vocals" goes to ASR and speaker vectors |
| VAD | sherpa-onnx Silero: threshold 0.5, min speech 0.2 s, min silence 0.2 s |
| Regions | joined when the gap is < 0.4 s and the span stays < 15 s; regions < 0.25 s are skipped; ±0.2 s padding; each region decoded on its own |
| ASR | faster-whisper 1.2.1 / CTranslate2 4.8.2, `ivrit-ai/whisper-large-v3-turbo-ct2` (rev `72ad623a`), CUDA float16 (CPU int8) |
| Decoding | beam 5, word timestamps, `language="he"`, `condition_on_previous_text=False`, `initial_prompt` = `asr_terms` |
| Keep-filter | a segment is kept if `no_speech_prob < 0.6`, `avg_logprob > -1.2`, and it is not a known hallucination ("תודה רבה", ...) |
| After ASR | words → 3 s chunks → ERes2NetV2 + TitaNet voice vectors → speakers → utterances → DB → summaries |

**Effective live config (checked 2026-10-15):** `whisper_model`, `asr_compute`, `device` and `asr_terms` were all
unset, so the defaults above apply on CUDA. The gold set (`data/home/gold`) was **empty**.

**Mismatch, now fixed:** `asr_update.model_wer` decoded each whole file with faster-whisper's own
`vad_filter=True` (different VAD parameters, no region split, no padding, no keep-filter). Its WER did not
describe production. Evaluation now runs `asr_engine`, the code production uses.

**Test coverage before:** 4 tests (prosody, updater licence filter, storage without emotions). No test covered
cropping, timestamps or speaker attribution.

## 2. What changed

| Module | Change |
|---|---|
| `asr_engine.py` (new) | Production transcription moved here, used by both `home_analyze` and the benchmark. Modes `legacy` / `large_only` / `dual_test` / `adaptive`. Writes a per-window trace (model, flags, uncertain, reason). |
| `asr_segment.py` (new) | The production region rule as preset `legacy`, plus experiments `pad05`, `pad08`, `merge`, `overlap`, `short`, `vadnorm` (combinable, e.g. `pad05+vadnorm`). Word ownership by midpoint, so padded or overlapping windows never store a word twice. |
| `asr_quality.py` (new) | Heuristic flags from Whisper's own numbers plus text checks. `choose()` picks between two readings and never mixes them. |
| `asr_models.py` (new) | Explicit install (licence, disk space, sha256 against Hugging Face metadata). Offline loading once installed. CUDA→CPU fallback, OOM handling. Secondary model is unloaded unless VRAM stays free. |
| `asr_correct.py` (new) | `asr_terms` + `asr_glossary`. Deterministic fixes only for listed variants, Latin letter case and spacing. Optional local-LLM yes/no per candidate. Negations, numbers and short words are never touched. Off by default. |
| `asr_metrics.py` (new) | Normalisation (niqqud, final letters, punctuation, gershayim, maqaf, aliases). WER/CER split into S/D/I. Strict name/number/Latin hits, timestamp anomalies, coverage. |
| `asr_bench.py` (new) | Production-equivalent benchmark: gold / FLEURS / synthetic probes; Opus, noise and level conditions; one process per system; JSON, CSV and Markdown output. |
| `asr_update.py` | Discovery separate from promotion; nominated models; production-equivalent evaluation; regression gate; `whisper_model_prev` + rollback; failed checks no longer switch checks off. |
| `home_analyze.py` | `Brain.transcribe` → `asr_engine`; `asr_annotate()` adds `u["asr"]` and `u["text_raw"]` after speakers are known. |
| `home_listener.py` | New nullable columns `utterances.text_raw`, `utterances.asr` (history untouched). API for the new tab. Gold `.json` keeps the recording condition. Worker reloads models on a settings change. |
| `ui/home.html` | New tab **איכות התמלול**. |
| `ListenService.kt` (both apps) | Opus encoding moved off the recording thread (see §5). |

Speaker recognition, voice banks, conversation boundaries, summaries, storage policy and deletion are unchanged.
Corrections only change `text`, never `speaker`. Media lines (TV/music) are never corrected.

## 3. Configuration (`config.json`)

```json
"asr": {
  "mode": "legacy",              // legacy | large_only | dual_test | adaptive
  "segmentation": "legacy",      // legacy | pad05 | pad08 | merge | overlap | short | vadnorm, combinable "pad05+vadnorm"
  "seg": {},                     // single overrides, e.g. {"pad": 0.5}
  "secondary_model": "ivrit-ai/whisper-large-v3-ct2",
  "keep_secondary": "auto",      // auto | always | never
  "retry_pad": 0.5,
  "retry_source": "raw",         // raw = the recording before Demucs; same = what the primary saw
  "quality": {"logprob": -1.0, "no_speech": 0.6, "compression": 2.4, "max_wps": 5.5},
  "mark_uncertain": true,        // flags stored per utterance; the text is not changed
  "correct": {"enabled": false, "llm": false, "llm_model": "gemma3:4b"}
},
"asr_glossary": [{"term": "WhatsApp", "variants": ["וואטסאפ"], "kind": "company", "prompt": true}],
"asr_check": {"auto_promote": true, "nominated": []}
```

## 4. Commands

```
python -X utf8 server\asr_models.py --install ivrit-ai/whisper-large-v3-ct2      # explicit download + sha256 check
python -X utf8 server\asr_models.py --verify  ivrit-ai/whisper-large-v3-ct2
python -X utf8 server\asr_bench.py --gold --systems legacy,adaptive,legacy+seg=pad05
python -X utf8 server\asr_bench.py --fleurs <dir> --concat 30 --conditions opus12,opus12+brown5,opus12+lvl-50
python -X utf8 server\asr_update.py --check            # discovery + evaluation, changes nothing
python -X utf8 server\asr_update.py --rollback
python -X utf8 -m unittest discover -s tests
```

Benchmark output goes to `<data>/bench/<time>/`: `results.json`, `items.csv`, `summary.csv`, `report.md`. The
newest run appears on the איכות התמלול tab. Real recordings and references stay in the data folder and never go
into git.

## 5. Phone: recording was blind after every segment (fixed in code, not yet installed)

Measured 2026-10-15 from 17,468 live segments on both phones. The time between the end of a segment and the start
of the next one grows with the previous segment's length:

| Previous segment | OPPO: 2nd-percentile gap | Redmi: 10th-percentile gap |
|---|---|---|
| 5–10 s | 2.2 s | 2.9 s |
| 15–20 s | 6.8 s | 8.5 s |
| 25–30 s | 11.4 s | 14.2 s |
| 30 s cap | median gap 15.5 s | |

**Cause:** `save()` encoded the Opus file on the recording thread. MediaCodec waits up to 10 ms per 20 ms packet,
while `AudioRecord`'s ~256 ms buffer overflows. Whatever was said in that window was never recorded, roughly half
the length of every segment. Encoding now runs on its own thread. Both apps compile; the fix reaches a phone only
with a new APK/AAB. **Expected effect:** far fewer lost words in conversations. It is not measured yet; after
install, the same gap query must show gaps no longer growing with segment length.

## 6. Results

All numbers below are measured. Data:

* **FLEURS Hebrew** test set (CC-BY-4.0): 347 distinct read sentences, 6,082 reference words, raised to the phones'
  median level (−31 dBFS).
* **Recordings:** the same sentences joined into 126 phone-like recordings of about 30 s with pauses.
* **Conditions:** synthetic.

Scoring uses lenient normalisation; 95 % intervals come from a paired bootstrap over items. RTX 5070 Ti, CUDA
float16, with the live server running on the same card. Read speech is **not** home conversation: these results
show direction, and §7 explains why they are not enough for a default change.

**Models (sentences, WER):**

| Condition | turbo (legacy) | large-v3 (large_only) | Δ (95 % CI) | Adaptive, default limits | Adaptive, lp −0.35 |
|---|---|---|---|---|---|
| clean | 18.0 % | 17.7 % | −0.3 [−1.0, +0.4] | 18.0 % | — |
| Opus 12k (phone) | 19.7 % | 19.1 % | −0.5 [−1.4, +0.2] | 19.7 % | 19.7 % |
| Opus 12k + brown noise 5 dB | 19.8 % | 18.7 % | **−1.1 [−1.8, −0.4]** | 19.7 % | 19.7 % |
| Opus 12k, quiet speaker −50 dB | 37.8 % | 37.6 % | −0.2 [−1.0, +0.6] | 37.5 % | **37.3 %** (−0.6) |
| Opus 24k | 18.7 % | 18.1 % | −0.5 | 18.7 % | — |
| Opus 32k | 18.6 % | 17.8 % | **−0.8 [−1.5, −0.1]** | 18.6 % | — |

* Speed (seconds of work per second of audio, ASR only): turbo 0.031, large-v3 0.09 (≈3×), adaptive 0.04–0.12
  depending on the limit.
* Peak RAM: turbo 2.2 GB, adaptive 5.7–6.7 GB.
* No system wrote any word on 20 s of digital silence, pink, brown or white noise.

**Bitrate** (same lossless source, turbo): 12k 19.7 % → 24k 18.7 % → 32k 18.6 %. The step from 12 to 24 kbps is
about 1 point (5 % relative); 32k adds nothing more. It would cost double the phone storage and upload (≈5 → 10 MB
per hour of speech). This is only a first comparison, on read speech.

**Segmentation and Demucs (recordings, Δ WER vs legacy; first run, before the benchmark trim fix):**

| System | Opus 12k | + noise | quiet −50 dB |
|---|---|---|---|
| seg=vadnorm | +0.1 | −0.1 | **−5.4 [−7.1, −3.8]** |
| seg=pad08 | −0.1 | −0.1 | **−2.8** |
| seg=overlap | −0.5 | −0.4 | **−2.4** |
| seg=merge | −0.3 | **−0.4** | **−0.9** |
| seg=pad05 / short | −0.2 | +0.2 | **−1.6** |
| Demucs on every recording | −0.3 | 0.0 | +0.4 |
| adaptive (default limits) | 0.0 | 0.0 | 0.0 |

**Segmentation, clean run** (benchmark trim fixed; WER, Δ points vs legacy [95 % CI]):

| System | Opus 12k | + brown noise 5 dB | quiet −50 dB | deletions (12k) | Seconds per second |
|---|---|---|---|---|---|
| legacy | 19.8 % | 20.1 % | 28.2 % | 2.8 % | 0.032 |
| seg=vadnorm | 19.9 % (+0.1 [−0.1, +0.4]) | 20.0 % (−0.1) | **20.9 % (−7.2 [−9.3, −5.3])** | 2.7 % | 0.031 |
| seg=pad08 | 19.6 % (−0.2) | 19.5 % (−0.6) | 26.0 % (−2.1) | 3.0 % | 0.032 |
| seg=overlap | **18.9 % (−0.8 [−1.4, −0.3])** | **18.9 % (−1.1)** | 25.9 % (−2.2) | 2.8 % | 0.028 |
| seg=merge | 19.1 % (−0.7 [−1.0, −0.4]) | 19.4 % (−0.7) | 27.1 % (−1.1) | 2.8 % | 0.028 |
| seg=pad08+vadnorm | 19.5 % (−0.2) | 19.7 % (−0.4) | 21.0 % (−7.2) | 3.3 % | 0.034 |
| **seg=overlap+vadnorm** | **19.2 % (−0.6 [−1.2, −0.0])** | **19.0 % (−1.0 [−1.8, −0.4])** | **20.5 % (−7.7 [−9.8, −5.7])** | 2.7 % | 0.027 |

`overlap+vadnorm` is better or equal in all three conditions. Relative to legacy: −3 % on normal phone audio, −5 %
with noise, **−27 % for quiet speakers**. It costs no extra time. No preset invented words on silence or noise.

**Real recordings, behaviour only** (80 random chunks from the last 14 days, 544 s, no reference text):

| System | Windows flagged | Chunks whose text changed vs legacy | Mean word similarity | Seconds per second |
|---|---|---|---|---|
| legacy | 25 of 131 (19 %) | — | 1.00 | 0.062 |
| adaptive | 24 re-read, 16 replaced | 19 | 0.84 | 0.19 |
| seg=vadnorm | — | 50 | 0.56 | 0.094 |
| seg=pad05 | — | 50 | 0.62 | 0.26 |
| large_only | — | 61 | 0.43 | 0.45 |

On real home audio (children, TV, people talking over each other) the options produce *different* readings, often
equally wrong. `vadnorm` gives more words in 19 chunks and fewer in 21. Large-v3 transcribes English TV as English,
but also invented a sentence the turbo model did not ("תודה רבה, חבר הכנסת ..."). Flags fire on 19 % of real
windows, against ≈0 % on FLEURS: they find the hard audio, but on FLEURS re-reading did not fix it.

**Household names as Whisper's hint (`asr_terms`): rejected.** Measured 2026-10-15 on 150 real chunks, same
pipeline with and without "אגמון, תמר, אדם, תאיה, דריה, פורת, שיבא". The names appeared 24 times instead of 3, most
of them invented ("תמר, תמר", "שיבא שיבא" on silence or noise, "תודה רבה, אדם" where legacy wrote nothing). Text
changed in 103 of 150 chunks. Names should go only into the glossary's *correction* list with explicit variants,
never into the hint.

## 7. Conclusions

1. **What was measured:** FLEURS sentences and recordings under phone-like conditions; behaviour on 80 real chunks;
   phone recording gaps on 17,468 real segments. **Not measured:** accuracy on your own conversations (gold set
   empty), the phone fix on a phone, the LLM correction stage (no glossary yet), Hebrew forced alignment (not
   adopted: no verified Hebrew alignment model).
2. **Did accuracy improve?** On FLEURS, the 10 % relative target is reached only for quiet speakers:
   `overlap+vadnorm` gives −27 % relative on that condition, and −3 % to −5 % on normal and noisy phone audio. The
   largest real-world gain is probably the phone fix, which recovers speech that was never recorded; it is not
   measurable on FLEURS.
3. **Default:** stays `legacy`. The FLEURS gains are real but come from read speech, and on 80 real chunks the
   presets changed most transcripts in ways that cannot be scored without references. **First candidate** for
   promotion once the gold set has ~40 sentences: `segmentation: overlap+vadnorm`. Command:
   `asr_bench.py --gold --systems legacy,legacy+seg=overlap+vadnorm,legacy+seg=vadnorm`. Promote it only if it is
   not worse on the gold set.
4. **Keep disabled:** `large_only`, because it is 3× slower for −0.5 points on phone audio. `adaptive`: no
   measurable gain at default limits, and only −0.6 points on quiet speech at 3.5× cost. Demucs on everything. Opus
   24k on the phone until real-speech data supports it. LLM correction until there is a glossary and a measured test.
5. **Cost of options:** the segmentation presets are free (same model, RTF 0.028–0.044); large-v3 or adaptive
   need about 3.5 GB more GPU memory (approximate) and 2–4 GB more RAM.

## 8. Not tested / hardware-specific

* CPU-only installs: the CPU int8 path and the CUDA→CPU fallback are covered by unit tests with a fake model;
  there was no real CPU benchmark run.
* OOM recovery is unit-tested with a simulated error, not with a real full GPU.
* `asr_models.install` was not run through the UI against the network (the model was downloaded with
  `snapshot_download` and verified there).
* The Android encoder-thread fix compiles (`compileDebugKotlin`, both apps) but is not installed or measured on a
  phone.
* Bitrate on the real phone encoder (MediaCodec) differs from ffmpeg libopus. Battery and upload effects were not
  measured.

## 9. Rollback

* **Model:** the "חזור אליו" button on איכות התמלול, or `asr_update.py --rollback`. It switches back to
  `whisper_model_prev`, which stays installed.
* **Mode / segmentation / correction:** pick "רגיל" on the tab, or remove the `"asr"` key from `config.json`. The
  worker reloads before the next chunk.
* **The whole upgrade:** deploy the previous server release. The two new DB columns are nullable and ignored by
  old code; no existing row was changed.
* **Phone fix:** reinstall the previous APK/AAB (no data format change).

## 10. On the owner's own sentences (2026-10-18)

First measurement on real home speech: the 40-sentence gold set (416 reference words, corrected by the owner from
the turbo transcript), production pipeline `legacy+seg=overlap+vadnorm`, RTX 5070 Ti, live server on the same card.

| System | WER | Δ vs production [95 % CI] | RTF |
|---|---|---|---|
| production (turbo, overlap+vadnorm) | 33.9 % | — | 0.049 |
| large_only (ivrit-ai large-v3) | 39.2 % | **+5.3 [+0.2, +10.7]** | 0.106 |
| beam 10 | 34.1 % | +0.2 [−1.9, +3.0] | 0.090 |
| keep log-prob > −1.0 / > −1.5, no-speech < 0.8 | 33.9 % | 0.0 (identical text) | 0.048 |

No system wrote words on silence or noise. **Conclusions:** large-v3 is worse on this household's speech (it was
0.3–1.1 points better on read FLEURS speech), so it stays off; a wider beam buys nothing at twice the time; the
keep-filter thresholds never bind on these sentences. Caveat: the references were corrected from turbo output, which
may favour turbo's spelling choices; and 40 sentences is small. The decoding knobs (`+beam=`, `+keeplp=`, `+nsp=` in
a bench system name; `SHEMA_ASR_*` environment) exist for experiments only; the server never sets them.
Benchmark needs `SHEMA_MODELS` pointing at a folder with silero_vad.onnx (lifegraph: `voice_models`).

## 11. Decoding each speaker turn separately (2026-10-18)

Production decodes whole windows (speech joined across pauses < 0.8 s, up to 28 s) and splits words between
speakers afterwards. The gold sentences are single lines (one speaker each), so the test joins pairs of them: 12
pairs of different speakers (the owner + someone else) and 8 same-speaker controls, with a 0.3 s gap (production
merges it into one window) and with no gap. "Each turn" = the two sentences decoded alone (perfect boundaries).

| | whole window (production) | each turn, perfect boundaries |
|---|---|---|
| different speakers, gap 0.3 s (197 words) | 32.0 % | **25.9 %** (whole worse in 6/12 pairs, better in 0) |
| different speakers, no gap | 35.0 % | **25.9 %** (worse in 9/12, better in 1) |
| same speaker, gap 0.3 s / none (219 words) | **35.6 % / 39.7 %** | 41.1 % |

So cutting at a change of speaker could remove about a fifth of the errors, while cutting one speaker's speech
costs context. **Automatic cutting** (`asr_segment.speaker_cuts`: eres2netv2 vectors of 1.5 s every 0.25 s, cut where
the window before vs after is least similar and below a threshold; bench `+spkcut=THR`, env `SHEMA_ASR_SPKCUT`):

| | production | spkcut 0.15 | spkcut 0.2 |
|---|---|---|---|
| different, gap 0.3 s | 32.0 % | 33.0 % | 34.5 % |
| different, no gap | 35.0 % | 32.5 % | 33.0 % |
| same speaker, 0.3 s / none | 35.6 / 39.7 % | 35.6 / 39.7 % | 35.6 / 41.6 % |
| 40 single sentences | 33.9 % | 33.9 % | 35.6 % |
| time (RTF) | 0.04 | 0.11–0.14 | 0.11–0.14 |

The voice vectors on 1.5 s of home audio do not separate a change of speaker from one speaker: the least similar
point was 0.04–0.66 at real changes, 0.17–0.50 inside one speaker, and as low as 0.17 inside single sentences.
**Not enabled.** The gain exists (perfect boundaries) but needs a detector trained for speaker change (e.g. a
frame-level segmentation model), or re-decoding by the speaker assignment production already makes after ASR;
neither is built. The switch stays off by default (SPKCUT = 0); production behaviour is unchanged.
