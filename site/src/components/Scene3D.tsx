import { useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { PerformanceMonitor } from '@react-three/drei'
import * as THREE from 'three'
import { store } from '../store'
import { audio } from '../audio/engine'
import {
  coreVertex, coreFragment, ringVertex, ringFragment,
  glowVertex, glowFragment, particleVertex, particleFragment,
} from './shaders'

// ---- the look of each section (index = stage 0..4) -------------------------
// 0 hero liquid sphere · 1 crystal · 2 crystal to the side · 3 warm breathing orb · 4 calm halo
const K = {
  liquid: [1, 0.06, 0.08, 0.42, 0.22],
  facet: [0, 1, 1, 0, 0],
  warm: [0, 0, 0, 1, 0.85],
  breath: [0.3, 0, 0, 1, 0.7],
  rings: [1, 0.22, 0.4, 0.18, 1],
  halo: [0, 0, 0, 0, 1],
  parts: [0.3, 0.35, 0.25, 0.8, 0.6],
  glow: [0.22, 0.3, 0.3, 0.5, 0.45],
  // desktop: text sits on the right (RTL), so the core goes left (-x) or right (+x)
  x: [-1.7, -1.6, 1.6, -1.55, 0],
  y: [0.0, 0, 0, 0.05, 0.82],
  s: [0.86, 0.8, 0.8, 0.9, 0.55],
  // phone: core stays centred, above the copy
  mx: [0, 0, 0, 0, 0],
  my: [1.3, 0.55, 1.05, 0.7, 0.95],
  ms: [0.48, 0.55, 0.5, 0.6, 0.5],
}
const BG = ['#09090B', '#09090B', '#09090B', '#0D0B09', '#0B0A09'].map((c) => new THREE.Color(c))
const GLOW = ['#8E8E93', '#B9B9C0', '#D4AF7A', '#D4AF7A', '#D4AF7A'].map((c) => new THREE.Color(c))

const smooth = (t: number) => t * t * (3 - 2 * t)
function at(arr: number[], s: number) {
  const i = Math.min(Math.floor(s), arr.length - 2)
  const f = smooth(Math.min(Math.max(s - i, 0), 1))
  return arr[i] + (arr[i + 1] - arr[i]) * f
}
function colorAt(arr: THREE.Color[], s: number, out: THREE.Color) {
  const i = Math.min(Math.floor(s), arr.length - 2)
  return out.copy(arr[i]).lerp(arr[i + 1], smooth(Math.min(Math.max(s - i, 0), 1)))
}

/** Sections marked data-stage drive the stage: entering section i moves it from i-1 to i. */
function readStage(): number {
  const els = document.querySelectorAll<HTMLElement>('[data-stage]')
  const vh = window.innerHeight
  let s = 0
  els.forEach((el, i) => {
    if (i === 0) return
    const top = el.getBoundingClientRect().top
    s += Math.min(Math.max((vh * 0.78 - top) / (vh * 0.6), 0), 1)
  })
  return s
}

// ---- geometry: icosahedron (80 flat faces) subdivided without projecting -----
function buildCore(sub: number) {
  const ico = new THREE.IcosahedronGeometry(1, 1)
  const src = ico.attributes.position
  const pos: number[] = []
  const sph: number[] = []
  const fn: number[] = []
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3()
  const ab = new THREE.Vector3(), ac = new THREE.Vector3(), n = new THREE.Vector3()
  const P = (i: number, j: number) =>
    a.clone().addScaledVector(ab, i / sub).addScaledVector(ac, j / sub)
  for (let t = 0; t < src.count; t += 3) {
    a.fromBufferAttribute(src, t)
    b.fromBufferAttribute(src, t + 1)
    c.fromBufferAttribute(src, t + 2)
    ab.subVectors(b, a)
    ac.subVectors(c, a)
    n.crossVectors(ab, ac).normalize()
    if (n.dot(a.clone().add(b).add(c)) < 0) n.negate()
    const push = (v: THREE.Vector3) => {
      pos.push(v.x, v.y, v.z)
      const s = v.clone().normalize()
      sph.push(s.x, s.y, s.z)
      fn.push(n.x, n.y, n.z)
    }
    for (let i = 0; i < sub; i++) {
      for (let j = 0; j < sub - i; j++) {
        push(P(i, j)); push(P(i + 1, j)); push(P(i, j + 1))
        if (i + j < sub - 1) { push(P(i + 1, j)); push(P(i + 1, j + 1)); push(P(i, j + 1)) }
      }
    }
  }
  ico.dispose()
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('aSphere', new THREE.Float32BufferAttribute(sph, 3))
  g.setAttribute('aFaceN', new THREE.Float32BufferAttribute(fn, 3))
  g.computeBoundingSphere()
  return g
}

function ringGeometry(seg: number) {
  const g = new THREE.BufferGeometry()
  const angles = new Float32Array(seg)
  for (let i = 0; i < seg; i++) angles[i] = (i / seg) * Math.PI * 2
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(seg * 3), 3))
  g.setAttribute('aAngle', new THREE.BufferAttribute(angles, 1))
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4)
  return g
}

