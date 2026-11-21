import { useEffect, useState } from 'react'
import { DESKTOP_DOWNLOAD_URL, GOOGLE_PLAY_URL, RELEASES_API } from '../config'
import { isAndroid } from '../store'

const PC_DOWNLOAD_EVENT = 'shema:pc-download' // same name as in InstallTip.tsx

/** The Windows logo: four panes in Microsoft blue. */
export function WindowsIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="#0078D4">
      <path d="M2 2h9.4v9.4H2zM12.6 2H22v9.4h-9.4zM2 12.6h9.4V22H2zM12.6 12.6H22V22h-9.4z" />
    </svg>
  )
}

/** The Google Play triangle in its four official colors. */
export function PlayIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path fill="#4285F4" d="M3.61 1.81 13.5 12 3.61 22.19a1.2 1.2 0 0 1-.36-.89V2.7c0-.35.13-.66.36-.89z" />
      <path fill="#34A853" d="M16.81 8.69 13.5 12 3.61 1.81c.3-.31.79-.35 1.24-.1z" />
      <path fill="#FBBC05" d="M20.3 10.69c.93.53.93 2.09 0 2.62l-3.49 2-3.31-3.31 3.31-3.31z" />
      <path fill="#EA4335" d="M16.81 15.31 4.85 22.29c-.45.25-.94.21-1.24-.1L13.5 12z" />
    </svg>
  )
}
/** "version 1.0.17 · 120 MB", fetched from GitHub; the button works without it. */
export function useReleaseMeta() {
  const [meta, setMeta] = useState<{ ver: string; mb: string } | null>(null)
  useEffect(() => {
    let live = true
    fetch(RELEASES_API)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((rel: { tag_name: string; assets?: { name: string; size: number }[] }) => {
        const a = rel.assets?.find((x) => x.name === 'ShemaSetup.exe')
        if (a && live) setMeta({ ver: rel.tag_name.replace(/^v/, ''), mb: `${(a.size / 1048576).toFixed(1)} MB` })
      })
      .catch(() => {})
    return () => { live = false }
  }, [])
  return meta
}

type Props = { size?: 'lg' | 'sm'; className?: string }

export default function DownloadButtons({ size = 'lg', className = '' }: Props) {
  const lg = size === 'lg'
  // Official-store look: crisp rounded rectangles, clear borders, lift on hover.
  const base =
    'group inline-flex items-center whitespace-nowrap rounded-[14px] border transition duration-200 ' +
    'hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-white'
  const box = lg ? 'min-h-[56px] gap-3 px-5 py-2' : 'min-h-[44px] gap-2 px-3 py-1.5'
  const icon = lg ? 'h-[26px] w-[26px] shrink-0' : 'h-[18px] w-[18px] shrink-0'

  const desktop = (
    <a
      key="pc"
      href={DESKTOP_DOWNLOAD_URL}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => setTimeout(() => window.dispatchEvent(new Event(PC_DOWNLOAD_EVENT)), 250)}
      className={`${base} ${box} border-white bg-[#FFFFFF] text-[#09090B] shadow-[0_8px_24px_-10px_rgba(255,255,255,.35)] hover:shadow-[0_14px_34px_-10px_rgba(255,255,255,.5)]`}
    >
      <WindowsIcon className={icon} />
      <span className="flex flex-col items-start leading-[1.15]">
        {lg && <span className="text-[11.5px] font-medium text-[#09090B]/60">ל-Windows 10 / 11</span>}
        <span className={lg ? 'text-[17px] font-semibold' : 'text-[13px] font-semibold'}>{lg ? 'הורדה למחשב' : 'למחשב'}</span>
      </span>
    </a>
  )
  const play = (
    <a
      key="play"
      href={GOOGLE_PLAY_URL}
      target="_blank"
      rel="noopener noreferrer"
      className={`${base} ${box} border-white/[.28] bg-[#000000] text-white shadow-[0_8px_24px_-12px_rgba(0,0,0,.9)] hover:border-white/50 hover:bg-[#121215]`}
    >
      <PlayIcon className={icon} />
      <span className="flex flex-col items-start leading-[1.15]" dir="rtl">
        {lg && <span className="text-[11.5px] font-medium text-white/70">להורדה ב-</span>}
        <span className={lg ? 'text-[19px] font-semibold tracking-tight' : 'text-[13px] font-semibold'} dir="ltr">Google Play</span>
      </span>
    </a>
  )

  return (
    <div className={`flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center ${lg ? '' : '!flex-row'} ${className}`}>
      {isAndroid ? [play, desktop] : [desktop, play]}
    </div>
  )
}