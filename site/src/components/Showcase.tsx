import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, Expand, Laptop, Smartphone, X } from 'lucide-react'
import { DESKTOP_SCREENSHOTS, MOBILE_SCREENSHOTS, type Shot } from '../screenshots'

type Mode = 'pc' | 'phone'
const ICON = { size: 18, strokeWidth: 1.25 } as const

// ---------------------------------------------------------------- lightbox
function Lightbox({ shots, index, onClose, onIndex }: {
  shots: Shot[]; index: number | null; onClose: () => void; onIndex: (i: number) => void
}) {
  const open = index !== null
  const closeBtn = useRef<HTMLButtonElement>(null)
  const go = useCallback((d: number) => {
    if (index === null) return
    onIndex((index + d + shots.length) % shots.length)
  }, [index, shots.length, onIndex])

  useEffect(() => {
    if (!open) return
    closeBtn.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      // RTL: the left arrow moves forward
      else if (e.key === 'ArrowLeft') go(1)
      else if (e.key === 'ArrowRight') go(-1)
    }
    window.addEventListener('keydown', onKey)
    const html = document.documentElement
    const prev = html.style.overflow
    html.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); html.style.overflow = prev }
  }, [open, go, onClose])

  if (index === null) return null
  const s = shots[index]
  const btn = 'grid h-11 w-11 place-items-center rounded-full border border-white/15 bg-obsidian/70 text-bone/80 transition hover:border-gold/60 hover:text-gold'
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={s.title} className="fixed inset-0 z-[70] flex flex-col bg-obsidian/95 backdrop-blur-md" data-lenis-prevent>
      <div className="flex items-center justify-between gap-4 px-4 py-3 md:px-6">
        <div className="min-w-0">
          <p className="truncate text-[15px] text-bone">{s.title}</p>
          <p className="truncate text-[13px] text-mute">{s.caption}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[12px] tabular-nums text-mute" dir="ltr">{index + 1} / {shots.length}</span>
          <button ref={closeBtn} type="button" onClick={onClose} aria-label="סגירה" className={btn}><X {...ICON} /></button>
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1 items-start justify-center overflow-auto px-4 pb-6 md:px-20" onClick={(e) => e.target === e.currentTarget && onClose()}>
        <img src={s.src} alt={`${s.title}: ${s.caption}`} className="h-auto max-w-full rounded-xl border border-white/10" style={{ width: s.w }} />
      </div>
      {shots.length > 1 && (
        <>
          <button type="button" onClick={() => go(-1)} aria-label="הקודם" className={`${btn} fixed right-3 top-1/2 -translate-y-1/2 md:right-6`}><ChevronRight {...ICON} /></button>
          <button type="button" onClick={() => go(1)} aria-label="הבא" className={`${btn} fixed left-3 top-1/2 -translate-y-1/2 md:left-6`}><ChevronLeft {...ICON} /></button>
        </>
      )}
    </div>,
    document.body,
  )
}

