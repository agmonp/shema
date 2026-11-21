import{r as s,j as l,C as Q,P as Z,u as ee,b as te}from"./r3f-DPvRo076.js";import{E as oe,I as K,j as O,k as ae,l as G,h as L,c as B,f as k,F as E,m as R,n as re,o as U}from"./three-Qho4-kCD.js";import{s as z}from"./index-DtsmaHwe.js";import"./motion-DA0HTlKj.js";const ne=`
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
`,se=`
${ne}
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
`,ie=`
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
`,ce=`
attribute float aAngle;
uniform float uTime, uIndex, uAmp, uAudio, uRadius;
void main(){
  float a = aAngle;
  float w = sin(a * 6.0 + uTime * 1.15 + uIndex * 1.7) * 0.6 + sin(a * 11.0 - uTime * 0.8 + uIndex) * 0.4;
  float r = uRadius * (1.0 + w * (0.012 + uAmp * 0.02 + uAudio * 0.085));
  vec3 p = vec3(cos(a) * r, sin(a) * r, 0.0);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`,ue=`
uniform float uOp, uWarm, uIndex;
void main(){
  vec3 cool = vec3(0.72, 0.72, 0.76);
  vec3 warm = vec3(0.83, 0.69, 0.48);
  gl_FragColor = vec4(mix(cool, warm, uWarm), uOp * (1.0 - uIndex / 7.5) * 0.32);
}
`,le=`
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`,me=`
uniform vec3 uColor;
uniform float uOp;
varying vec2 vUv;
void main(){
  float d = length(vUv - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.4) * uOp;
  gl_FragColor = vec4(uColor * a, a);
}
`,ve=`
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
`,de=`
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
`,u={liquid:[1,.06,.08,.42,.22],facet:[0,1,1,0,0],warm:[0,0,0,1,.85],breath:[.3,0,0,1,.7],rings:[1,.22,.4,.18,1],halo:[0,0,0,0,1],parts:[.3,.35,.25,.8,.6],glow:[.22,.3,.3,.5,.45],x:[-1.7,-1.6,1.6,-1.55,0],y:[0,0,0,.05,.82],s:[.86,.8,.8,.9,.55],mx:[0,0,0,0,0],my:[1.3,.55,1.05,.7,.95],ms:[.48,.55,.5,.6,.5]},pe=["#09090B","#09090B","#09090B","#0D0B09","#0B0A09"].map(e=>new L(e)),fe=["#8E8E93","#B9B9C0","#D4AF7A","#D4AF7A","#D4AF7A"].map(e=>new L(e)),X=e=>e*e*(3-2*e);function f(e,o){const a=Math.min(Math.floor(o),e.length-2),r=X(Math.min(Math.max(o-a,0),1));return e[a]+(e[a+1]-e[a])*r}function H(e,o,a){const r=Math.min(Math.floor(o),e.length-2);return a.copy(e[r]).lerp(e[r+1],X(Math.min(Math.max(o-r,0),1)))}function he(){const e=document.querySelectorAll("[data-stage]"),o=window.innerHeight;let a=0;return e.forEach((r,m)=>{if(m===0)return;const x=r.getBoundingClientRect().top;a+=Math.min(Math.max((o*.78-x)/(o*.6),0),1)}),a}function xe(e){const o=new K(1,1),a=o.attributes.position,r=[],m=[],x=[],g=new B,M=new B,P=new B,T=new B,N=new B,y=new B,h=(d,v)=>g.clone().addScaledVector(T,d/e).addScaledVector(N,v/e);for(let d=0;d<a.count;d+=3){g.fromBufferAttribute(a,d),M.fromBufferAttribute(a,d+1),P.fromBufferAttribute(a,d+2),T.subVectors(M,g),N.subVectors(P,g),y.crossVectors(T,N).normalize(),y.dot(g.clone().add(M).add(P))<0&&y.negate();const v=n=>{r.push(n.x,n.y,n.z);const c=n.clone().normalize();m.push(c.x,c.y,c.z),x.push(y.x,y.y,y.z)};for(let n=0;n<e;n++)for(let c=0;c<e-n;c++)v(h(n,c)),v(h(n+1,c)),v(h(n,c+1)),n+c<e-1&&(v(h(n+1,c)),v(h(n+1,c+1)),v(h(n,c+1)))}o.dispose();const w=new k;return w.setAttribute("position",new E(r,3)),w.setAttribute("aSphere",new E(m,3)),w.setAttribute("aFaceN",new E(x,3)),w.computeBoundingSphere(),w}function ge(e){const o=new k,a=new Float32Array(e);for(let r=0;r<e;r++)a[r]=r/e*Math.PI*2;return o.setAttribute("position",new R(new Float32Array(e*3),3)),o.setAttribute("aAngle",new R(a,1)),o.boundingSphere=new re(new B,4),o}function ye(e){const o=new k,a=new Float32Array(e*3),r=new Float32Array(e);for(let m=0;m<e;m++){const x=2.2+Math.random()*4.2,g=Math.random()*Math.PI*2,M=Math.acos(2*Math.random()-1);a[m*3]=x*Math.sin(M)*Math.cos(g)*1.5,a[m*3+1]=x*Math.cos(M)*.9,a[m*3+2]=x*Math.sin(M)*Math.sin(g)-1.5,r[m]=Math.random()}return o.setAttribute("position",new R(a,3)),o.setAttribute("aSeed",new R(r,1)),o}const we=6;function Me(){const e=z.isMobile,{gl:o,camera:a,size:r}=ee(),m=s.useMemo(()=>xe(e?14:24),[e]),x=s.useMemo(()=>new oe(new K(1.08,1),1),[]),g=s.useMemo(()=>ge(e?160:256),[e]),M=s.useMemo(()=>ye(e?520:1400),[e]),P=s.useMemo(()=>new O({vertexShader:se,fragmentShader:ie,transparent:!0,uniforms:{uTime:{value:0},uLiquid:{value:1},uFacet:{value:0},uWarm:{value:0},uAudio:{value:0},uBreath:{value:0},uDim:{value:0}}}),[]),T=s.useMemo(()=>new ae({color:"#D4AF7A",transparent:!0,opacity:0,depthWrite:!1,blending:G}),[]),N=s.useMemo(()=>Array.from({length:we},(D,S)=>new O({vertexShader:ce,fragmentShader:ue,transparent:!0,depthWrite:!1,blending:G,uniforms:{uTime:{value:0},uIndex:{value:S},uAmp:{value:0},uAudio:{value:0},uRadius:{value:1.45+S*.32},uOp:{value:1},uWarm:{value:0}}})),[]),y=s.useMemo(()=>new O({vertexShader:le,fragmentShader:me,transparent:!0,depthWrite:!1,blending:G,uniforms:{uColor:{value:new L("#8E8E93")},uOp:{value:.3}}}),[]),h=s.useMemo(()=>new O({vertexShader:ve,fragmentShader:de,transparent:!0,depthWrite:!1,blending:G,uniforms:{uTime:{value:0},uSize:{value:e?7:9},uPix:{value:o.getPixelRatio()},uOp:{value:.4},uWarm:{value:0}}}),[o,e]),w=s.useRef(null),d=s.useRef(null),v=s.useRef(null),n=s.useRef(null),c=s.useRef({stage:0,audio:0,mx:0,my:0,dim:0}),I=s.useMemo(()=>new B,[]),Y=s.useMemo(()=>new L,[]),$=document.body.style,J=(D,S)=>{I.copy(D).project(a);const b=(I.x+1)/2*r.width,A=(1-I.y)/2*r.height,t=a.fov,F=S*1.15*r.height/(2*Math.tan(U.degToRad(t/2))*6),i=4*F*F;let p=0;return document.querySelectorAll("[data-dense]").forEach(V=>{const j=V.getBoundingClientRect(),C=Math.min(j.right,b+F)-Math.max(j.left,b-F),_=Math.min(j.bottom,A+F)-Math.max(j.top,A-F);C>0&&_>0&&(p+=C*_)}),Math.min(1,p/i*1.8)};return te((D,S)=>{const b=Math.min(S,.05),A=D.clock.elapsedTime,t=c.current,F=1-Math.exp(-b*(z.reducedMotion?20:4));z.stage=he(),t.stage+=(z.stage-t.stage)*F;const i=t.stage;t.audio+=(z.demoLevel-t.audio)*(1-Math.exp(-b*12)),t.mx+=(z.mouseX-t.mx)*(1-Math.exp(-b*3)),t.my+=(z.mouseY-t.my)*(1-Math.exp(-b*3));const p=P.uniforms;p.uTime.value=A,p.uLiquid.value=f(u.liquid,i),p.uFacet.value=f(u.facet,i),p.uWarm.value=f(u.warm,i),p.uBreath.value=f(u.breath,i),p.uAudio.value=t.audio,T.opacity=f(u.facet,i)*(.32+t.audio*.6)*(1-t.dim*.75),w.current.position.set(f(e?u.mx:u.x,i),f(e?u.my:u.y,i)+Math.sin(A*.6)*.05,0);const V=f(e?u.ms:u.s,i)*(1+t.audio*.06)*(1-t.dim*.14);w.current.scale.setScalar(V),t.dim+=(J(w.current.position,V)-t.dim)*(1-Math.exp(-b*5)),p.uDim.value=t.dim;const j=p.uFacet.value;d.current.rotation.y+=b*(.12+j*.18+t.audio*.6),d.current.rotation.x=Math.sin(A*.2)*.25+t.my*.25,d.current.rotation.z=t.mx*-.15;const C=f(u.halo,i);v.current.rotation.x=U.lerp(1.12,0,C)+t.my*.35*(1-C),v.current.rotation.y=t.mx*.45*(1-C),v.current.scale.setScalar(1+C*.22);const _=f(u.rings,i),q=p.uWarm.value;for(const W of N)W.uniforms.uTime.value=A,W.uniforms.uAmp.value=1-j,W.uniforms.uAudio.value=t.audio,W.uniforms.uOp.value=_*(1-t.dim*.7),W.uniforms.uWarm.value=q;y.uniforms.uOp.value=f(u.glow,i)*(.5+t.audio*.8)*(1-t.dim*.85),H(fe,i,y.uniforms.uColor.value),h.uniforms.uTime.value=A,h.uniforms.uOp.value=f(u.parts,i),h.uniforms.uWarm.value=q,n.current.rotation.y=A*.015+t.mx*.08,$.backgroundColor="#"+H(pe,i,Y).getHexString()}),l.jsxs(l.Fragment,{children:[l.jsx("points",{ref:n,geometry:M,material:h}),l.jsxs("group",{ref:w,children:[l.jsx("mesh",{position:[0,0,-.6],material:y,renderOrder:-1,children:l.jsx("planeGeometry",{args:[6.5,6.5]})}),l.jsx("group",{ref:v,children:N.map((D,S)=>l.jsx("lineLoop",{geometry:g,material:D},S))}),l.jsxs("group",{ref:d,children:[l.jsx("mesh",{geometry:m,material:P}),l.jsx("lineSegments",{geometry:x,material:T})]})]})]})}function Fe(){const[e,o]=s.useState(()=>Math.min(window.devicePixelRatio||1,z.isMobile?1.5:2));return l.jsx("div",{className:"pointer-events-none fixed inset-0 z-0","aria-hidden":"true",children:l.jsxs(Q,{dpr:z.isMobile?[1,1.5]:e,camera:{position:[0,0,6],fov:40},gl:{antialias:!0,alpha:!0,powerPreference:"high-performance"},children:[l.jsx(Z,{onDecline:()=>o(1)}),l.jsx(Me,{})]})})}export{Fe as default};
