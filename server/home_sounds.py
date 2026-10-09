# -*- coding: utf-8 -*-
r"""home_sounds.py -- what is heard around the talk at home.

Three layers, every 2 s window (hop 1 s):
  1. CED-base (sherpa-onnx, AudioSet 527 classes, mAP 0.50 vs 0.46 for the AST it replaces, and
     the same model family runs on Android) -> the home-relevant classes in TAGS (Hebrew names,
     grouped). Microwave, door, drawer, cupboard, knock, creak, guitar, ball bounce, doorbell ...
  2. CLAP (laion/larger_clap_general) zero-shot for sounds AudioSet does not have: the user's own
     list in sound_labels.json in the data folder ("מקרר": ["refrigerator door opening and closing", ...]).
     A label wins only against the negatives (speech, silence, room noise, music) by a margin.
  3. the user's taught sounds: CLAP audio vectors of clips the user named on the PC
     (home.sqlite sound_bank) -> nearest neighbour ("our doorbell").
Consecutive windows of the same tag merge into one event.

    python -X utf8 home_sounds.py FILE   # print the events
"""
import json, sys
from pathlib import Path

import numpy as np

PROJ = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJ))
from paths import DATA, MODELS  # noqa: E402

CED_DIR = MODELS / "sherpa-onnx-ced-base-audio-tagging-2024-04-19"
CLAP_MODEL = "laion/larger_clap_general"
LABELS_FILE = DATA / "sound_labels.json"
SR = 16000
WIN, HOP = 2.0, 1.0