// ---------------------------------------------------------------- PC: window frame + thumbnails
function DesktopView({ onOpen }: { onOpen: (i: number) => void }) {
  const [i, setI] = useState(0)
  const shots = DESKTOP_SCREENSHOTS
  const s = shots[i]
  const step = (d: number) => setI((i + d + shots.length) % shots.length)
  const arrow = 'grid h-10 w-10 place-items-center rounded-full border border-white/15 text-bone/70 transition hover:border-gold/60 hover:text-gold'
  return (
    <div>
      <div className="mx-auto max-w-4xl overflow-hidden rounded-2xl border border-white/[.12] bg-surface shadow-[0_50px_100px_-30px_rgba(0,0,0,.85)]">
        <div className="flex items-center justify-between border-b border-white/[.08] px-4 py-2.5" dir="ltr">
          <div className="flex gap-1.5"><i className="h-2.5 w-2.5 rounded-full bg-white/15" /><i className="h-2.5 w-2.5 rounded-full bg-white/15" /><i className="h-2.5 w-2.5 rounded-full bg-white/15" /></div>
          <span className="text-[11px] text-mute">שמע · {s.title}</span>
          <span className="w-10" />
        </div>
        <button type="button" onClick={() => onOpen(i)} className="group relative block aspect-[16/10] w-full overflow-hidden bg-[#141210]" aria-label={`הגדלה: ${s.title}`}>
          {shots.map((x, k) => (
            <img
              key={x.src}
              src={x.src}
              alt={k === i ? `${x.title}: ${x.caption}` : ''}
              loading={k === 0 ? 'eager' : 'lazy'}
              className={`absolute inset-0 h-full w-full object-cover object-top transition-opacity duration-500 ${k === i ? 'opacity-100' : 'opacity-0'}`}
            />
          ))}
          <span className="absolute bottom-4 left-4 flex items-center gap-2 rounded-full border border-white/15 bg-obsidian/75 px-3 py-1.5 text-[12px] text-bone/85 opacity-0 backdrop-blur transition group-hover:opacity-100 group-focus-visible:opacity-100">
            <Expand size={14} strokeWidth={1.25} /> הגדלה
          </span>
        </button>
      </div>

      <div className="mx-auto mt-6 flex max-w-4xl items-center justify-between gap-4">
        <button type="button" onClick={() => step(-1)} aria-label="הקודם" className={arrow}><ChevronRight {...ICON} /></button>
        <div className="min-w-0 text-center">
          <p className="text-[16px] text-bone">{s.title}</p>
          <p className="mt-1 text-[14px] text-mute">{s.caption}</p>
        </div>
        <button type="button" onClick={() => step(1)} aria-label="הבא" className={arrow}><ChevronLeft {...ICON} /></button>
      </div>

      <div className="mx-auto mt-6 flex max-w-4xl gap-3 overflow-x-auto pb-2 [scrollbar-width:none]">
        {shots.map((x, k) => (
          <button
            key={x.src}
            type="button"
            onClick={() => setI(k)}
            aria-label={x.title}
            aria-current={k === i}
            className={`relative h-16 w-24 shrink-0 overflow-hidden rounded-lg border transition md:h-[72px] md:w-28 ${k === i ? 'border-gold/70 opacity-100' : 'border-white/10 opacity-50 hover:opacity-80'}`}
          >
            <img src={x.src} alt="" loading="lazy" className="h-full w-full object-cover object-top" />
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- phone: dark frames, swipe on small screens
function MobileView({ onOpen }: { onOpen: (i: number) => void }) {
  return (
    <div className="-mx-4 flex snap-x snap-mandatory gap-6 overflow-x-auto px-4 pb-4 [scrollbar-width:none] md:mx-0 md:justify-center md:gap-10 md:overflow-visible md:px-0">
      {MOBILE_SCREENSHOTS.map((s, k) => (
        <figure key={s.src} className={`w-[min(240px,64vw)] shrink-0 snap-center ${k === 1 ? 'md:-translate-y-6' : ''}`}>
          <button type="button" onClick={() => onOpen(k)} aria-label={`הגדלה: ${s.title}`} className="group block w-full rounded-[34px] border border-white/[.12] bg-[#0d0d10] p-2 shadow-[0_40px_80px_-30px_rgba(0,0,0,.9)] transition hover:border-gold/40">
            <div className="relative overflow-hidden rounded-[27px]">
              <span className="absolute left-1/2 top-2 z-10 h-1.5 w-14 -translate-x-1/2 rounded-full bg-black/80" />
              <img src={s.src} alt={`${s.title}: ${s.caption}`} loading="lazy" width={s.w} height={s.h} className="block h-auto w-full" />
            </div>
          </button>
          <figcaption className="mt-4 text-center">
            <p className="text-[15px] text-bone">{s.title}</p>
            <p className="mt-1 text-[13px] leading-snug text-mute">{s.caption}</p>
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- section
export default function Showcase() {
  const [mode, setMode] = useState<Mode>('pc')
  const [open, setOpen] = useState<number | null>(null)
  const shots = mode === 'pc' ? DESKTOP_SCREENSHOTS : MOBILE_SCREENSHOTS
  const tab = (m: Mode, Icon: typeof Laptop, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={mode === m}
      onClick={() => setMode(m)}
      className={`flex items-center gap-2 rounded-full border px-4 py-2 text-[14px] transition md:px-5 ${mode === m ? 'border-gold/60 bg-white/[.05] text-bone' : 'border-transparent text-mute hover:text-bone'}`}
    >
      <Icon {...ICON} className={mode === m ? 'text-gold' : ''} aria-hidden="true" /> {label}
    </button>
  )
  return (
    <section id="screens" className="relative px-4 py-24 md:px-8 md:py-36">
      <div className="mx-auto max-w-6xl">
        <div data-reveal data-dense className="mx-auto max-w-2xl text-center max-md:surface max-md:rounded-[28px] max-md:p-6">
          <span className="hairline inline-flex items-center gap-2.5 rounded-full px-3.5 py-1 text-[12px] tracking-[.08em] text-mute">
            <span className="h-1 w-1 rounded-full bg-gold" /> צילומי מסך אמיתיים
          </span>
          <h2 className="mt-6 font-display text-[clamp(34px,4.6vw,60px)] font-medium leading-[1.06] tracking-[-0.02em] text-bone">כך זה נראה בפועל</h2>
        </div>

        <div className="mt-10 flex justify-center">
          <div role="tablist" aria-label="בחירת מכשיר" className="surface flex gap-1 rounded-full p-1">
            {tab('pc', Laptop, 'תוכנת המחשב (Windows)')}
            {tab('phone', Smartphone, 'אפליקציית הטלפון (Android)')}
          </div>
        </div>

        <div data-dense className="mt-12">
          {mode === 'pc' ? <DesktopView onOpen={setOpen} /> : <MobileView onOpen={setOpen} />}
        </div>
      </div>
      <Lightbox shots={shots} index={open} onClose={() => setOpen(null)} onIndex={setOpen} />
    </section>
  )
}
