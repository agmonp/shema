// GLSL for the Acoustic Core, the sound rings, the glow and the particles.

// Ashima Arts 3D simplex noise (MIT), the standard webgl-noise implementation.
const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0);
  const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy));
  vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);
  vec3 l=1.0-g;
  vec3 i1=min(g.xyz,l.zxy);
  vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;
  vec3 x2=x0-i2+C.yyy;
  vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857;
  vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z);
  vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy;
  vec4 y=y_*ns.x+ns.yyyy;
  vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);
  vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0;
  vec4 s1=floor(b1)*2.0+1.0;
  vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;
  vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);
  vec3 p1=vec3(a0.zw,h.y);
  vec3 p2=vec3(a1.xy,h.z);
  vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);
  m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
`

/**
 * The core is one mesh that morphs between three looks:
 *  liquid sphere (aSphere + noise)  ->  faceted crystal (flat triangles)  ->  warm breathing orb.
 */
export const coreVertex = /* glsl */ `
${NOISE}
attribute vec3 aSphere;
attribute vec3 aFaceN;
uniform float uTime, uLiquid, uFacet, uAudio, uBreath;
varying vec3 vN;
varying vec3 vPos;
varying float vDisp;
float field(vec3 s, float t){
  return snoise(s * 1.4 + vec3(t, t * 0.7, -t)) * 0.7 + snoise(s * 2.6 - t * 1.3) * 0.3;
}
void main(){
  vec3 sph = normalize(aSphere);
  float t = uTime * 0.28;
  float amp = uLiquid * 0.075 + uAudio * 0.2 * (1.0 - 0.85 * uFacet);
  float d = field(sph, t);

  // smooth surface normal of the displaced sphere (finite differences), so the glass shades
  // as one continuous surface: no per-triangle facets or blocky highlights
  vec3 tA = normalize(cross(sph, abs(sph.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
  vec3 tB = cross(sph, tA);
  float e = 0.03;
  vec3 sA = normalize(sph + tA * e), sB = normalize(sph + tB * e);
  vec3 p0 = sph * (1.0 + d * amp);
  vec3 pA = sA * (1.0 + field(sA, t) * amp);
  vec3 pB = sB * (1.0 + field(sB, t) * amp);
  vec3 nSmooth = normalize(cross(pA - p0, pB - p0));
  if (dot(nSmooth, sph) < 0.0) nSmooth = -nSmooth;

  vec3 base = mix(sph, position * 1.08, uFacet);
  vec3 n = normalize(mix(nSmooth, aFaceN, uFacet));
  float breath = 1.0 + sin(uTime * 0.85) * 0.04 * uBreath;
  vec3 p = base * breath * (1.0 + uAudio * 0.08 * uFacet) + sph * d * amp;
  vDisp = d;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vN = normalize(normalMatrix * n);
  vPos = mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`

export const coreFragment = /* glsl */ `
uniform float uFacet, uWarm, uAudio, uLiquid, uTime, uDim;
varying vec3 vN;
varying vec3 vPos;
varying float vDisp;
void main(){
  // smooth glass uses the interpolated normal only; the crystal uses the true flat facet normal
  vec3 dN = normalize(cross(dFdx(vPos), dFdy(vPos)));
  vec3 N = normalize(mix(normalize(vN), dN, uFacet));
  vec3 V = normalize(-vPos);
  float ndv = clamp(dot(N, V), 0.0, 1.0);
  float fres = pow(1.0 - ndv, 3.0);
  float rim = smoothstep(0.55, 1.0, 1.0 - ndv);

  vec3 obs = vec3(0.035, 0.035, 0.042);     // obsidian
  vec3 silver = vec3(0.86, 0.86, 0.89);     // bone / brushed silver
  vec3 champ = vec3(0.831, 0.686, 0.478);   // #D4AF7A

  vec3 L1 = normalize(vec3(0.55, 0.8, 0.65));
  vec3 L2 = normalize(vec3(-0.7, -0.2, 0.5));
  vec3 H1 = normalize(L1 + V);
  float diff = max(dot(N, L1), 0.0);

  // 1. translucent obsidian glass: dark see-through body, Fresnel rim, champagne edge glow
  float sky = smoothstep(0.15, 1.0, N.y) * (1.0 - ndv);          // soft studio window from above
  float sheen = pow(max(dot(N, H1), 0.0), 60.0);                // one small round highlight
  float bloom = pow(max(dot(N, H1), 0.0), 8.0) * 0.06;          // and its wide soft falloff
  vec3 glass = obs + silver * fres * 0.9 + silver * sky * 0.22;
  glass += champ * rim * 0.55 + champ * pow(fres, 6.0) * 0.6;
  glass += silver * (sheen * 0.55 + bloom);
  float aGlass = mix(0.28, 0.96, fres);

  // 2. faceted smoked crystal (unchanged look)
  float facet = 0.5 + 0.5 * dot(N, normalize(vec3(0.3, 0.9, 0.4)));
  float spec = pow(max(dot(reflect(-L1, N), V), 0.0), 90.0);
  vec3 crystal = obs * 1.7 + silver * facet * 0.13 + silver * fres * 0.7 + champ * diff * 0.08;
  crystal += silver * spec * 1.2;
  float aCrystal = mix(0.86, 0.98, fres);

  // 3. champagne glass, breathing: warm see-through body with a glowing gold rim
  float breathe = 0.85 + 0.15 * sin(uTime * 0.85);
  vec3 warm = champ * 0.10 * breathe + champ * fres * 1.15 + mix(champ, vec3(1.0, 0.95, 0.86), 0.6) * rim * 0.45;
  warm += champ * sky * 0.18 + vec3(1.0, 0.95, 0.86) * (sheen * 0.45 + bloom);
  float aWarm = mix(0.32, 0.96, fres);

  vec3 col = mix(mix(glass, crystal, uFacet), warm, uWarm);
  col += champ * pow(max(dot(reflect(-L2, N), V), 0.0), 30.0) * 0.12 * uFacet;
  col += champ * uAudio * 0.4;
  col *= 1.0 - uDim * 0.55;

  float alpha = mix(mix(aGlass, aCrystal, uFacet), aWarm, uWarm) * (1.0 - uDim * 0.55);
  gl_FragColor = vec4(col, alpha);
}
`

export const ringVertex = /* glsl */ `
attribute float aAngle;
uniform float uTime, uIndex, uAmp, uAudio, uRadius;
void main(){
  float a = aAngle;
  float w = sin(a * 6.0 + uTime * 1.15 + uIndex * 1.7) * 0.6 + sin(a * 11.0 - uTime * 0.8 + uIndex) * 0.4;
  float r = uRadius * (1.0 + w * (0.012 + uAmp * 0.02 + uAudio * 0.085));
  vec3 p = vec3(cos(a) * r, sin(a) * r, 0.0);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`

export const ringFragment = /* glsl */ `
uniform float uOp, uWarm, uIndex;
void main(){
  vec3 cool = vec3(0.72, 0.72, 0.76);
  vec3 warm = vec3(0.83, 0.69, 0.48);
  gl_FragColor = vec4(mix(cool, warm, uWarm), uOp * (1.0 - uIndex / 7.5) * 0.32);
}
`

export const glowVertex = /* glsl */ `
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`

export const glowFragment = /* glsl */ `
uniform vec3 uColor;
uniform float uOp;
varying vec2 vUv;
void main(){
  float d = length(vUv - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.4) * uOp;
  gl_FragColor = vec4(uColor * a, a);
}
`

export const particleVertex = /* glsl */ `
attribute float aSeed;
uniform float uTime, uSize, uPix;
varying float vSeed;
void main(){
  vec3 p = position;
  float s = aSeed * 6.2831;
  p.y += sin(uTime * 0.22 + s) * 0.35;
  p.x += cos(uTime * 0.17 + s * 1.3) * 0.22;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = uSize * uPix * (0.45 + aSeed) * (6.0 / -mv.z);
  vSeed = aSeed;
  gl_Position = projectionMatrix * mv;
}
`

export const particleFragment = /* glsl */ `
uniform float uOp, uWarm, uTime;
varying float vSeed;
void main(){
  float d = length(gl_PointCoord - 0.5) * 2.0;
  float a = smoothstep(1.0, 0.0, d);
  float tw = 0.55 + 0.45 * sin(uTime * (0.6 + vSeed) + vSeed * 30.0);
  vec3 cool = vec3(0.75, 0.75, 0.78);
  vec3 warm = vec3(0.83, 0.69, 0.48);
  gl_FragColor = vec4(mix(cool, warm, uWarm), a * a * uOp * tw * 0.7);
}
`