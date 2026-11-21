// Shared, non-React state read every frame by the 3D scene (no re-renders).

const mq = (q: string) => typeof window !== 'undefined' && window.matchMedia(q).matches

export const store = {
  /** 0..4, which section the page is in (fractional while moving between them). */
  stage: 0,
  /** Pointer position, -1..1 on both axes. */
  mouseX: 0,
  mouseY: 0,
  /** 0..1 loudness from the Web Audio analyser. */
  audio: 0,
  /** The live demo is playing: the crystal pulses harder. */
  demoPlaying: false,
  /** 0..1 simulated speech level from the silent demo. */
  demoLevel: 0,
  isMobile: mq('(max-width: 767px)'),
  reducedMotion: mq('(prefers-reduced-motion: reduce)'),
}

export const isAndroid = typeof navigator !== 'undefined' && /Android/i.test(navigator.userAgent)
