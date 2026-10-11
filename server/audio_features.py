"""Local acoustic estimates using NumPy only; no emotion classifier or Praat.

Intensity uses the historical digital reference (2e-5), not calibrated sound
pressure. Pitch is an autocorrelation estimate and is omitted for unvoiced audio.
These measurements must not be presented as arousal, valence or a diagnosis.
"""
import numpy as np


def prosody(wave, sr=16000):
    samples = np.asarray(wave, dtype=np.float64).reshape(-1)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    size, hop = int(sr * .04), int(sr * .01)
    if len(samples) < size:
        return {"voiced_share": 0.0, "intensity_db": None}
    frames = np.lib.stride_tricks.sliding_window_view(samples, size)[::hop]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-10) / 2e-5)
    pitches = []
    lo, hi = max(1, int(sr / 600)), int(sr / 75)
    for frame, level in zip(frames, rms):
        if level < 1e-4:
            continue
        x = frame - frame.mean()
        corr = np.correlate(x, x, mode="full")[size - 1:]
        if corr[0] < 1e-12:
            continue
        # Compensate for the decreasing overlap at longer lags.
        corr = corr / (np.arange(size, 0, -1) * (corr[0] / size))
        peaks = [lag for lag in range(lo, hi + 1)
                 if corr[lag] >= .65 and corr[lag] >= corr[lag - 1]
                 and corr[lag] > corr[lag + 1]]
        if not peaks:
            continue
        best = max(corr[lag] for lag in peaks)
        lag = next(lag for lag in peaks if corr[lag] >= .9 * best)
        denom = corr[lag - 1] - 2 * corr[lag] + corr[lag + 1]
        shift = .5 * (corr[lag - 1] - corr[lag + 1]) / denom if abs(denom) > 1e-12 else 0
        frequency = sr / (lag + np.clip(shift, -.5, .5))
        if 75 <= frequency <= 600:
            pitches.append(frequency)
    out = {"voiced_share": round(len(pitches) / len(frames), 2),
           "intensity_db": round(float(np.median(db)), 1)}
    if len(pitches) >= 10:
        semitones = 12 * np.log2(np.asarray(pitches) / 100)
        out.update(f0_hz=round(float(np.median(pitches)), 1),
                   f0_range_st=round(float(np.percentile(semitones, 90) - np.percentile(semitones, 10)), 1))
    return out