# AudioSet display name -> (Hebrew tag, group, min prob). Groups drive icons and colours on the screen.
TAGS = {
    # people (non-speech)
    "Laughter": ("צחוק", "אנשים", .25), "Baby laughter": ("צחוק", "אנשים", .25), "Giggle": ("צחוק", "אנשים", .25),
    "Crying, sobbing": ("בכי", "אנשים", .25), "Baby cry, infant cry": ("בכי", "אנשים", .25), "Whimper": ("בכי", "אנשים", .3),
    "Screaming": ("צעקה", "אנשים", .3), "Shout": ("צעקה", "אנשים", .3), "Yell": ("צעקה", "אנשים", .3),
    "Children shouting": ("צעקות ילדים", "אנשים", .3), "Children playing": ("ילדים משחקים", "אנשים", .3),
    "Whispering": ("לחישה", "אנשים", .3), "Singing": ("שירה", "אנשים", .3), "Child singing": ("שירה", "אנשים", .3),
    "Humming": ("זמזום שיר", "אנשים", .3), "Whistling": ("שריקה", "אנשים", .3), "Sigh": ("אנחה", "אנשים", .35),
    "Cough": ("שיעול", "אנשים", .35), "Sneeze": ("התעטשות", "אנשים", .35), "Sniff": ("הרחה", "אנשים", .4),
    "Snoring": ("נחירות", "אנשים", .3), "Hiccup": ("שיהוק", "אנשים", .35), "Burping, eructation": ("גיהוק", "אנשים", .35),
    "Clapping": ("מחיאות כפיים", "אנשים", .3), "Applause": ("מחיאות כפיים", "אנשים", .3), "Cheering": ("עידוד", "אנשים", .3),
    "Finger snapping": ("נקישת אצבעות", "אנשים", .35), "Walk, footsteps": ("צעדים", "אנשים", .3), "Run": ("ריצה", "אנשים", .35),
    "Babbling": ("מלמול תינוק", "אנשים", .3),
    # doors & furniture
    "Door": ("דלת", "בית", .25), "Sliding door": ("דלת הזזה", "בית", .3), "Slam": ("טריקה", "בית", .25),
    "Knock": ("דפיקה בדלת", "בית", .25), "Doorbell": ("פעמון דלת", "בית", .2), "Ding-dong": ("פעמון דלת", "בית", .2),
    "Cupboard open or close": ("ארון נפתח/נסגר", "בית", .25), "Drawer open or close": ("מגירה", "בית", .25),
    "Squeak": ("חריקה", "בית", .3), "Creak": ("חריקת רהיט/דלת", "בית", .3), "Keys jangling": ("מפתחות", "בית", .3),
    "Zipper (clothing)": ("רוכסן", "בית", .35), "Crumpling, crinkling": ("קימוט ניילון/נייר", "בית", .35),
    "Tearing": ("קריעה", "בית", .35), "Scissors": ("מספריים", "בית", .35), "Coin (dropping)": ("מטבע נופל", "בית", .35),
    "Glass": ("זכוכית", "בית", .3), "Shatter": ("משהו נשבר", "בית", .25), "Basketball bounce": ("כדור קופץ", "בית", .25),
    "Rattle": ("רעשן/קרקוש", "בית", .35), "Clock": ("שעון", "בית", .35), "Tick-tock": ("שעון", "בית", .35),
    # kitchen & bath
    "Microwave oven": ("מיקרוגל", "מטבח", .2), "Blender": ("בלנדר", "מטבח", .25), "Dishes, pots, and pans": ("כלים", "מטבח", .25),
    "Cutlery, silverware": ("סכו\"ם", "מטבח", .25), "Chopping (food)": ("חיתוך", "מטבח", .3), "Frying (food)": ("טיגון", "מטבח", .3),
    "Boiling": ("רתיחה/קומקום", "מטבח", .3), "Water tap, faucet": ("ברז", "מטבח", .25), "Sink (filling or washing)": ("כיור", "מטבח", .25),
    "Pour": ("מזיגה", "מטבח", .35), "Fill (with liquid)": ("מילוי מים", "מטבח", .35), "Drip": ("טפטוף", "מטבח", .35),
    "Toilet flush": ("הורדת מים", "אמבטיה", .25), "Bathtub (filling or washing)": ("אמבטיה/מקלחת", "אמבטיה", .25),
    "Hair dryer": ("פן", "אמבטיה", .25), "Toothbrush": ("צחצוח שיניים", "אמבטיה", .3),
    "Electric shaver, electric razor": ("מכונת גילוח", "אמבטיה", .3),
    # appliances & devices
    "Vacuum cleaner": ("שואב אבק", "מכשירים", .25), "Mechanical fan": ("מאוורר", "מכשירים", .35),
    "Air conditioning": ("מזגן", "מכשירים", .35), "Printer": ("מדפסת", "מכשירים", .3), "Typing": ("הקלדה", "מכשירים", .3),
    "Computer keyboard": ("הקלדה", "מכשירים", .3), "Beep, bleep": ("צפצוף", "מכשירים", .3), "Ding": ("צליל דינג", "מכשירים", .3),
    "Alarm": ("אזעקה/התראה", "מכשירים", .3), "Alarm clock": ("שעון מעורר", "מכשירים", .3),
    "Smoke detector, smoke alarm": ("גלאי עשן", "מכשירים", .25), "Telephone bell ringing": ("טלפון מצלצל", "מכשירים", .25),
    "Ringtone": ("רינגטון", "מכשירים", .25), "Television": ("טלוויזיה", "מכשירים", .3), "Radio": ("רדיו", "מכשירים", .3),
    "Video game music": ("משחק מחשב", "מכשירים", .3), "Hammer": ("פטיש", "מכשירים", .3), "Drill": ("מקדחה", "מכשירים", .3),
    "Power tool": ("כלי עבודה חשמלי", "מכשירים", .3), "Sawing": ("ניסור", "מכשירים", .3),
    # music
    "Music": ("מוזיקה", "מוזיקה", .4), "Guitar": ("גיטרה", "מוזיקה", .25), "Ukulele": ("יוקלילי", "מוזיקה", .3),
    "Piano": ("פסנתר", "מוזיקה", .25), "Keyboard (musical)": ("קלידים", "מוזיקה", .3), "Drum": ("תופים", "מוזיקה", .3),
    "Drum kit": ("תופים", "מוזיקה", .3), "Violin, fiddle": ("כינור", "מוזיקה", .3), "Music for children": ("שירי ילדים", "מוזיקה", .3),
    "Wind chime": ("פעמוני רוח", "מוזיקה", .3),
    # animals & outside
    "Dog": ("כלב", "בעלי חיים", .3), "Bark": ("נביחה", "בעלי חיים", .3), "Cat": ("חתול", "בעלי חיים", .3),
    "Meow": ("מיאו", "בעלי חיים", .3), "Purr": ("גרגור חתול", "בעלי חיים", .35), "Bird": ("ציפורים", "בעלי חיים", .35),
    "Chirp, tweet": ("ציוץ", "בעלי חיים", .35), "Rain": ("גשם", "בחוץ", .35), "Thunder": ("רעם", "בחוץ", .3),
    "Wind": ("רוח", "בחוץ", .4), "Car": ("רכב", "בחוץ", .35), "Motorcycle": ("אופנוע", "בחוץ", .35),
    "Siren": ("סירנה", "בחוץ", .3), "Car alarm": ("אזעקת רכב", "בחוץ", .3), "Fireworks": ("זיקוקים", "בחוץ", .3),
}