function particleGeometry(count: number) {
  const g = new THREE.BufferGeometry()
  const p = new Float32Array(count * 3)
  const s = new Float32Array(count)
  for (let i = 0; i < count; i++) {
    const r = 2.2 + Math.random() * 4.2
    const th = Math.random() * Math.PI * 2
    const ph = Math.acos(2 * Math.random() - 1)
    p[i * 3] = r * Math.sin(ph) * Math.cos(th) * 1.5
    p[i * 3 + 1] = r * Math.cos(ph) * 0.9
    p[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th) - 1.5
    s[i] = Math.random()
  }
  g.setAttribute('position', new THREE.BufferAttribute(p, 3))
  g.setAttribute('aSeed', new THREE.BufferAttribute(s, 1))
  return g
}

const RING_COUNT = 6

function Experience() {
  const mobile = store.isMobile
  const { gl, camera, size } = useThree()
  const coreGeo = useMemo(() => buildCore(mobile ? 8 : 10), [mobile])
  const edgeGeo = useMemo(() => new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.08, 1), 1), [])
  const ringGeo = useMemo(() => ringGeometry(mobile ? 160 : 256), [mobile])
  const partGeo = useMemo(() => particleGeometry(mobile ? 520 : 1400), [mobile])

  const coreMat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: coreVertex, fragmentShader: coreFragment, transparent: true,
    uniforms: {
      uTime: { value: 0 }, uLiquid: { value: 1 }, uFacet: { value: 0 },
      uWarm: { value: 0 }, uAudio: { value: 0 }, uBreath: { value: 0 }, uDim: { value: 0 },
    },
  }), [])
  const edgeMat = useMemo(() => new THREE.LineBasicMaterial({
    color: '#D4AF7A', transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending,
  }), [])
  const ringMats = useMemo(() => Array.from({ length: RING_COUNT }, (_, i) => new THREE.ShaderMaterial({
    vertexShader: ringVertex, fragmentShader: ringFragment, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 }, uIndex: { value: i }, uAmp: { value: 0 }, uAudio: { value: 0 },
      uRadius: { value: 1.45 + i * 0.32 }, uOp: { value: 1 }, uWarm: { value: 0 },
    },
  })), [])
  const glowMat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: glowVertex, fragmentShader: glowFragment, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: { uColor: { value: new THREE.Color('#8E8E93') }, uOp: { value: 0.3 } },
  }), [])
  const partMat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: particleVertex, fragmentShader: particleFragment, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 }, uSize: { value: mobile ? 7 : 9 }, uPix: { value: gl.getPixelRatio() },
      uOp: { value: 0.4 }, uWarm: { value: 0 },
    },
  }), [gl, mobile])

  const holder = useRef<THREE.Group>(null!)
  const spin = useRef<THREE.Group>(null!)
  const rings = useRef<THREE.Group>(null!)
  const parts = useRef<THREE.Points>(null!)
  const st = useRef({ stage: 0, audio: 0, mx: 0, my: 0, dim: 0 })
  const proj = useMemo(() => new THREE.Vector3(), [])
  const tmp = useMemo(() => new THREE.Color(), [])
  const bodyStyle = document.body.style

  /** Share (0..1) of the core's on-screen disc covered by elements marked data-dense. */
  const coverage = (pos: THREE.Vector3, scale: number) => {
    proj.copy(pos).project(camera)
    const cx = ((proj.x + 1) / 2) * size.width
    const cy = ((1 - proj.y) / 2) * size.height
    const fov = (camera as THREE.PerspectiveCamera).fov
    const r = (scale * 1.15 * size.height) / (2 * Math.tan(THREE.MathUtils.degToRad(fov / 2)) * 6)
    const area = 4 * r * r
    let hit = 0
    document.querySelectorAll<HTMLElement>('[data-dense]').forEach((el) => {
      const b = el.getBoundingClientRect()
      const w = Math.min(b.right, cx + r) - Math.max(b.left, cx - r)
      const h = Math.min(b.bottom, cy + r) - Math.max(b.top, cy - r)
      if (w > 0 && h > 0) hit += w * h
    })
    return Math.min(1, (hit / area) * 1.8)
  }

  useFrame((state, dt) => {
    const d = Math.min(dt, 0.05)
    const t = state.clock.elapsedTime
    const S = st.current
    const k = 1 - Math.exp(-d * (store.reducedMotion ? 20 : 4))
    store.stage = readStage()
    S.stage += (store.stage - S.stage) * k
    const s = S.stage

    // sound in -> pulse (the demo counts double)
    const lvl = Math.max(audio.level() * (store.demoPlaying ? 1 : 0.35), store.demoLevel)
    S.audio += (lvl - S.audio) * (1 - Math.exp(-d * 12))
    store.audio = S.audio
    S.mx += (store.mouseX - S.mx) * (1 - Math.exp(-d * 3))
    S.my += (store.mouseY - S.my) * (1 - Math.exp(-d * 3))

    const u = coreMat.uniforms
    u.uTime.value = t
    u.uLiquid.value = at(K.liquid, s)
    u.uFacet.value = at(K.facet, s)
    u.uWarm.value = at(K.warm, s)
    u.uBreath.value = at(K.breath, s)
    u.uAudio.value = S.audio
    edgeMat.opacity = at(K.facet, s) * (0.32 + S.audio * 0.6) * (1 - S.dim * 0.75)

    holder.current.position.set(
      at(mobile ? K.mx : K.x, s),
      at(mobile ? K.my : K.y, s) + Math.sin(t * 0.6) * 0.05,
      0,
    )
    // dense text over the core? dim it and pull it back a little
    const sc = at(mobile ? K.ms : K.s, s) * (1 + S.audio * 0.06) * (1 - S.dim * 0.14)
    holder.current.scale.setScalar(sc)
    S.dim += (coverage(holder.current.position, sc) - S.dim) * (1 - Math.exp(-d * 5))
    u.uDim.value = S.dim

    const facet = u.uFacet.value
    spin.current.rotation.y += d * (0.12 + facet * 0.18 + S.audio * 0.6)
    spin.current.rotation.x = Math.sin(t * 0.2) * 0.25 + S.my * 0.25
    spin.current.rotation.z = S.mx * -0.15

    const halo = at(K.halo, s)
    rings.current.rotation.x = THREE.MathUtils.lerp(1.12, 0, halo) + S.my * 0.35 * (1 - halo)
    rings.current.rotation.y = S.mx * 0.45 * (1 - halo)
    rings.current.scale.setScalar(1 + halo * 0.22)
    const rop = at(K.rings, s)
    const warm = u.uWarm.value
    for (const m of ringMats) {
      m.uniforms.uTime.value = t
      m.uniforms.uAmp.value = 1 - facet
      m.uniforms.uAudio.value = S.audio
      m.uniforms.uOp.value = rop * (1 - S.dim * 0.7)
      m.uniforms.uWarm.value = warm
    }

    glowMat.uniforms.uOp.value = at(K.glow, s) * (0.5 + S.audio * 0.8) * (1 - S.dim * 0.85)
    colorAt(GLOW, s, glowMat.uniforms.uColor.value)

    partMat.uniforms.uTime.value = t
    partMat.uniforms.uOp.value = at(K.parts, s)
    partMat.uniforms.uWarm.value = warm
    parts.current.rotation.y = t * 0.015 + S.mx * 0.08

    bodyStyle.backgroundColor = '#' + colorAt(BG, s, tmp).getHexString()
  })

  return (
    <>
      <points ref={parts} geometry={partGeo} material={partMat} />
      <group ref={holder}>
        <mesh position={[0, 0, -0.6]} material={glowMat} renderOrder={-1}>
          <planeGeometry args={[6.5, 6.5]} />
        </mesh>
        <group ref={rings}>
          {ringMats.map((m, i) => (
            <lineLoop key={i} geometry={ringGeo} material={m} />
          ))}
        </group>
        <group ref={spin}>
          <mesh geometry={coreGeo} material={coreMat} />
          <lineSegments geometry={edgeGeo} material={edgeMat} />
        </group>
      </group>
    </>
  )
}

export default function Scene3D() {
  const [dpr, setDpr] = useState<number>(() =>
    Math.min(window.devicePixelRatio || 1, store.isMobile ? 1.5 : 2),
  )
  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden="true">
      <Canvas
        dpr={store.isMobile ? [1, 1.5] : dpr}
        camera={{ position: [0, 0, 6], fov: 40 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
      >
        <PerformanceMonitor onDecline={() => setDpr(1)} />
        <Experience />
      </Canvas>
    </div>
  )
}
