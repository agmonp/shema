import { lazy, Suspense, useLayoutEffect } from 'react'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import Lenis from 'lenis'
import Navbar from './components/Navbar'
import { Hero, Clarity, Business, Personal, Features, Footer } from './components/Sections'
import { store } from './store'

gsap.registerPlugin(ScrollTrigger)
const Scene3D = lazy(() => import('./components/Scene3D'))

function webglOK() {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}
const HAS_GL = webglOK()

export default function App() {
  useLayoutEffect(() => {
    // pointer for the rings / core tilt
    const onMove = (e: PointerEvent) => {
      store.mouseX = (e.clientX / window.innerWidth) * 2 - 1
      store.mouseY = (e.clientY / window.innerHeight) * 2 - 1
    }
    window.addEventListener('pointermove', onMove, { passive: true })

    // Lenis inertial scroll, driven by GSAP's ticker so ScrollTrigger stays in sync
    let lenis: Lenis | null = null
    const tick = (time: number) => lenis?.raf(time * 1000)
    if (!store.reducedMotion) {
      lenis = new Lenis({ duration: 1.15, smoothWheel: true })
      lenis.on('scroll', ScrollTrigger.update)
      gsap.ticker.add(tick)
      gsap.ticker.lagSmoothing(0)
    }

    // in-page links go through Lenis
    const onClick = (e: MouseEvent) => {
      const a = (e.target as HTMLElement).closest('a[href^="#"]') as HTMLAnchorElement | null
      if (!a) return
      const id = a.getAttribute('href')!
      const el = id === '#top' ? document.body : document.querySelector(id)
      if (!el) return
      e.preventDefault()
      if (lenis) lenis.scrollTo(el as HTMLElement, { offset: -20 })
      else (el as HTMLElement).scrollIntoView()
    }
    document.addEventListener('click', onClick)

    const ctx = gsap.context(() => {
      if (store.reducedMotion) return
      gsap.from('[data-hero]', { y: 36, opacity: 0, duration: 1.1, ease: 'power3.out', stagger: 0.12, delay: 0.15 })

      gsap.utils.toArray<HTMLElement>('[data-reveal]').forEach((el) => {
        gsap.from(el, {
          y: 48, opacity: 0, duration: 1.1, ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 88%' },
        })
      })

      if (!store.isMobile) {
        gsap.utils.toArray<HTMLElement>('[data-speed]').forEach((el) => {
          const sp = parseFloat(el.dataset.speed || '1')
          gsap.to(el, {
            yPercent: -28 * sp, ease: 'none',
            scrollTrigger: { trigger: el.closest('section'), start: 'top bottom', end: 'bottom top', scrub: true },
          })
        })
      }

      gsap.utils.toArray<HTMLElement>('[data-bar]').forEach((el) => {
        gsap.from(el, {
          scaleX: 0, duration: 1.4, ease: 'power2.out',
          scrollTrigger: { trigger: el, start: 'top 92%' },
        })
      })
    })

    return () => {
      window.removeEventListener('pointermove', onMove)
      document.removeEventListener('click', onClick)
      gsap.ticker.remove(tick)
      lenis?.destroy()
      ctx.revert()
    }
  }, [])

  return (
    <>
      {HAS_GL && (
        <Suspense fallback={null}>
          <Scene3D />
        </Suspense>
      )}
      <div className="grain" aria-hidden="true" />
      <Navbar />
      <main className="relative z-10">
        <Hero />
        <Clarity />
        <Business />
        <Personal />
        <Features />
      </main>
      <div className="relative z-10"><Footer /></div>
    </>
  )
}
