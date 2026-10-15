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

## 5. Rollback

* **Model:** the "חזור אליו" button on איכות התמלול, or `asr_update.py --rollback`. It switches back to
  `whisper_model_prev`, which stays installed.
* **Mode / segmentation / correction:** pick "רגיל" on the tab, or remove the `"asr"` key from `config.json`. The
  worker reloads before the next chunk.
* **The whole upgrade:** deploy the previous server release. The two new DB columns are nullable and ignored by
  old code; no existing row was changed.
* **Phone fix:** reinstall the previous APK/AAB (no data format change).
