import { useEffect, useState } from 'react'
import DownloadButtons from './DownloadButtons'

export default function Navbar() {
  const [past, setPast] = useState(false)

  // compact download buttons appear once the hero's big buttons leave the screen
  useEffect(() => {
    const el = document.getElementById('hero-cta')
    if (!el) return
    const io = new IntersectionObserver(([e]) => setPast(!e.isIntersecting && e.boundingClientRect.top < 0))
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <nav className="mx-auto mt-3 flex h-16 max-w-6xl items-center justify-between gap-3 rounded-full border border-white/[.07] bg-obsidian/60 pe-2 ps-4 backdrop-blur-xl md:pe-2.5 md:ps-5 [margin-inline:16px] md:[margin-inline:auto]">
        <a href="#top" className="flex shrink-0 items-center gap-2.5 font-display text-[19px] font-medium tracking-tight text-bone" aria-label="שמע, לראש העמוד">
          <img src="shema-icon.svg" alt="" width={30} height={30} className="h-[30px] w-[30px] rounded-lg" />
          <span>שמע</span>
          <span className="hairline hidden rounded-full px-2 py-px text-[10px] font-medium tracking-[.14em] text-bone/70 sm:inline">PRO</span>
        </a>

        <div className={`transition-all duration-500 ${past ? 'visible translate-y-0 opacity-100' : 'invisible -translate-y-2 opacity-0'}`}>
          <DownloadButtons size="sm" className="!flex-nowrap !gap-2" />
        </div>
      </nav>
    </header>
  )
}
