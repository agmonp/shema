import { useEffect, useState } from 'react'
import DownloadButtons from './DownloadButtons'
import { audio } from '../audio/engine'

function SpeakerIcon({ on }: { on: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-[17px] w-[17px]" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" aria-hidden="true">
      <path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z" strokeLinejoin="round" />
      {on ? (
        <>
          <path d="M15.5 9a4.2 4.2 0 0 1 0 6" />
          <path d="M18 6.5a7.8 7.8 0 0 1 0 11" />
        </>
      ) : (
        <path d="m16 9.5 5 5m0-5-5 5" />
      )}
    </svg>
  )
}

export default function Navbar() {
  const [past, setPast] = useState(false)
  const [sound, setSound] = useState(false)

  // compact download buttons appear once the hero's big buttons leave the screen
  useEffect(() => {
    const el = document.getElementById('hero-cta')
    if (!el) return
    const io = new IntersectionObserver(([e]) => setPast(!e.isIntersecting && e.boundingClientRect.top < 0))
    io.observe(el)
    return () => io.disconnect()
  }, [])

  const toggle = () => {
    const on = !sound
    setSound(on)
    audio.setSound(on)
  }

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <nav className="mx-auto mt-3 flex h-14 max-w-6xl items-center justify-between gap-3 rounded-full border border-white/[.07] bg-obsidian/60 px-3 backdrop-blur-xl md:px-5 [margin-inline:16px] md:[margin-inline:auto]">
        <a href="#top" className="flex items-center gap-2.5 font-display text-[19px] font-medium tracking-tight text-bone" aria-label="שמע, לראש העמוד">
          <img src="shema-icon.svg" alt="" width={30} height={30} className="h-[30px] w-[30px] rounded-lg" />
          <span>שמע</span>
          <span className="hairline hidden rounded-full px-2 py-px text-[10px] font-medium tracking-[.14em] text-bone/70 sm:inline">PRO</span>
        </a>

        <div className="flex items-center gap-2">
          <div
            className={`transition-all duration-500 ${past ? 'visible translate-y-0 opacity-100' : 'invisible -translate-y-2 opacity-0'}`}
          >
            <DownloadButtons size="sm" className="!flex-nowrap !gap-2" />
          </div>
          <button
            type="button"
            onClick={toggle}
            aria-pressed={sound}
            aria-label={sound ? 'השתקת צלילי האתר' : 'הפעלת צלילי האתר'}
            title={sound ? 'צליל פועל' : 'צליל כבוי'}
            className="hairline grid h-9 w-9 shrink-0 place-items-center rounded-full text-mute transition hover:text-bone"
          >
            <SpeakerIcon on={sound} />
          </button>
        </div>
      </nav>
    </header>
  )
}
