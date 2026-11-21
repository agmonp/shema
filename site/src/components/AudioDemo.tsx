import { useEffect, useMemo, useRef, useState } from 'react'
import { Pause, Play, RotateCcw } from 'lucide-react'
import { audio } from '../audio/engine'
import { store } from '../store'
import { DEMO_AUDIO_URL } from '../config'

// A silent, visual simulation of a 10-second meeting. With DEMO_AUDIO_URL set, the same timeline
// follows the real clip's clock instead, and the 3D core listens to its sound.
export const DEMO_LENGTH = 10

/** Who speaks when (seconds); the transcript types itself during each turn. */
const LINES = [
  { from: 0.2, to: 2.0, who: 'דנה', text: 'אז סגרנו שההשקה זזה לשבוע הבא?' },
  { from: 2.2, to: 4.0, who: 'יואב', text: 'כן. אבל הסרטון חייב להיות מוכן עד חמישי.' },
  { from: 4.2, to: 5.7, who: 'דנה', text: 'אני מדברת עם הסטודיו עוד היום.' },
  { from: 5.9, to: 7.3, who: 'יואב', text: 'והתקציב לקמפיין נשאר עשרים אלף.' },
]
const SUMMARY = { at: 7.7, text: 'ההשקה נדחית בשבוע. הסרטון הוא מה שקובע את הלו״ז.' }
const DECISIONS = { at: 8.4, items: ['ההשקה עוברת לשבוע הבא', 'תקציב הקמפיין: ₪20,000'] }
const TASKS = { at: 9.1, items: [{ who: 'דנה', what: 'לתאם עם הסטודיו', when: 'היום' }, { who: 'יואב', what: 'סרטון מוכן', when: 'עד חמישי' }] }

/** Simulated speech loudness at time t: syllable-like flutter inside each speaker turn. */
function levelAt(t: number) {
  for (const [i, l] of LINES.entries()) {
    if (t >= l.from && t <= l.to) {
      const edge = Math.min(1, (t - l.from) / 0.12, (l.to - t) / 0.12)
      const syl = Math.abs(Math.sin(t * 15.7 + i)) * (0.55 + 0.45 * Math.abs(Math.sin(t * 4.3 + i * 2)))
      return edge * (0.25 + 0.6 * syl)
    }
  }
  return 0.03
}

const BARS = 72
const fade = (on: boolean) =>
  `transition-all duration-[900ms] ease-out ${on ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-1.5'}`

