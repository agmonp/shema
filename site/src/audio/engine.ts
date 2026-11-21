// Web Audio: one context, one analyser that the 3D core listens to.
// - ambient pad + UI clicks only while the site sound is on (off by default)
// - the live demo is a silent visual simulation; a real clip (DEMO_AUDIO_URL) can be attached

class AudioEngine {
  private ctx: AudioContext | null = null
  private master!: GainNode
  private analyser!: AnalyserNode
  private data!: Uint8Array
  private ambientStop: (() => void) | null = null
  soundOn = false

  private ensure(): AudioContext {
    if (!this.ctx) {
      const AC =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new AC()
      this.master = ctx.createGain()
      this.master.gain.value = 0.9
      this.analyser = ctx.createAnalyser()
      this.analyser.fftSize = 256
      this.analyser.smoothingTimeConstant = 0.82
      this.master.connect(this.analyser)
      this.analyser.connect(ctx.destination)
      this.data = new Uint8Array(this.analyser.frequencyBinCount)
      this.ctx = ctx
    }
    if (this.ctx.state === 'suspended') void this.ctx.resume()
    return this.ctx
  }

  /** 0..1 loudness of the speech band. */
  level(): number {
    if (!this.ctx) return 0
    this.analyser.getByteFrequencyData(this.data)
    let sum = 0
    for (let i = 2; i < 48; i++) sum += this.data[i]
    return Math.min(1, sum / (46 * 255) * 1.6)
  }

  /** Frequency bins (0..255) for drawing a waveform. Returns null before any sound. */
  bins(): Uint8Array | null {
    if (!this.ctx) return null
    this.analyser.getByteFrequencyData(this.data)
    return this.data
  }

  setSound(on: boolean) {
    this.soundOn = on
    if (on) {
      this.ensure()
      this.startAmbient()
      this.click()
    } else {
      this.ambientStop?.()
      this.ambientStop = null
    }
  }

  click() {
    if (!this.soundOn) return
    const ctx = this.ensure()
    const t = ctx.currentTime
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.type = 'sine'
    o.frequency.setValueAtTime(940, t)
    o.frequency.exponentialRampToValueAtTime(620, t + 0.08)
    g.gain.setValueAtTime(0.0001, t)
    g.gain.exponentialRampToValueAtTime(0.05, t + 0.01)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12)
    o.connect(g).connect(this.master)
    o.start(t)
    o.stop(t + 0.14)
  }

  private startAmbient() {
    if (this.ambientStop || !this.ctx) return
    const ctx = this.ctx
    const t = ctx.currentTime
    const out = ctx.createGain()
    out.gain.setValueAtTime(0, t)
    out.gain.linearRampToValueAtTime(0.05, t + 2.5)
    const lp = ctx.createBiquadFilter()
    lp.type = 'lowpass'
    lp.frequency.value = 520
    lp.connect(out).connect(this.master)
    const lfo = ctx.createOscillator()
    const lfoGain = ctx.createGain()
    lfo.frequency.value = 0.07
    lfoGain.gain.value = 260
    lfo.connect(lfoGain).connect(lp.frequency)
    const oscs = [110, 164.81, 220.5, 329.6].map((f, i) => {
      const o = ctx.createOscillator()
      o.type = i === 2 ? 'triangle' : 'sine'
      o.frequency.value = f
      o.detune.value = (i - 1.5) * 4
      const g = ctx.createGain()
      g.gain.value = i === 3 ? 0.25 : 0.6
      o.connect(g).connect(lp)
      o.start()
      return o
    })
    lfo.start()
    this.ambientStop = () => {
      const now = ctx.currentTime
      out.gain.cancelScheduledValues(now)
      out.gain.setValueAtTime(out.gain.value, now)
      out.gain.linearRampToValueAtTime(0, now + 0.6)
      for (const o of [...oscs, lfo]) o.stop(now + 0.7)
    }
  }

  private media = new WeakMap<HTMLMediaElement, MediaElementAudioSourceNode>()

  /** Route a real recording (DEMO_AUDIO_URL) through the analyser so the core reacts to it. */
  attachMedia(el: HTMLMediaElement) {
    const ctx = this.ensure()
    if (!this.media.has(el)) {
      const src = ctx.createMediaElementSource(el)
      src.connect(this.master)
      this.media.set(el, src)
    }
  }
}
export const audio = new AudioEngine()
