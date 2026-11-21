import { useEffect, useState } from 'react'
import { DESKTOP_DOWNLOAD_URL, GOOGLE_PLAY_URL, RELEASES_API, TRIAL_DAYS } from '../config'
import { isAndroid } from '../store'
import { audio } from '../audio/engine'

export function WindowsIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="currentColor">
      <path d="M3 5.1 10.4 4v7.2H3zM11.4 3.9 21 2.5v8.7h-9.6zM3 12.3h7.4v7.2L3 18.4zm8.4 0H21v8.6l-9.6-1.4z" />
    </svg>
  )
}

export function PlayIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="currentColor">
      <path d="M4.6 2.4c-.4.3-.6.7-.6 1.3v16.6c0 .6.2 1 .6 1.3L13.8 12zm10.4 10.8-2 2-6.6 6.4 8.9-5.1zm0-2.4-1.7-1.6L6.4 2.4l8.6 5zm1.4.8 2.6 1.5c.9.5.9 1.3 0 1.8l-2.6 1.5L14.3 12z" />
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
  const base =
    'group relative inline-flex items-center gap-3 whitespace-nowrap rounded-full font-medium transition duration-300 ' +
    'focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-4 focus-visible:outline-gold'
  const pad = lg ? 'px-7 py-3.5 text-[16px] min-w-[230px]' : '!gap-1.5 px-2.5 py-1.5 text-[12.5px] sm:px-3.5 sm:py-2 sm:text-[13px]'
  const click = () => audio.click()

  const desktop = (
    <a
      key="pc"
      href={DESKTOP_DOWNLOAD_URL}
      target="_blank"
      rel="noopener noreferrer"
      onClick={click}
      className={`${base} ${pad} bg-bone text-obsidian hover:bg-white`}
    >
      <WindowsIcon className={lg ? 'h-5 w-5' : 'h-3.5 w-3.5'} />
      <span className="flex flex-col items-start leading-tight">
        <span>{lg ? 'הורדה למחשב' : 'למחשב'}</span>
        {lg && <span className="text-[12px] font-normal text-obsidian/55">Windows 10 / 11 · התקנה בקובץ אחד</span>}
      </span>
    </a>
  )
  const play = (
    <a
      key="play"
      href={GOOGLE_PLAY_URL}
      target="_blank"
      rel="noopener noreferrer"
      onClick={click}
      className={`${base} ${pad} hairline bg-white/[.02] text-bone backdrop-blur-md hover:border-gold/60`}
    >
      <PlayIcon className={lg ? 'h-5 w-5 text-gold' : 'h-3.5 w-3.5 text-gold'} />
      <span className="flex flex-col items-start leading-tight">
        <span>{lg ? 'הורדה ב-Google Play' : <><span className="hidden sm:inline">Google </span>Play</>}</span>
        {lg && <span className="text-[12px] font-normal text-mute">אנדרואיד · {TRIAL_DAYS} ימי ניסיון חינם</span>}
      </span>
    </a>
  )

  return (
    <div className={`flex flex-wrap items-center gap-3 ${className}`}>
      {isAndroid ? [play, desktop] : [desktop, play]}
    </div>
  )
}
