import { useEffect, useRef, useState } from 'react'
import { Download, ShieldAlert, X } from 'lucide-react'
import { GOOGLE_PLAY_URL } from '../config'
import { PlayIcon } from './DownloadButtons'

/** Fired by the "הורדה למחשב" buttons; the download itself opens in a new tab. */
export const PC_DOWNLOAD_EVENT = 'shema:pc-download'

const STEPS = [
  { where: 'בדפדפן Edge', how: ['⋯', 'שמור', 'הצג עוד', 'שמור בכל זאת'] },
  { where: 'במסך "Windows הגן על המחשב שלך"', how: ['מידע נוסף', 'הפעל בכל זאת'] },
]

export default function InstallTip() {
  const [open, setOpen] = useState(false)
  const close = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const show = () => setOpen(true)
    window.addEventListener(PC_DOWNLOAD_EVENT, show)
    return () => window.removeEventListener(PC_DOWNLOAD_EVENT, show)
  }, [])

  useEffect(() => {
    if (!open) return
    close.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <div
      className={`fixed inset-0 z-[60] flex items-end justify-center p-3 transition duration-500 md:items-center ${open ? 'visible opacity-100' : 'invisible opacity-0'}`}
      aria-hidden={!open}
    >
      <div className="absolute inset-0 bg-obsidian/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="install-tip-title"
        className={`surface relative w-full max-w-md rounded-[28px] p-7 transition duration-500 md:p-8 ${open ? 'translate-y-0' : 'translate-y-6'}`}
        style={{ background: 'linear-gradient(180deg, #17171B, #121215)' }}
      >
        <button
          ref={close}
          type="button"
          onClick={() => setOpen(false)}
          aria-label="סגירה"
          className="absolute end-5 top-5 grid h-9 w-9 place-items-center rounded-full text-mute transition hover:text-bone"
        >
          <X size={18} strokeWidth={1.25} />
        </button>

        <Download size={24} strokeWidth={1.25} className="text-gold" aria-hidden="true" />
        <h2 id="install-tip-title" className="mt-5 font-display text-[22px] font-medium tracking-tight text-bone">ההורדה התחילה</h2>
        <p className="mt-2 text-[15px] leading-relaxed text-mute">
          קובץ ההתקנה עוד לא חתום, אז Windows ישאל פעמיים אם להמשיך. כך עוברים:
        </p>

        <ol className="mt-6 space-y-4">
          {STEPS.map((s, i) => (
            <li key={s.where} className="flex gap-4">
              <span className="hairline grid h-7 w-7 shrink-0 place-items-center rounded-full text-[12px] tabular-nums text-gold">{i + 1}</span>
              <div>
                <p className="text-[14px] text-mute">{s.where}</p>
                <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[14px] text-bone">
                  {s.how.map((h, j) => (
                    <span key={h} className="flex items-center gap-1.5">
                      {j > 0 && <span className="text-mute/60">←</span>}
                      <span className="rounded-md bg-white/[.06] px-2 py-0.5">{h}</span>
                    </span>
                  ))}
                </p>
              </div>
            </li>
          ))}
        </ol>

        <p className="mt-6 flex gap-2 text-[13px] leading-relaxed text-mute">
          <ShieldAlert size={16} strokeWidth={1.25} className="mt-0.5 shrink-0" aria-hidden="true" />
          ההתקנה מורידה את מודלי התמלול (כמה GB) ולוקחת כמה דקות. בסוף נפתח המסך של שמע.
        </p>

        <div className="mt-7 border-t border-white/[.06] pt-6">
          <p className="text-[14px] text-mute">בינתיים, התקינו את שמע בטלפון:</p>
          <a
            href={GOOGLE_PLAY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="hairline mt-3 inline-flex items-center gap-2.5 rounded-full px-5 py-2.5 text-[14px] text-bone transition hover:border-gold/60"
          >
            <PlayIcon className="h-4 w-4 text-gold" /> הורדה ב-Google Play
          </a>
        </div>
      </div>
    </div>
  )
}