DEFAULT_CUSTOM = {   # CLAP prompts for sounds AudioSet lacks (editable: sound_labels.json in the data folder)
    "מקרר": ["the sound of a refrigerator door opening and closing", "a fridge door being shut"],
    "גרירת כיסא/רהיט": ["chair legs scraping across a floor", "furniture being dragged on a tiled floor"],
    "כדור": ["a ball bouncing on the floor indoors", "a child kicking a ball against a wall"],
    "צעצוע": ["an electronic children's toy playing sounds", "a toy rattling and clicking"],
    "צפצוף מיקרוגל": ["a microwave oven beeping when it finishes"],
    "מכונת כביסה": ["a washing machine spinning", "a dishwasher running"],
    "קומקום": ["an electric kettle boiling water and clicking off"],
    "מכונת קפה": ["an espresso coffee machine grinding and brewing"],
    "תריס": ["a window roller shutter being pulled up or down"],
    "גיטרה": ["someone strumming an acoustic guitar"],
}
CLAP_MIN_SIM, CLAP_MARGIN = 0.30, -0.02   # ESC-50 test 2026-10-06: real washing machine 0.32-0.37 (AudioSet "pump"/"engine" tie it), every wrong custom label <= 0.245
BANK_MIN_SIM = 0.80


def custom_labels():
    try:
        return json.load(open(LABELS_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        json.dump(DEFAULT_CUSTOM, open(LABELS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return dict(DEFAULT_CUSTOM)


def _emb(out):
    """transformers 5 returns an output object from get_*_features (4.x returned the tensor)."""
    if hasattr(out, "pooler_output") and out.pooler_output is not None:
        out = out.pooler_output
    return out / out.norm(dim=-1, keepdim=True)


class Ears:
    def __init__(self, device=None, use_clap=True):
        import sherpa_onnx
        from paths import device as _dev
        device = device or _dev()
        cfg = sherpa_onnx.AudioTaggingConfig(
            model=sherpa_onnx.AudioTaggingModelConfig(ced=str(CED_DIR / "model.int8.onnx"), num_threads=4, provider="cpu"),
            labels=str(CED_DIR / "class_labels_indices.csv"), top_k=40)
        self.tagger = sherpa_onnx.AudioTagging(cfg)
        self.device = device
        self.clap = None
        if use_clap:
            import torch
            from transformers import ClapModel, ClapProcessor
            self.torch = torch
            self.clap_proc = ClapProcessor.from_pretrained(CLAP_MODEL)
            self.clap = ClapModel.from_pretrained(CLAP_MODEL).to(device).eval()
            self._text_cache = {}

    # ---- CED
    def tag(self, wave):
        st = self.tagger.create_stream()
        st.accept_waveform(sample_rate=SR, waveform=wave)
        return {e.name: float(e.prob) for e in self.tagger.compute(st)}

    # ---- CLAP
    def audioset_prompts(self):
        if not hasattr(self, "_as_prompts"):
            import csv
            rows = list(csv.reader(open(CED_DIR / "class_labels_indices.csv", encoding="utf-8")))[1:]
            self._as_prompts = [f"the sound of {r[2].lower()}" for r in rows]
        return self._as_prompts

    def text_vecs(self, texts):
        key = tuple(texts)
        if key not in self._text_cache:
            t = self.clap_proc(text=list(texts), return_tensors="pt", padding=True).to(self.device)
            with self.torch.no_grad():
                v = _emb(self.clap.get_text_features(**t))
            self._text_cache[key] = v
        return self._text_cache[key]

    def audio_vecs(self, waves):
        import librosa
        w48 = [librosa.resample(w, orig_sr=SR, target_sr=48000) for w in waves]
        a = self.clap_proc(audio=w48, sampling_rate=48000, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            return _emb(self.clap.get_audio_features(**a))

    def listen(self, audio, bank=None):
        """-> (events, window vectors). bank: [(tag, vec)] taught by the user."""
        n = len(audio) / SR
        starts = np.arange(0, max(n - WIN, 0) + 1e-6, HOP) if n > WIN else np.array([0.0])
        waves = [audio[int(s * SR):int((s + WIN) * SR)] for s in starts]
        hits = []          # (t0, tag, group, score, source)
        for s, w in zip(starts, waves):
            if len(w) < 0.5 * SR:
                continue
            for name, p in self.tag(w).items():
                t = TAGS.get(name)
                if t and p >= t[2]:
                    hits.append((float(s), t[0], t[1], p, "ced"))
        vecs = None
        if self.clap is not None and waves:
            vecs = self.audio_vecs([w if len(w) >= SR else np.pad(w, (0, SR - len(w))) for w in waves])
            # open-set: a custom sound must be the BEST description among all 527 AudioSet classes
            # too ("the sound of a siren" ...). A closed softmax over only our list called finger
            # snapping "refrigerator" at 1.0 (test 2026-10-06).
            labels = custom_labels()
            names, prompts = [], []
            for tag, ps in labels.items():
                for p in ps:
                    names.append(tag); prompts.append(p)
            T = self.text_vecs(prompts + self.audioset_prompts())
            sims = (vecs @ T.T).float().cpu().numpy()                       # windows x (custom + audioset)
            k = len(prompts)
            for i, s in enumerate(starts):
                j = int(np.argmax(sims[i, :k]))
                best_custom, other = float(sims[i, j]), float(sims[i, k:].max())
                if best_custom >= CLAP_MIN_SIM and best_custom - other >= CLAP_MARGIN:
                    hits.append((float(s), names[j], "שלי", best_custom, "clap"))
            if bank:
                V = vecs.float().cpu().numpy()
                for i, s in enumerate(starts):
                    best = max(((float(V[i] @ v), tag) for tag, v in bank), default=(0, None))
                    if best[1] and best[0] >= BANK_MIN_SIM:
                        hits.append((float(s), best[1], "לימדת", best[0], "taught"))
        # merge consecutive windows of one tag
        hits.sort(key=lambda h: (h[1], h[0]))
        events = []
        for s, tag, grp, p, src in hits:
            e = events[-1] if events else None
            if e and e["tag"] == tag and s - e["t1"] <= HOP + 1e-6:
                e["t1"] = round(s + WIN, 1)
                e["score"] = round(max(e["score"], p), 2)
            else:
                events.append({"tag": tag, "group": grp, "t0": round(s, 1), "t1": round(min(s + WIN, n), 1),
                               "score": round(p, 2), "source": src})
        events.sort(key=lambda e: e["t0"])
        return events, (vecs.float().cpu().numpy() if vecs is not None else None), starts


def main():
    import voice_embed as VE
    E = Ears()
    for f in sys.argv[1:]:
        a = VE.read_audio(f, max_s=600)
        ev, _, _ = E.listen(a)
        print(f, len(a) / SR, "s")
        for e in ev:
            print("  ", e)


if __name__ == "__main__":
    main()
