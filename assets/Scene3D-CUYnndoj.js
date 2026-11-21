import{r as n,j as l,C as Z,P as ee,u as te,a as oe}from"./r3f-pKdTYIYg.js";import{E as ae,I as K,j as q,k as re,l as O,h as L,c as j,f as E,F as G,m as R,n as ie,o as U}from"./three-Qho4-kCD.js";import{s as h,a as ne}from"./index-BHNm-kQo.js";import"./motion-DA0HTlKj.js";const se=`
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
`,ce=`
${se}
attribute vec3 aSphere;
attribute vec3 aFaceN;
uniform float uTime, uLiquid, uFacet, uAudio, uBreath;
varying vec3 vN;
varying vec3 vPos;
varying float vDisp;
void main(){
  vec3 sph = normalize(aSphere);
  vec3 base = mix(sph, position * 1.08, uFacet);
  vec3 n = normalize(mix(sph, aFaceN, uFacet));
  float t = uTime * 0.32;
  float d = snoise(sph * 1.5 + vec3(t, t * 0.7, -t)) * 0.65 + snoise(sph * 3.1 - t * 1.4) * 0.3;
  float amp = uLiquid * 0.12 + uAudio * 0.26 * (1.0 - 0.85 * uFacet);
  float breath = 1.0 + sin(uTime * 0.85) * 0.045 * uBreath;
  vec3 p = base * breath * (1.0 + uAudio * 0.08 * uFacet) + sph * d * amp;
  vDisp = d;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vN = normalize(normalMatrix * n);
  vPos = mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`,ue=`
uniform float uFacet, uWarm, uAudio, uLiquid, uTime, uDim;
varying vec3 vN;
varying vec3 vPos;
varying float vDisp;
void main(){
  vec3 dN = normalize(cross(dFdx(vPos), dFdy(vPos)));
  vec3 N = normalize(mix(vN, dN, 0.12 + 0.88 * uFacet));
  vec3 V = normalize(-vPos);
  float ndv = max(dot(N, V), 0.0);
  float fres = pow(1.0 - ndv, 2.6);

  vec3 obs = vec3(0.050, 0.050, 0.058);     // obsidian
  vec3 silver = vec3(0.86, 0.86, 0.89);     // bone / brushed silver
  vec3 champ = vec3(0.831, 0.686, 0.478);   // #D4AF7A

  vec3 L1 = normalize(vec3(0.55, 0.8, 0.65));
  vec3 L2 = normalize(vec3(-0.7, -0.2, 0.5));
  float diff = max(dot(N, L1), 0.0);
  float spec = pow(max(dot(reflect(-L1, N), V), 0.0), mix(40.0, 90.0, uFacet));
  float spec2 = pow(max(dot(reflect(-L2, N), V), 0.0), 30.0);

  // 1. frosted obsidian glass: dark body, silver rim, a champagne kiss at grazing angles
  float sky = smoothstep(-0.1, 0.9, N.y);                       // soft studio reflection from above
  vec3 liquid = obs * 1.6 + silver * fres * 1.05 + champ * pow(fres, 3.0) * 0.55;
  liquid += silver * sky * 0.16 + silver * 0.06 * (0.5 + 0.5 * vDisp) * uLiquid;
  liquid += silver * diff * 0.07;
  // 2. faceted smoked crystal: each facet catches a slightly different amount of light
  float facet = 0.5 + 0.5 * dot(N, normalize(vec3(0.3, 0.9, 0.4)));
  vec3 crystal = obs * 1.5 + silver * facet * 0.13 + silver * fres * 0.7 + champ * diff * 0.08;
  // 3. champagne metal, breathing
  vec3 warm = champ * (0.28 + 0.42 * diff) + mix(champ, vec3(1.0, 0.94, 0.84), 0.5) * fres * 0.95;
  warm *= 0.92 + 0.08 * sin(uTime * 0.85);

  vec3 col = mix(mix(liquid, crystal, uFacet), warm, uWarm);
  col += mix(silver, champ, 0.3 + 0.5 * uWarm) * spec * (0.7 + 0.5 * uFacet);
  col += champ * spec2 * 0.18;
  col += champ * uAudio * 0.45;
  col *= 1.0 - uDim * 0.55;

  float alpha = mix(0.86, 0.98, fres) * (1.0 - uDim * 0.55);
  gl_FragColor = vec4(col, alpha);
}
`,le=`
attribute float aAngle;
uniform float uTime, uIndex, uAmp, uAudio, uRadius;
void main(){
  float a = aAngle;
  float w = sin(a * 6.0 + uTime * 1.15 + uIndex * 1.7) * 0.6 + sin(a * 11.0 - uTime * 0.8 + uIndex) * 0.4;
  float r = uRadius * (1.0 + w * (0.012 + uAmp * 0.02 + uAudio * 0.085));
  vec3 p = vec3(cos(a) * r, sin(a) * r, 0.0);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`,me=`
uniform float uOp, uWarm, uIndex;
void main(){
  vec3 cool = vec3(0.72, 0.72, 0.76);
  vec3 warm = vec3(0.83, 0.69, 0.48);
  gl_FragColor = vec4(mix(cool, warm, uWarm), uOp * (1.0 - uIndex / 7.5) * 0.32);
}
`,ve=`
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`,de=`
uniform vec3 uColor;
uniform float uOp;
varying vec2 vUv;
void main(){
  float d = length(vUv - 0.5) * 2.0;
  float a = pow(max(1.0 - d, 0.0), 2.4) * uOp;
  gl_FragColor = vec4(uColor * a, a);
}
`,pe=`
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
`,fe=`
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
`,u={liquid:[1,.06,.08,.42,.22],facet:[0,1,1,0,0],warm:[0,0,0,1,.85],breath:[.3,0,0,1,.7],rings:[1,.22,.4,.18,1],halo:[0,0,0,0,1],parts:[.3,.35,.25,.8,.6],glow:[.22,.3,.3,.5,.45],x:[-1.7,-1.6,1.6,-1.55,0],y:[0,0,0,.05,.82],s:[.86,.8,.8,.9,.55],mx:[0,0,0,0,0],my:[1.3,.55,1.05,.7,.95],ms:[.48,.55,.5,.6,.5]},xe=["#09090B","#09090B","#09090B","#0D0B09","#0B0A09"].map(e=>new L(e)),he=["#8E8E93","#B9B9C0","#D4AF7A","#D4AF7A","#D4AF7A"].map(e=>new L(e)),X=e=>e*e*(3-2*e);function p(e,o){const a=Math.min(Math.floor(o),e.length-2),r=X(Math.min(Math.max(o-a,0),1));return e[a]+(e[a+1]-e[a])*r}function H(e,o,a){const r=Math.min(Math.floor(o),e.length-2);return a.copy(e[r]).lerp(e[r+1],X(Math.min(Math.max(o-r,0),1)))}function ge(){const e=document.querySelectorAll("[data-stage]"),o=window.innerHeight;let a=0;return e.forEach((r,m)=>{if(m===0)return;const g=r.getBoundingClientRect().top;a+=Math.min(Math.max((o*.78-g)/(o*.6),0),1)}),a}function ye(e){const o=new K(1,1),a=o.attributes.position,r=[],m=[],g=[],y=new j,b=new j,C=new j,T=new j,D=new j,w=new j,f=(d,v)=>y.clone().addScaledVector(T,d/e).addScaledVector(D,v/e);for(let d=0;d<a.count;d+=3){y.fromBufferAttribute(a,d),b.fromBufferAttribute(a,d+1),C.fromBufferAttribute(a,d+2),T.subVectors(b,y),D.subVectors(C,y),w.crossVectors(T,D).normalize(),w.dot(y.clone().add(b).add(C))<0&&w.negate();const v=i=>{r.push(i.x,i.y,i.z);const c=i.clone().normalize();m.push(c.x,c.y,c.z),g.push(w.x,w.y,w.z)};for(let i=0;i<e;i++)for(let c=0;c<e-i;c++)v(f(i,c)),v(f(i+1,c)),v(f(i,c+1)),i+c<e-1&&(v(f(i+1,c)),v(f(i+1,c+1)),v(f(i,c+1)))}o.dispose();const M=new E;return M.setAttribute("position",new G(r,3)),M.setAttribute("aSphere",new G(m,3)),M.setAttribute("aFaceN",new G(g,3)),M.computeBoundingSphere(),M}function we(e){const o=new E,a=new Float32Array(e);for(let r=0;r<e;r++)a[r]=r/e*Math.PI*2;return o.setAttribute("position",new R(new Float32Array(e*3),3)),o.setAttribute("aAngle",new R(a,1)),o.boundingSphere=new ie(new j,4),o}function Me(e){const o=new E,a=new Float32Array(e*3),r=new Float32Array(e);for(let m=0;m<e;m++){const g=2.2+Math.random()*4.2,y=Math.random()*Math.PI*2,b=Math.acos(2*Math.random()-1);a[m*3]=g*Math.sin(b)*Math.cos(y)*1.5,a[m*3+1]=g*Math.cos(b)*.9,a[m*3+2]=g*Math.sin(b)*Math.sin(y)-1.5,r[m]=Math.random()}return o.setAttribute("position",new R(a,3)),o.setAttribute("aSeed",new R(r,1)),o}const be=6;function ze(){const e=h.isMobile,{gl:o,camera:a,size:r}=te(),m=n.useMemo(()=>ye(e?8:10),[e]),g=n.useMemo(()=>new ae(new K(1.08,1),1),[]),y=n.useMemo(()=>we(e?160:256),[e]),b=n.useMemo(()=>Me(e?520:1400),[e]),C=n.useMemo(()=>new q({vertexShader:ce,fragmentShader:ue,transparent:!0,uniforms:{uTime:{value:0},uLiquid:{value:1},uFacet:{value:0},uWarm:{value:0},uAudio:{value:0},uBreath:{value:0},uDim:{value:0}}}),[]),T=n.useMemo(()=>new re({color:"#D4AF7A",transparent:!0,opacity:0,depthWrite:!1,blending:O}),[]),D=n.useMemo(()=>Array.from({length:be},(N,S)=>new q({vertexShader:le,fragmentShader:me,transparent:!0,depthWrite:!1,blending:O,uniforms:{uTime:{value:0},uIndex:{value:S},uAmp:{value:0},uAudio:{value:0},uRadius:{value:1.45+S*.32},uOp:{value:1},uWarm:{value:0}}})),[]),w=n.useMemo(()=>new q({vertexShader:ve,fragmentShader:de,transparent:!0,depthWrite:!1,blending:O,uniforms:{uColor:{value:new L("#8E8E93")},uOp:{value:.3}}}),[]),f=n.useMemo(()=>new q({vertexShader:pe,fragmentShader:fe,transparent:!0,depthWrite:!1,blending:O,uniforms:{uTime:{value:0},uSize:{value:e?7:9},uPix:{value:o.getPixelRatio()},uOp:{value:.4},uWarm:{value:0}}}),[o,e]),M=n.useRef(null),d=n.useRef(null),v=n.useRef(null),i=n.useRef(null),c=n.useRef({stage:0,audio:0,mx:0,my:0,dim:0}),I=n.useMemo(()=>new j,[]),Y=n.useMemo(()=>new L,[]),$=document.body.style,J=(N,S)=>{I.copy(N).project(a);const z=(I.x+1)/2*r.width,A=(1-I.y)/2*r.height,t=a.fov,F=S*1.15*r.height/(2*Math.tan(U.degToRad(t/2))*6),s=4*F*F;let V=0;return document.querySelectorAll("[data-dense]").forEach(x=>{const P=x.getBoundingClientRect(),W=Math.min(P.right,z+F)-Math.max(P.left,z-F),B=Math.min(P.bottom,A+F)-Math.max(P.top,A-F);W>0&&B>0&&(V+=W*B)}),Math.min(1,V/s*1.8)};return oe((N,S)=>{const z=Math.min(S,.05),A=N.clock.elapsedTime,t=c.current,F=1-Math.exp(-z*(h.reducedMotion?20:4));h.stage=ge(),t.stage+=(h.stage-t.stage)*F;const s=t.stage,V=Math.max(ne.level()*(h.demoPlaying?1:.35),h.demoLevel);t.audio+=(V-t.audio)*(1-Math.exp(-z*12)),h.audio=t.audio,t.mx+=(h.mouseX-t.mx)*(1-Math.exp(-z*3)),t.my+=(h.mouseY-t.my)*(1-Math.exp(-z*3));const x=C.uniforms;x.uTime.value=A,x.uLiquid.value=p(u.liquid,s),x.uFacet.value=p(u.facet,s),x.uWarm.value=p(u.warm,s),x.uBreath.value=p(u.breath,s),x.uAudio.value=t.audio,T.opacity=p(u.facet,s)*(.32+t.audio*.6)*(1-t.dim*.75),M.current.position.set(p(e?u.mx:u.x,s),p(e?u.my:u.y,s)+Math.sin(A*.6)*.05,0);const P=p(e?u.ms:u.s,s)*(1+t.audio*.06)*(1-t.dim*.14);M.current.scale.setScalar(P),t.dim+=(J(M.current.position,P)-t.dim)*(1-Math.exp(-z*5)),x.uDim.value=t.dim;const W=x.uFacet.value;d.current.rotation.y+=z*(.12+W*.18+t.audio*.6),d.current.rotation.x=Math.sin(A*.2)*.25+t.my*.25,d.current.rotation.z=t.mx*-.15;const B=p(u.halo,s);v.current.rotation.x=U.lerp(1.12,0,B)+t.my*.35*(1-B),v.current.rotation.y=t.mx*.45*(1-B),v.current.scale.setScalar(1+B*.22);const Q=p(u.rings,s),k=x.uWarm.value;for(const _ of D)_.uniforms.uTime.value=A,_.uniforms.uAmp.value=1-W,_.uniforms.uAudio.value=t.audio,_.uniforms.uOp.value=Q*(1-t.dim*.7),_.uniforms.uWarm.value=k;w.uniforms.uOp.value=p(u.glow,s)*(.5+t.audio*.8)*(1-t.dim*.85),H(he,s,w.uniforms.uColor.value),f.uniforms.uTime.value=A,f.uniforms.uOp.value=p(u.parts,s),f.uniforms.uWarm.value=k,i.current.rotation.y=A*.015+t.mx*.08,$.backgroundColor="#"+H(xe,s,Y).getHexString()}),l.jsxs(l.Fragment,{children:[l.jsx("points",{ref:i,geometry:b,material:f}),l.jsxs("group",{ref:M,children:[l.jsx("mesh",{position:[0,0,-.6],material:w,renderOrder:-1,children:l.jsx("planeGeometry",{args:[6.5,6.5]})}),l.jsx("group",{ref:v,children:D.map((N,S)=>l.jsx("lineLoop",{geometry:y,material:N},S))}),l.jsxs("group",{ref:d,children:[l.jsx("mesh",{geometry:m,material:C}),l.jsx("lineSegments",{geometry:g,material:T})]})]})]})}function Pe(){const[e,o]=n.useState(()=>Math.min(window.devicePixelRatio||1,h.isMobile?1.5:2));return l.jsx("div",{className:"pointer-events-none fixed inset-0 z-0","aria-hidden":"true",children:l.jsxs(Z,{dpr:h.isMobile?[1,1.5]:e,camera:{position:[0,0,6],fov:40},gl:{antialias:!0,alpha:!0,powerPreference:"high-performance"},children:[l.jsx(ee,{onDecline:()=>o(1)}),l.jsx(ze,{})]})})}export{Pe as default};