export default function AudioDemo() {
  const [playing, setPlaying] = useState(false)
  const [t, setT] = useState(-1) // seconds into the clip; -1 = not started
  const canvas = useRef<HTMLCanvasElement>(null)
  const clip = useRef<HTMLAudioElement | null>(null)
  const clock = useRef({ start: 0, offset: 0 })
  const tRef = useRef(-1)

  // the whole clip as a static waveform (like a voice memo): played part in champagne
  const shape = useMemo(
    () => Array.from({ length: BARS }, (_, i) => {
      const s = ((i + 0.5) / BARS) * DEMO_LENGTH
      let m = 0
      for (let k = -2; k <= 2; k++) m = Math.max(m, levelAt(s + k * 0.035))
      return Math.max(0.05, m)
    }),
    [],
  )

  const now = () =>
    clip.current ? clip.current.currentTime : clock.current.offset + (performance.now() - clock.current.start) / 1000

  useEffect(() => {
    if (DEMO_AUDIO_URL) {
      const el = new Audio(DEMO_AUDIO_URL)
      el.preload = 'auto'
      el.crossOrigin = 'anonymous'
      clip.current = el
    }
    return () => {
      clip.current?.pause()
      store.demoPlaying = false
      store.demoLevel = 0
    }
  }, [])

  // one animation loop: clock, transcript, waveform, and the 3D core's pulse
  useEffect(() => {
    const c = canvas.current!
    const ctx = c.getContext('2d')!
    let raf = 0
    let lastTenth = -2
    const draw = () => {
      const w = c.clientWidth, h = c.clientHeight, dpr = Math.min(devicePixelRatio, 2)
      if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr) }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)

      let time = tRef.current
      if (playing) {
        time = now()
        if (time >= DEMO_LENGTH) {
          time = DEMO_LENGTH
          setPlaying(false)
          store.demoPlaying = false
        }
        tRef.current = time
        const lvl = DEMO_AUDIO_URL ? audio.level() : levelAt(time)
        store.demoLevel = lvl
        if (Math.floor(time * 10) !== lastTenth) { lastTenth = Math.floor(time * 10); setT(time) }
      } else {
        store.demoLevel *= 0.9
      }

      const head = Math.max(0, time) / DEMO_LENGTH
      const gw = w / BARS
      const live = playing ? (DEMO_AUDIO_URL ? audio.level() : levelAt(time)) : 0
      // RTL: time runs from right to left
      for (let i = 0; i < BARS; i++) {
        const p = (i + 0.5) / BARS
        const played = p <= head
        const near = Math.max(0, 1 - Math.abs(p - head) * BARS / 3)
        const amp = shape[i] * (1 + near * live * 0.9)
        const bh = Math.max(2, amp * h * 0.9)
        ctx.fillStyle = played ? '#D4AF7A' : 'rgba(244,244,245,0.16)'
        ctx.globalAlpha = played ? 0.55 + 0.45 * near : 1
        const x = w - (i + 1) * gw + gw * 0.3
        ctx.beginPath()
        ctx.roundRect(x, (h - bh) / 2, gw * 0.4, bh, 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      if (time >= 0) {
        const x = w - head * w
        ctx.fillStyle = 'rgba(244,244,245,0.85)'
        ctx.fillRect(x - 0.5, 0, 1, h)
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [playing, shape])

  const toggle = () => {
    if (playing) {
      if (clip.current) clip.current.pause()
      else clock.current.offset = now()
      store.demoPlaying = false
      setPlaying(false)
      return
    }
    const restart = tRef.current < 0 || tRef.current >= DEMO_LENGTH
    if (restart) { tRef.current = 0; setT(0) }
    if (clip.current) {
      audio.attachMedia(clip.current)
      if (restart) clip.current.currentTime = 0
      void clip.current.play()
    } else {
      clock.current = { start: performance.now(), offset: restart ? 0 : tRef.current }
    }
    audio.click()
    store.demoPlaying = true
    setPlaying(true)
  }

  const done = t >= DEMO_LENGTH
  const secs = Math.max(0, Math.min(DEMO_LENGTH, Math.floor(t)))

  return (
    <div data-dense className="surface rounded-[28px] p-6 md:p-8">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="eyebrow">נסו את זה עכשיו</p>
          <h3 className="mt-1 font-display text-[22px] font-medium tracking-tight text-bone">פגישת צוות · 10 שניות</h3>
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? 'עצירה' : done ? 'הפעלה מחדש' : 'הפעלת הדוגמה'}
          className="hairline grid h-12 w-12 shrink-0 place-items-center rounded-full text-bone transition hover:border-gold/60 hover:text-gold focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-4 focus-visible:outline-gold"
        >
          {playing ? <Pause size={18} strokeWidth={1.25} /> : done ? <RotateCcw size={18} strokeWidth={1.25} /> : <Play size={18} strokeWidth={1.25} className="translate-x-[1px]" />}
        </button>
      </div>

      <canvas ref={canvas} className="mt-6 h-14 w-full" aria-hidden="true" />
      <div className="mt-2 flex justify-between text-[11px] tabular-nums text-mute" dir="ltr">
        <span>0:{String(secs).padStart(2, '0')}</span>
        <span>0:10</span>
      </div>

      <div className="mt-6 min-h-[132px] space-y-2.5 border-t border-white/[.06] pt-5" aria-live="polite">
        {t < 0 && <p className="text-[14px] leading-relaxed text-mute">לחצו על הכפתור וראו איך עשר שניות של פגישה הופכות לתמלול, החלטות ומשימות.</p>}
        {LINES.map((l) => {
          if (t < l.from) return null
          const n = Math.ceil(l.text.length * Math.min(1, (t - l.from) / (l.to - l.from)))
          const typing = n < l.text.length
          return (
            <p key={l.from} className="text-[15px] leading-relaxed">
              <span className="me-2 text-[12px] font-medium tracking-wide text-gold">{l.who}</span>
              <span className="text-bone/90">{l.text.slice(0, n)}</span>
              {typing && <span className="ms-0.5 inline-block h-[1em] w-px translate-y-[2px] animate-pulse bg-gold" />}
            </p>
          )
        })}
      </div>

      <div className="mt-5 grid gap-px overflow-hidden rounded-2xl border border-white/[.06] bg-white/[.06] md:grid-cols-3">
        <div className={`bg-surface p-4 ${fade(t >= SUMMARY.at)}`}>
          <p className="eyebrow mb-2">סיכום מנהלים</p>
          <p className="text-[14px] leading-snug text-bone/90">{SUMMARY.text}</p>
        </div>
        <div className={`bg-surface p-4 ${fade(t >= DECISIONS.at)}`}>
          <p className="eyebrow mb-2">החלטות</p>
          <ul className="space-y-1 text-[14px] leading-snug text-bone/90">
            {DECISIONS.items.map((d) => <li key={d} className="flex gap-2"><span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-gold" />{d}</li>)}
          </ul>
        </div>
        <div className={`bg-surface p-4 ${fade(t >= TASKS.at)}`}>
          <p className="eyebrow mb-2">משימות להמשך</p>
          <ul className="space-y-1 text-[14px] leading-snug text-bone/90">
            {TASKS.items.map((d) => (
              <li key={d.who}><span className="text-gold">{d.who}</span> · {d.what} <span className="text-mute">({d.when})</span></li>
            ))}
          </ul>
        </div>
      </div>
      <p className="mt-4 text-[11.5px] text-mute/80">
        {DEMO_AUDIO_URL ? 'הקלטה לדוגמה.' : 'הדמיה ויזואלית, בלי קול.'} בשמע האמיתי התמלול והסיכום רצים על המחשב שלכם.
      </p>
    </div>
  )
}
