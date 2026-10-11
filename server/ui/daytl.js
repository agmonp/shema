/* Zoomable day timeline (2026-10-11) — used by the day page of שמע (ui/home.html), served as /home/daytl.js.
   - opens on the day's active hours only (first to last sound of speech, rounded to the hour), not a fixed 06–24
   - wheel / pinch zooms around the pointer, drag pans, double-click zooms in, +/−/"כל היום" buttons, arrow keys
   - a small overview strip above shows where the zoomed window sits in the day; drag it to move
   - row "שיחות": nearby conversations merge into one block while zoomed out (the number on it = how many); a click on
     a merged block zooms into it, a click on a single conversation opens it (o.onOpen) — colour = mood in the voice
   - one row per speaker (from D.segs = [start s, end s, name, media, conv_id]) so you see who talked when; TV/music on
     a hatched "רקע" row; sounds as emoji only where there is room (the rest are counted into the neighbouring emoji)
   - the zoom and the open conversation survive the page's periodic refresh (state is kept per day)
   Usage: DayTL.mount(el, D, {color: name => css, mood: valence => css, snd: {tag: emoji}, media: {name: emoji}, onOpen: id => …}) */
'use strict';
window.DayTL = (function () {
  const CSS = `
.dtl{direction:rtl;user-select:none;-webkit-user-select:none;--dtl-lab:74px}
.dtl-bar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.dtl-bar button{background:var(--surface2);border:1px solid var(--line2,var(--line));border-radius:14px;min-width:30px;height:28px;padding:0 10px;color:var(--ink);font:inherit;font-size:14px;cursor:pointer;line-height:1}
.dtl-bar button:hover{border-color:var(--accent)}
.dtl-bar button:disabled{opacity:.35;cursor:default;border-color:var(--line)}
.dtl-rng{font-weight:700;font-size:14px;direction:ltr;unicode-bidi:isolate}
.dtl-hint{color:var(--faint);font-size:12px;margin-inline-start:auto}
.dtl-ov{position:relative;height:14px;margin:0 0 6px;background:var(--surface2);border-radius:5px;direction:ltr;cursor:pointer;touch-action:none}
.dtl-ov i{position:absolute;top:3px;bottom:3px;border-radius:2px;opacity:.8}
.dtl-win{position:absolute;top:0;bottom:0;border:1.5px solid var(--ink);border-radius:5px;background:rgba(255,255,255,.06);cursor:grab}
.dtl-body{display:flex}
.dtl-labs{width:var(--dtl-lab);flex:none;font-size:12px}
.dtl-labs div{height:var(--h);display:flex;align-items:center;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-inline-end:6px}
.dtl-labs .sub{font-weight:400;color:var(--faint)}
.dtl-plot{position:relative;flex:1;min-width:0;direction:ltr;overflow:hidden;background:var(--surface2);border-radius:10px;touch-action:pan-y;cursor:grab;outline:none}
.dtl-plot:focus-visible{box-shadow:0 0 0 2px var(--accent)}
.dtl-plot.drag{cursor:grabbing}
.dtl-grid{position:absolute;inset:0;pointer-events:none}
.dtl-grid i{position:absolute;top:0;bottom:0;width:1px;background:var(--line)}
.dtl-grid i.h{background:var(--line2,var(--line))}
.dtl-now{position:absolute;top:0;bottom:0;width:2px;background:var(--rose);pointer-events:none}
.dtl-lane{position:relative;height:var(--h)}
.dtl-lane+.dtl-lane{border-top:1px solid var(--line)}
.dtl-lane b{position:absolute;top:4px;bottom:4px;border-radius:3px;min-width:2px}
.dtl-lane.cv b{top:4px;bottom:4px;border-radius:5px;min-width:4px;cursor:pointer;overflow:hidden;font:600 11px/1 inherit;color:#1b130b;display:flex;align-items:center;padding:0 5px;white-space:nowrap;direction:rtl}
.dtl-lane.cv b:hover{outline:2px solid var(--ink)}
.dtl-lane.cv b.sel{outline:2px solid var(--ink);box-shadow:0 0 0 4px rgba(255,255,255,.12)}
.dtl-lane.cv b.n{justify-content:center}
.dtl-lane.cv b.n span{background:rgba(0,0,0,.28);color:#fff;border-radius:8px;padding:1px 5px}
.dtl-lane.ps b{cursor:pointer;opacity:.85}
.dtl-lane.ps b:hover{opacity:1}
.dtl-lane.bg b{background:repeating-linear-gradient(135deg,rgba(143,179,224,.55) 0 3px,rgba(143,179,224,.18) 3px 6px)}
.dtl-lane.sd span{position:absolute;top:50%;transform:translate(-50%,-50%);font-size:13px;line-height:1}
.dtl-lane.sd span small{font-size:9px;color:var(--faint);margin-left:1px}
.dtl-axis{position:relative;height:16px;font-size:11px;color:var(--faint);direction:ltr;margin-inline-start:var(--dtl-lab)}
.dtl-axis span{position:absolute;top:2px;transform:translateX(-50%);white-space:nowrap}
.dtl-axis span.h{color:var(--dim);font-weight:700}
.dtl-tip{position:fixed;z-index:20;pointer-events:none;background:var(--surface3);border:1px solid var(--line2,var(--line));border-radius:10px;padding:6px 10px;font-size:13px;max-width:300px;box-shadow:0 6px 20px rgba(0,0,0,.45);direction:rtl}
.dtl-tip .t{color:var(--faint);font-size:12px;direction:ltr;unicode-bidi:isolate}
.dtl-leg{color:var(--faint);font-size:12px;margin-top:6px}
@media (max-width:640px){.dtl{--dtl-lab:58px}.dtl-hint{display:none}.dtl-labs{font-size:11px}}`;
  const STATE = {};
  const MIN_SPAN = 300;              // 5 minutes is the closest zoom
  const STEPS = [60, 300, 600, 900, 1800, 3600, 7200, 10800];
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const hm = s => { s = Math.max(0, Math.min(86399, Math.round(s))); return String(Math.floor(s / 3600)).padStart(2, '0') + ':' + String(Math.floor(s / 60) % 60).padStart(2, '0'); };
  const sod = iso => { const t = String(iso || ''); return +t.slice(11, 13) * 3600 + +t.slice(14, 16) * 60 + (parseFloat(t.slice(17)) || 0); };
  const J = (s, d) => { if (s == null || s === '') return d; if (typeof s !== 'string') return s; try { return JSON.parse(s) ?? d; } catch (e) { return d; } };
  const first = n => n && n !== '?' ? String(n).split(' ')[0] : 'לא מזוהה';
  const dur = s => s >= 3600 ? `${Math.floor(s / 3600)} ש׳ ${Math.round(s % 3600 / 60)} דק׳` : s >= 60 ? `${Math.round(s / 60)} דק׳` : `${Math.round(s)} שנ׳`;

  function css() {
    if (document.getElementById('dtl-css')) return;
    const s = document.createElement('style'); s.id = 'dtl-css'; s.textContent = CSS; document.head.appendChild(s);
  }

  function mount(el, D, o) {
    css();
    o = Object.assign({color: () => '#eaa45e', mood: () => '#eaa45e', snd: {}, media: {}, onOpen: () => {}}, o || {});
    const day = D.day;
    const endOf = c => c.end && String(c.end).slice(0, 10) > day ? 86400 : sod(c.end || c.start);
    const C = D.conversations.map(c => ({id: c.id, a: sod(c.start), b: Math.max(endOf(c), sod(c.start) + 15), c}));
    if (!C.length) { el.innerHTML = ''; return null; }
    const byId = Object.fromEntries(C.map(x => [x.id, x]));

    // speaker rows: from the utterances when the server sends them, else (older server) from each conversation's talk_seconds
    let segs = D.segs;
    if (!segs) {
      segs = [];
      C.forEach(x => Object.entries(J(x.c.talk_seconds, {})).forEach(([n, s]) => s > 0 && segs.push([x.a, x.b, n === '?' ? null : n, null, x.id])));
    }
    const lanes = {}, order = [];
    (D.talk || []).forEach(p => { const k = p.name === '?' || !p.name ? '?' : p.name; if (!lanes[k]) { lanes[k] = []; order.push(k); } });
    let bgSegs = [];
    segs.forEach(s => {
      if (s[3]) { bgSegs.push(s); return; }
      const k = s[2] || '?';
      if (!lanes[k]) { lanes[k] = []; order.push(k); }
      lanes[k].push(s);
    });
    const named = order.filter(k => k !== '?' && lanes[k].length).slice(0, 8);
    const rows = [...named, ...(lanes['?'] && lanes['?'].length ? ['?'] : [])];
    const sounds = (D.sounds || []).filter(s => o.snd[s.tag] && s.tag !== 'צליל לא מזוהה').map(s => ({t: sod(s.t0), tag: s.tag}));

    // the day's active hours
    const now = new Date(), today = now.toISOString().slice(0, 10) === day || `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` === day;
    const nowS = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
    const hours = (lo, hi) => {
      let a = Math.max(0, Math.floor((lo - 900) / 3600) * 3600), b = Math.min(86400, Math.ceil((hi + 900) / 3600) * 3600);
      if (b - a < 3 * 3600) { const m = (a + b) / 2; a = Math.max(0, m - 5400); b = Math.min(86400, a + 3 * 3600); }
      return [a, b];
    };
    const srt = [...C].sort((p, q) => p.a - q.a);
    let hi = Math.max(...C.map(x => x.b));
    if (today && nowS - hi < 7200) hi = Math.max(hi, Math.min(86400, nowS));   // show "now" only when the day is still going
    const [F0, F1] = hours(srt[0].a, hi);
    // the opening view leaves out a short lone conversation far from the rest (e.g. 5 minutes at 00:07 when the day
    // starts at 07:00); it is still in the overview strip and in "כל היום"
    let i0 = 0, i1 = srt.length - 1;
    const lone = (i, j) => srt.slice(i, j + 1).reduce((s, x) => s + x.b - x.a, 0) < 900;
    while (i0 < i1 && srt[i0 + 1].a - srt[i0].b > 3 * 3600 && lone(0, i0)) i0++;
    while (i1 > i0 && srt[i1].a - srt[i1 - 1].b > 3 * 3600 && lone(i1, srt.length - 1)) i1--;
    const [O0, O1] = hours(srt[i0].a, i1 === srt.length - 1 ? hi : srt[i1].b);
    const st = STATE[day] = STATE[day] || {v0: O0, v1: O1, sel: null, touched: false};
    if (!st.touched) { st.v0 = O0; st.v1 = O1; }       // follow a growing day until the user zooms
    clamp();

    const H = {cv: 30, ps: 20, bg: 16, sd: 20};
    el.innerHTML = `<div class="dtl">
      <div class="dtl-bar"><button data-z="in" title="זום פנימה (+)">＋</button><button data-z="out" title="זום החוצה (−)">－</button>
        <button data-z="all" title="כל שעות הפעילות">כל היום</button><span class="dtl-rng"></span>
        <span class="dtl-hint">גלגלת או צביטה = זום · גרירה = הזזה · לחיצה על שיחה פותחת אותה</span></div>
      <div class="dtl-body"><div style="width:var(--dtl-lab)"></div><div class="dtl-ov" style="flex:1"></div></div>
      <div class="dtl-body"><div class="dtl-labs">
          <div style="--h:${H.cv}px">שיחות</div>
          ${rows.map(k => `<div style="--h:${H.ps}px;color:${k === '?' ? 'var(--faint)' : o.color(k)}" title="${esc(k === '?' ? 'דיבור שלא זוהה מי אמר' : k)}">${esc(first(k))}</div>`).join('')}
          ${bgSegs.length ? `<div class="sub" style="--h:${H.bg}px">📺 רקע</div>` : ''}
          ${sounds.length ? `<div class="sub" style="--h:${H.sd}px">צלילים</div>` : ''}</div>
        <div class="dtl-plot" tabindex="0" aria-label="ציר הזמן של היום"><div class="dtl-grid"></div><div class="dtl-lanes"></div></div></div>
      <div class="dtl-axis"></div>
      <div class="dtl-leg">שורת השיחות: צבע = מצב הרוח בקול — <span style="color:var(--sage)">רגוע/חיובי</span> · <span style="color:var(--accent)">ביניים</span> · <span style="color:var(--rose)">מתוח</span>; מספר על בלוק = כמה שיחות צמודות (לחיצה מתקרבת אליהן). שורות האנשים: מתי כל אחד דיבר.</div></div>`;
    const plot = el.querySelector('.dtl-plot'), lanesEl = el.querySelector('.dtl-lanes'), grid = el.querySelector('.dtl-grid'),
      axis = el.querySelector('.dtl-axis'), ov = el.querySelector('.dtl-ov'), rng = el.querySelector('.dtl-rng'),
      bIn = el.querySelector('[data-z=in]'), bOut = el.querySelector('[data-z=out]'), bAll = el.querySelector('[data-z=all]');
    let tip = document.querySelector('.dtl-tip');
    if (!tip) { tip = document.createElement('div'); tip.className = 'dtl-tip'; tip.hidden = true; document.body.appendChild(tip); }
    let CL = [];                       // the conversation blocks as drawn (merged by pixel distance)

    function clamp() {
      let span = Math.max(MIN_SPAN, Math.min(F1 - F0, st.v1 - st.v0));
      if (st.v0 < F0) st.v0 = F0;
      st.v1 = st.v0 + span;
      if (st.v1 > F1) { st.v1 = F1; st.v0 = F1 - span; }
    }
    function merge(list, W, gapPx, X) {            // list sorted by start; joins items closer than gapPx on screen
      const out = [];
      for (const s of list) {
        if (s.b < st.v0 || s.a > st.v1) continue;
        const L = out[out.length - 1];
        if (L && X(s.a) - X(L.b) < gapPx) { L.b = Math.max(L.b, s.b); L.items.push(s.x); }
        else out.push({a: s.a, b: s.b, items: [s.x]});
      }
      return out;
    }
    function draw() {
      if (!el.isConnected) return;
      const W = plot.clientWidth || 600, span = st.v1 - st.v0;
      const X = s => (s - st.v0) / span * W;
      const step = STEPS.find(k => W / (span / k) >= 64) || 10800;
      let g = '', ax = '';
      for (let t = Math.ceil(st.v0 / step) * step; t <= st.v1; t += step) {
        const h = t % 3600 === 0;
        g += `<i class="${h ? 'h' : ''}" style="left:${X(t).toFixed(1)}px"></i>`;
        const x = X(t); if (x > 14 && x < W - 14) ax += `<span class="${h ? 'h' : ''}" style="left:${x.toFixed(1)}px">${hm(t)}</span>`;
      }
      if (today && nowS > st.v0 && nowS < st.v1) g += `<span class="dtl-now" style="left:${X(nowS).toFixed(1)}px" title="עכשיו"></span>`;
      grid.innerHTML = g;
      axis.innerHTML = ax;
      axis.style.width = W + 'px';
      // conversations
      CL = merge(C.map(x => ({a: x.a, b: x.b, x})), W, 5, X);
      let h = `<div class="dtl-lane cv" style="--h:${H.cv}px">` + CL.map((k, i) => {
        const x0 = X(k.a), w = Math.max(4, X(k.b) - x0), one = k.items.length === 1;
        const tot = k.items.reduce((a, x) => a + (x.b - x.a), 0) || 1;
        const val = k.items.some(x => x.c.mood_valence != null) ? k.items.reduce((a, x) => a + (x.c.mood_valence ?? .5) * (x.b - x.a), 0) / tot : null;
        const lab = one ? (w > 70 ? `${hm(k.a)} ${esc(k.items[0].c.topic || '')}` : '') : (w > 18 ? `<span>${k.items.length}</span>` : '');
        const sel = k.items.some(x => x.id === st.sel);
        return `<b class="${one ? '' : 'n'}${sel ? ' sel' : ''}" data-cl="${i}" style="left:${x0.toFixed(1)}px;width:${w.toFixed(1)}px;background:${o.mood(val)}">${lab}</b>`;
      }).join('') + '</div>';
      // speakers
      for (const k of rows) {
        const col = k === '?' ? 'var(--faint)' : o.color(k);
        h += `<div class="dtl-lane ps" style="--h:${H.ps}px">` + merge(lanes[k].map(s => ({a: s[0], b: Math.max(s[1], s[0] + 1), x: s})), W, 2, X)
          .map(m => `<b data-cv="${m.items[0][4] ?? ''}" data-who="${esc(k)}" data-a="${m.a}" data-b="${m.b}" style="left:${X(m.a).toFixed(1)}px;width:${Math.max(2, X(m.b) - X(m.a)).toFixed(1)}px;background:${col}"></b>`).join('') + '</div>';
      }
      if (bgSegs.length) h += `<div class="dtl-lane bg" style="--h:${H.bg}px">` + merge(bgSegs.map(s => ({a: s[0], b: Math.max(s[1], s[0] + 1), x: s})), W, 3, X)
        .map(m => `<b data-cv="${m.items[0][4] ?? ''}" data-who="${esc([...new Set(m.items.map(s => s[3]))].join(', '))}" data-a="${m.a}" data-b="${m.b}" style="left:${X(m.a).toFixed(1)}px;width:${Math.max(2, X(m.b) - X(m.a)).toFixed(1)}px"></b>`).join('') + '</div>';
      if (sounds.length) {
        const shown = [];
        for (const s of sounds) {
          if (s.t < st.v0 || s.t > st.v1) continue;
          const x = X(s.t), L = shown[shown.length - 1];
          if (L && x - L.x < 20) { L.more.push(s); continue; }      // no room: counted into the neighbour's tooltip
          if (x < 8 || x > W - 8) continue;
          shown.push({x, s, more: []});
        }
        h += `<div class="dtl-lane sd" style="--h:${H.sd}px">` + shown.map(z => {
          const tags = [z.s, ...z.more].map(s => `${s.tag} ${hm(s.t)}`);
          return `<span style="left:${z.x.toFixed(1)}px" data-snd="${esc(tags.slice(0, 8).join(' · ') + (tags.length > 8 ? ` · ועוד ${tags.length - 8}` : ''))}">${o.snd[z.s.tag]}</span>`;
        }).join('') + '</div>';
      }
      lanesEl.innerHTML = h;
      // overview + range label + buttons
      const fs = F1 - F0;
      ov.innerHTML = C.map(x => `<i style="left:${((x.a - F0) / fs * 100).toFixed(2)}%;width:${Math.max(.25, (x.b - x.a) / fs * 100).toFixed(2)}%;background:${o.mood(x.c.mood_valence)}"></i>`).join('') +
        `<div class="dtl-win" style="left:${((st.v0 - F0) / fs * 100).toFixed(2)}%;width:${((st.v1 - st.v0) / fs * 100).toFixed(2)}%"></div>`;
      ov.style.visibility = span < fs - 1 ? 'visible' : 'hidden';
      rng.textContent = `${hm(st.v0)}–${hm(st.v1)}`;
      bIn.disabled = span <= MIN_SPAN + 1; bOut.disabled = bAll.disabled = span >= fs - 1;
    }

    let raf = 0;
    const redraw = () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); };
    function zoomAt(anchor, f) {
      const span = st.v1 - st.v0, ns = Math.max(MIN_SPAN, Math.min(F1 - F0, span * f));
      st.v0 = anchor - (anchor - st.v0) * ns / span; st.v1 = st.v0 + ns; st.touched = true; clamp(); redraw();
    }
    let anim = 0;
    function animateTo(a, b) {
      if (b - a < MIN_SPAN) { const m = (a + b) / 2; a = m - MIN_SPAN / 2; b = m + MIN_SPAN / 2; }
      const s0 = st.v0, s1 = st.v1, t0 = performance.now(); st.touched = true;
      cancelAnimationFrame(anim);
      const tick = t => {
        const k = Math.min(1, (t - t0) / 260), e = 1 - Math.pow(1 - k, 3);
        st.v0 = s0 + (a - s0) * e; st.v1 = s1 + (b - s1) * e; clamp(); draw();
        if (k < 1) anim = requestAnimationFrame(tick);
      };
      anim = requestAnimationFrame(tick);
    }
    const tAt = clientX => { const r = plot.getBoundingClientRect(); return st.v0 + (clientX - r.left) / r.width * (st.v1 - st.v0); };
    function open(id) {
      st.sel = id; draw();
      o.onOpen(id);
    }
    function clickOn(t) {
      const cl = t.closest('[data-cl]');
      if (cl) {
        const k = CL[+cl.dataset.cl];
        if (k.items.length > 1 && st.v1 - st.v0 > MIN_SPAN + 1) { const pad = Math.max(60, (k.b - k.a) * .08); animateTo(k.a - pad, k.b + pad); }
        else open(k.items.reduce((a, x) => (x.b - x.a) > (a.b - a.a) ? x : a).id);
        return;
      }
      const sg = t.closest('[data-cv]');
      if (sg && sg.dataset.cv && byId[sg.dataset.cv]) open(+sg.dataset.cv);
    }

    bIn.onclick = () => zoomAt((st.v0 + st.v1) / 2, .5);
    bOut.onclick = () => zoomAt((st.v0 + st.v1) / 2, 2);
    bAll.onclick = () => animateTo(F0, F1);

    // pointer: one finger / mouse = pan (or click when it barely moved), two fingers = pinch zoom
    const P = new Map(); let gest = null;
    plot.addEventListener('pointerdown', e => {
      if (e.button) return;
      P.set(e.pointerId, {x: e.clientX, y: e.clientY});
      try { plot.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      if (P.size === 1) gest = {k: 'pan', x: e.clientX, y: e.clientY, v0: st.v0, v1: st.v1, moved: false, target: e.target};
      else if (P.size === 2) {
        const [p, q] = [...P.values()];
        gest = {k: 'pinch', d: Math.hypot(p.x - q.x, p.y - q.y) || 1, mid: tAt((p.x + q.x) / 2), v0: st.v0, v1: st.v1, moved: true};
      }
      tip.hidden = true;
    });
    plot.addEventListener('pointermove', e => {
      if (P.has(e.pointerId)) P.set(e.pointerId, {x: e.clientX, y: e.clientY});
      if (gest && gest.k === 'pan' && P.size === 1) {
        const dx = e.clientX - gest.x;
        if (!gest.moved && Math.abs(dx) < 5) return;
        if (!gest.moved && e.pointerType === 'touch' && Math.abs(e.clientY - gest.y) > Math.abs(dx)) { gest = null; return; }  // vertical = page scroll
        gest.moved = true; plot.classList.add('drag');
        const ds = dx / plot.clientWidth * (gest.v1 - gest.v0);
        st.v0 = gest.v0 - ds; st.v1 = gest.v1 - ds; st.touched = true; clamp(); redraw();
      } else if (gest && gest.k === 'pinch' && P.size === 2) {
        const [p, q] = [...P.values()], d = Math.hypot(p.x - q.x, p.y - q.y) || 1;
        const span0 = gest.v1 - gest.v0, ns = Math.max(MIN_SPAN, Math.min(F1 - F0, span0 * gest.d / d));
        const r = plot.getBoundingClientRect(), fx = ((p.x + q.x) / 2 - r.left) / r.width;
        st.v0 = gest.mid - fx * ns; st.v1 = st.v0 + ns; st.touched = true; clamp(); redraw();
      } else if (!P.size && e.pointerType === 'mouse') hover(e);
    });
    const up = e => {
      P.delete(e.pointerId);
      plot.classList.remove('drag');
      if (gest && gest.k === 'pan' && !gest.moved && !P.size) clickOn(gest.target);
      if (!P.size) gest = null;
      else if (P.size === 1 && gest && gest.k === 'pinch') { const [p] = [...P.values()]; gest = {k: 'pan', x: p.x, y: p.y, v0: st.v0, v1: st.v1, moved: true}; }
    };
    plot.addEventListener('pointerup', up);
    plot.addEventListener('pointercancel', e => { P.delete(e.pointerId); gest = null; plot.classList.remove('drag'); });
    plot.addEventListener('pointerleave', () => { tip.hidden = true; });
    plot.addEventListener('wheel', e => {
      e.preventDefault(); tip.hidden = true;
      if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || e.shiftKey) {
        const ds = (e.deltaX || e.deltaY) / plot.clientWidth * (st.v1 - st.v0);
        st.v0 += ds; st.v1 += ds; st.touched = true; clamp(); redraw();
      } else zoomAt(tAt(e.clientX), Math.exp(e.deltaY * (e.deltaMode ? 0.05 : 0.0015)));
    }, {passive: false});
    plot.addEventListener('dblclick', e => { e.preventDefault(); zoomAt(tAt(e.clientX), .4); });
    plot.addEventListener('keydown', e => {
      const span = st.v1 - st.v0, mid = (st.v0 + st.v1) / 2;
      if (e.key === '+' || e.key === '=') zoomAt(mid, .5);
      else if (e.key === '-' || e.key === '_') zoomAt(mid, 2);
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { const ds = (e.key === 'ArrowRight' ? 1 : -1) * span * .2; st.v0 += ds; st.v1 += ds; st.touched = true; clamp(); redraw(); }
      else if (e.key === '0' || e.key === 'Home') bAll.onclick();
      else return;
      e.preventDefault();
    });
    // overview strip: click centres the window there, drag moves it
    let ovDrag = null;
    const ovT = cx => { const r = ov.getBoundingClientRect(); return F0 + (cx - r.left) / r.width * (F1 - F0); };
    ov.addEventListener('pointerdown', e => {
      ov.setPointerCapture(e.pointerId);
      const t = ovT(e.clientX), span = st.v1 - st.v0;
      if (t < st.v0 || t > st.v1) { st.v0 = t - span / 2; st.v1 = t + span / 2; st.touched = true; clamp(); draw(); }
      ovDrag = {x: e.clientX, v0: st.v0, v1: st.v1};
    });
    ov.addEventListener('pointermove', e => {
      if (!ovDrag) return;
      const ds = (e.clientX - ovDrag.x) / ov.clientWidth * (F1 - F0);
      st.v0 = ovDrag.v0 + ds; st.v1 = ovDrag.v1 + ds; st.touched = true; clamp(); redraw();
    });
    ov.addEventListener('pointerup', () => { ovDrag = null; });

    function hover(e) {
      const t = e.target, cl = t.closest('[data-cl]'), sg = t.closest('[data-who]'), sn = t.closest('[data-snd]');
      let html = '';
      if (cl) {
        const k = CL[+cl.dataset.cl];
        if (k.items.length === 1) {
          const c = k.items[0].c, ppl = J(c.people, []).map(first).join(', ');
          html = `<div class="t">${hm(k.a)}–${hm(k.b)} · ${dur(k.b - k.a)}</div><b>${esc(c.topic || 'שיחה')}</b>${ppl ? `<div>${esc(ppl)}</div>` : ''}<div class="t" style="direction:rtl">לחיצה פותחת את השיחה והניתוח</div>`;
        } else html = `<div class="t">${hm(k.a)}–${hm(k.b)}</div><b>${k.items.length} שיחות</b>${k.items.slice(0, 5).map(x => `<div>${hm(x.a)} ${esc(x.c.topic || 'שיחה')}</div>`).join('')}${k.items.length > 5 ? `<div class="t">ועוד ${k.items.length - 5}</div>` : ''}<div class="t" style="direction:rtl">לחיצה מתקרבת</div>`;
      } else if (sg) {
        const a = +sg.dataset.a, b = +sg.dataset.b, cv = byId[sg.dataset.cv];
        html = `<b>${esc(first(sg.dataset.who === '?' ? null : sg.dataset.who))}</b> <span class="t">${hm(a)}–${hm(b)}</span>${cv ? `<div>${esc(cv.c.topic || 'שיחה')}</div>` : ''}`;
      } else if (sn) html = esc(sn.dataset.snd);
      if (!html) { tip.hidden = true; return; }
      tip.innerHTML = html; tip.hidden = false;
      const w = tip.offsetWidth, x = Math.min(window.innerWidth - w - 8, Math.max(8, e.clientX - w / 2));
      tip.style.left = x + 'px'; tip.style.top = (e.clientY + 16) + 'px';
    }

    if (window.ResizeObserver) { const ro = new ResizeObserver(() => { if (!el.isConnected) return ro.disconnect(); redraw(); }); ro.observe(plot); }
    draw();
    return {
      select(id) { st.sel = id; draw(); },
      get selected() { return st.sel; },
      get touched() { return st.touched; },
    };
  }
  return {mount, state: day => STATE[day]};
})();
