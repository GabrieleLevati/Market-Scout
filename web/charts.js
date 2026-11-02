/* Grafici in SVG puro: nessuna libreria, nessuna CDN.
   L'FDD prevede Plotly (1.5); qui i grafici sono generati a mano per tenere la
   demo apribile da file:// senza dipendenze. Specifiche visive: marche sottili,
   estremita' dati arrotondata 4px, linee 2px, marker >=8px con anello del colore
   di superficie, griglia hairline recessiva, etichette dirette selettive,
   tooltip sempre presente. */

/* Script classico (non modulo ES): i moduli sono bloccati dal CORS su file://. */
const Charts = (function () {
'use strict';

const NS = 'http://www.w3.org/2000/svg';
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const fmt = {
  num: (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '-'
    : v.toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d }),
  int: (v) => (v === null || v === undefined) ? '-' : Math.round(v).toLocaleString('it-IT'),
  pct: (v, d = 1) => (v === null || v === undefined) ? '-'
    : (v * 100).toLocaleString('it-IT', { minimumFractionDigits: d, maximumFractionDigits: d }) + '%',
  signed: (v, d = 1) => (v > 0 ? '+' : '') + fmt.pct(v, d),
  compact: (v) => {
    const a = Math.abs(v);
    if (a >= 1e9) return fmt.num(v / 1e9, 1) + ' Mld';
    if (a >= 1e6) return fmt.num(v / 1e6, 1) + ' Mln';
    if (a >= 1e4) return fmt.int(v / 1e3) + 'K';
    return fmt.int(v);
  },
  date: (iso) => iso.slice(8, 10) + '/' + iso.slice(5, 7) + '/' + iso.slice(2, 4),
  // L'ora di un istante UTC, scritta nel fuso di chi guarda. Il motore
  // dichiara gli orari in UTC perche' e' l'unico modo di confrontarli fra
  // borse diverse; chi legge li vuole nella sua ora.
  ora: (iso) => {
    const t = new Date(iso);
    if (isNaN(t)) return '';
    return String(t.getHours()).padStart(2, '0') + ':'
         + String(t.getMinutes()).padStart(2, '0');
  },
  // Vero se quell'istante cade nel giorno di chi guarda.
  oggi: (iso) => {
    const t = new Date(iso);
    if (isNaN(t)) return false;
    const o = new Date();
    return t.getFullYear() === o.getFullYear() && t.getMonth() === o.getMonth()
        && t.getDate() === o.getDate();
  },
};

function el(tag, attrs = {}, parent = null) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function frame(host, width, height) {
  host.innerHTML = '';
  host.classList.add('chart');
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img' });
  host.appendChild(svg);
  const tip = document.createElement('div');
  tip.className = 'tooltip';
  host.appendChild(tip);
  return { svg, tip };
}

function showTip(host, tip, x, y, html) {
  tip.innerHTML = html;
  tip.style.opacity = 1;
  const w = host.clientWidth;
  const tw = tip.offsetWidth;
  tip.style.left = Math.max(2, Math.min(w - tw - 2, x - tw / 2)) + 'px';
  tip.style.top = Math.max(0, y) + 'px';
}

function niceTicks(min, max, count = 4) {
  if (min === max) return [min];
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(s => s * mag).find(s => s >= raw) || mag * 10;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

/* ---------------------------------------------------------------- linee */
function lineChart(host, { dates, series, markers = [], height = 260, yFormat = fmt.num, legend = true }) {
  const W = 760, H = height, M = { t: 14, r: 62, b: 24, l: 52 };
  if (legend && series.length > 1) {
    const lg = document.createElement('div');
    lg.className = 'legend';
    lg.innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join('');
    host.parentNode.insertBefore(lg, host);
  }
  const { svg, tip } = frame(host, W, H);
  const all = series.flatMap(s => s.values).concat(markers.map(m => m.value)).filter(v => v != null);
  let min = Math.min(...all), max = Math.max(...all);
  const pad = (max - min) * 0.08 || Math.abs(max) * 0.05 || 1;
  min -= pad; max += pad;
  const n = dates.length;
  const X = i => M.l + (W - M.l - M.r) * (n === 1 ? 0.5 : i / (n - 1));
  const Y = v => M.t + (H - M.t - M.b) * (1 - (v - min) / (max - min));

  for (const t of niceTicks(min, max)) {
    el('line', { x1: M.l, x2: W - M.r, y1: Y(t), y2: Y(t), stroke: css('--grid'), 'stroke-width': 1 }, svg);
    const lb = el('text', { x: M.l - 8, y: Y(t) + 4, 'text-anchor': 'end', fill: css('--muted'), 'font-size': 11 }, svg);
    lb.textContent = yFormat(t);
  }
  const step = Math.max(1, Math.floor(n / 6));
  for (let i = 0; i < n; i += step) {
    const lb = el('text', { x: X(i), y: H - 6, 'text-anchor': 'middle', fill: css('--muted'), 'font-size': 11 }, svg);
    lb.textContent = fmt.date(dates[i]);
  }

  for (const m of markers) {
    el('line', {
      x1: M.l, x2: W - M.r, y1: Y(m.value), y2: Y(m.value), stroke: m.color,
      'stroke-width': 1, 'stroke-dasharray': '1 0', opacity: .55,
    }, svg);
    const lb = el('text', { x: W - M.r + 6, y: Y(m.value) + 4, fill: css('--text-2'), 'font-size': 11 }, svg);
    lb.textContent = m.label;
  }

  series.forEach(s => {
    const pts = s.values.map((v, i) => `${X(i)},${Y(v)}`).join(' ');
    if (s.fill) {
      el('polygon', {
        points: `${X(0)},${Y(min)} ${pts} ${X(n - 1)},${Y(min)}`,
        fill: s.color, opacity: .10,
      }, svg);
    }
    el('polyline', {
      points: pts, fill: 'none', stroke: s.color, 'stroke-width': s.width || 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round', opacity: s.dim ? .75 : 1,
    }, svg);
    const last = s.values[s.values.length - 1];
    el('circle', { cx: X(n - 1), cy: Y(last), r: 4.5, fill: s.color, stroke: css('--surface-1'), 'stroke-width': 2 }, svg);
  });
  // etichetta diretta solo sull'ultima serie di prezzo (selettiva)
  const main = series[0];
  const lbl = el('text', {
    x: W - M.r + 6, y: Y(main.values[n - 1]) - 8, fill: css('--text-1'),
    'font-size': 11.5, 'font-weight': 650,
  }, svg);
  lbl.textContent = yFormat(main.values[n - 1]);

  const cross = el('line', { y1: M.t, y2: H - M.b, stroke: css('--axis'), 'stroke-width': 1, opacity: 0 }, svg);
  const dots = series.map(s => el('circle', { r: 4, fill: s.color, stroke: css('--surface-1'), 'stroke-width': 2, opacity: 0 }, svg));
  const hit = el('rect', { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: 'transparent' }, svg);
  hit.addEventListener('mousemove', (ev) => {
    const r = host.getBoundingClientRect();
    const scale = W / r.width;
    const px = (ev.clientX - r.left) * scale;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - M.l) / ((W - M.l - M.r) / (n - 1)))));
    cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('opacity', .8);
    series.forEach((s, k) => {
      dots[k].setAttribute('cx', X(i)); dots[k].setAttribute('cy', Y(s.values[i])); dots[k].setAttribute('opacity', 1);
    });
    showTip(host, tip, X(i) / scale, 6,
      `<div class="tt-title">${fmt.date(dates[i])}</div>` +
      series.map(s => `<div class="tt-row"><span>${s.name}</span><span>${yFormat(s.values[i])}</span></div>`).join(''));
  });
  hit.addEventListener('mouseleave', () => {
    cross.setAttribute('opacity', 0);
    dots.forEach(d => d.setAttribute('opacity', 0));
    tip.style.opacity = 0;
  });
}

/* --------------------------------------------------- barre orizzontali */
function barH(host, { items, max = null, color = null, height = null, format = (v) => fmt.num(v, 1), label = 'valore' }) {
  const rowH = 30, W = 760;
  const H = height || items.length * rowH + 10;
  const labelW = 190, valueW = 74;
  const { svg, tip } = frame(host, W, H);
  const hi = max != null ? max : Math.max(...items.map(i => i.value), 0.0001);
  const barMax = W - labelW - valueW;
  items.forEach((it, i) => {
    const y = i * rowH + 5;
    const h = Math.min(20, rowH - 10);
    const w = Math.max(1, barMax * (it.value / hi));
    const c = it.color || color || css('--seq-450');
    const t = el('text', { x: 0, y: y + h / 2 + 4, fill: css('--text-2'), 'font-size': 12 }, svg);
    t.textContent = it.label;
    // estremita' dati arrotondata 4px, base quadrata sulla linea di partenza
    el('path', {
      d: `M${labelW},${y} H${labelW + Math.max(0, w - 4)} a4,4 0 0 1 4,4 v${h - 8} a4,4 0 0 1 -4,4 H${labelW} Z`,
      fill: c,
    }, svg);
    const v = el('text', { x: labelW + w + 8, y: y + h / 2 + 4, fill: css('--text-1'), 'font-size': 11.5, 'font-weight': 600 }, svg);
    v.textContent = it.display || format(it.value);
    const hit = el('rect', { x: 0, y, width: W, height: rowH - 4, fill: 'transparent' }, svg);
    hit.addEventListener('mousemove', () => showTip(host, tip, labelW + w / 2, y - 4,
      `<div class="tt-title">${it.label}</div>` +
      `<div class="tt-row"><span>${label}</span><span>${it.display || format(it.value)}</span></div>` +
      (it.note ? `<div class="tt-row"><span>${it.note}</span><span></span></div>` : '')));
    hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; });
  });
}

/* ------------------------------------------------------------- colonne */
function columns(host, { items, height = 200, format = fmt.int, color = null, width = 760 }) {
  const W = width, H = height, M = { t: 18, r: 8, b: 42, l: 44 };
  const { svg, tip } = frame(host, W, H);
  const hi = Math.max(...items.map(i => i.value), 1);
  const band = (W - M.l - M.r) / items.length;
  const bw = Math.min(24, band - 14);
  for (const t of niceTicks(0, hi, 3)) {
    const y = M.t + (H - M.t - M.b) * (1 - t / hi);
    el('line', { x1: M.l, x2: W - M.r, y1: y, y2: y, stroke: css('--grid'), 'stroke-width': 1 }, svg);
    const lb = el('text', { x: M.l - 8, y: y + 4, 'text-anchor': 'end', fill: css('--muted'), 'font-size': 11 }, svg);
    lb.textContent = format(t);
  }
  items.forEach((it, i) => {
    const x = M.l + band * i + (band - bw) / 2;
    const h = (H - M.t - M.b) * (it.value / hi);
    const y = H - M.b - h;
    const c = it.color || color || css('--seq-450');
    if (h > 0) {
      el('path', {
        d: `M${x},${H - M.b} V${y + 4} a4,4 0 0 1 4,-4 h${bw - 8} a4,4 0 0 1 4,4 V${H - M.b} Z`,
        fill: c,
      }, svg);
    }
    const v = el('text', { x: x + bw / 2, y: y - 6, 'text-anchor': 'middle', fill: css('--text-1'), 'font-size': 11.5, 'font-weight': 600 }, svg);
    v.textContent = it.display || format(it.value);
    (it.label || '').split('\n').forEach((line, k) => {
      const lb = el('text', { x: x + bw / 2, y: H - M.b + 16 + k * 13, 'text-anchor': 'middle', fill: css('--text-2'), 'font-size': 11 }, svg);
      lb.textContent = line;
    });
    const hit = el('rect', { x: M.l + band * i, y: M.t, width: band, height: H - M.t - M.b, fill: 'transparent' }, svg);
    hit.addEventListener('mousemove', () => showTip(host, tip, x + bw / 2, Math.max(0, y - 40),
      `<div class="tt-title">${(it.label || '').replace('\n', ' ')}</div>` +
      `<div class="tt-row"><span>${it.note || 'valore'}</span><span>${it.display || format(it.value)}</span></div>`));
    hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; });
  });
}

/* ------------------------------------------------ barre divergenti P/L */
function diverging(host, { items, format = fmt.signed }) {
  const rowH = 30, W = 760, labelW = 120;
  const H = items.length * rowH + 10;
  const { svg, tip } = frame(host, W, H);
  // la linea dello zero sta dove serve: al centro solo se ci sono entrambi i segni
  const avail = W - labelW - 90;
  const negMax = Math.max(0, -Math.min(...items.map(i => i.value)));
  const posMax = Math.max(0, Math.max(...items.map(i => i.value)));
  const span = (negMax + posMax) || 1;
  const negW = avail * (negMax / span), posW = avail * (posMax / span);
  const zero = labelW + negW;
  el('line', { x1: zero, x2: zero, y1: 2, y2: H - 6, stroke: css('--axis'), 'stroke-width': 1 }, svg);
  items.forEach((it, i) => {
    const y = i * rowH + 5, h = 20;
    const pos = it.value >= 0;
    const w = Math.max(1, pos ? posW * (it.value / (posMax || 1))
      : negW * (-it.value / (negMax || 1)));
    const c = pos ? css('--series-1') : css('--critical');
    const x = pos ? zero : zero - w;
    const t = el('text', { x: 0, y: y + h / 2 + 4, fill: css('--text-2'), 'font-size': 12 }, svg);
    t.textContent = it.label;
    const d = pos
      ? `M${x},${y} H${x + Math.max(0, w - 4)} a4,4 0 0 1 4,4 v${h - 8} a4,4 0 0 1 -4,4 H${x} Z`
      : `M${zero},${y} H${x + 4} a4,4 0 0 0 -4,4 v${h - 8} a4,4 0 0 0 4,4 H${zero} Z`;
    el('path', { d, fill: c }, svg);
    const v = el('text', {
      x: pos ? x + w + 8 : x - 8, y: y + h / 2 + 4, 'text-anchor': pos ? 'start' : 'end',
      fill: css('--text-1'), 'font-size': 11.5, 'font-weight': 600,
    }, svg);
    v.textContent = it.display || format(it.value);
    const hit = el('rect', { x: 0, y, width: W, height: rowH - 4, fill: 'transparent' }, svg);
    hit.addEventListener('mousemove', () => showTip(host, tip, zero, y - 4,
      `<div class="tt-title">${it.label}</div>` +
      `<div class="tt-row"><span>${it.note || 'P/L'}</span><span>${it.display || format(it.value)}</span></div>`));
    hit.addEventListener('mouseleave', () => { tip.style.opacity = 0; });
  });
}

/* --------------------------------------------------------------- meter */
function meter(host, { value, max, caption, warnAt = null }) {
  host.innerHTML = '';
  host.classList.add('chart');
  const over = value > max;
  const wrap = document.createElement('div');
  const pct = Math.min(100, (value / Math.max(max, value)) * 100);
  const fill = over ? css('--critical') : (warnAt && value > warnAt ? css('--warning') : css('--seq-450'));
  wrap.innerHTML =
    `<div style="height:10px;border-radius:999px;background:var(--seq-200);overflow:hidden">
       <div style="width:${pct}%;height:100%;background:${fill}"></div>
     </div>
     <div class="note" style="margin-top:6px">${caption}</div>`;
  host.appendChild(wrap);
}

/* ----------------------------------------------------------- sparkline */
function sparkline(values, { width = 110, height = 26, color = null } = {}) {
  const min = Math.min(...values), max = Math.max(...values);
  const X = i => (width - 2) * (i / (values.length - 1)) + 1;
  const Y = v => height - 2 - (height - 4) * (max === min ? .5 : (v - min) / (max - min));
  const pts = values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
  const c = color || css('--seq-450');
  return `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" style="display:block">
      <polyline points="${pts}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${X(values.length - 1).toFixed(1)}" cy="${Y(values[values.length - 1]).toFixed(1)}" r="3"
              fill="${c}" stroke="${css('--surface-1')}" stroke-width="2"/>
    </svg>`;
}

/* ---------------------------------------------------------------------------
   sparkArea: l'andamento dentro una scheda della vista cliente.

   Una serie sola, quindi nessuna legenda: il titolo della scheda dice di che
   strumento si tratta. Niente assi e niente griglia, perche' qui la domanda
   non e' "quanto" ma "da che parte sta andando"; il valore di oggi e' scritto
   in chiaro accanto al punto, ed e' l'unica etichetta diretta. La linea si
   disegna da sinistra: e' il verso del tempo.
   --------------------------------------------------------------------------- */
function sparkArea(host, { values, dates = null, color = null, height = 60 } = {}) {
  host.innerHTML = '';
  if (!values || values.length < 2) return;
  const W = 300, H = height;          // viewBox fisso, lo SVG si stira in larghezza
  const pad = 6;
  const min = Math.min(...values), max = Math.max(...values);
  const span = (max === min) ? 1 : (max - min);
  const X = (i) => pad + (W - pad * 2) * (i / (values.length - 1));
  const Y = (v) => H - pad - (H - pad * 2) * ((v - min) / span);
  const c = color || css('--series-1');

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none',
                          role: 'img' }, host);
  const linea = values.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' L');
  CONTA_SPARK += 1;
  const grad = 'gsp' + CONTA_SPARK;     // id unico: due grafici uguali lo condividerebbero
  const defs = el('defs', {}, svg);
  const lg = el('linearGradient', { id: grad, x1: '0', y1: '0', x2: '0', y2: '1' }, defs);
  el('stop', { offset: '0', 'stop-color': c, 'stop-opacity': '.30' }, lg);
  el('stop', { offset: '1', 'stop-color': c, 'stop-opacity': '0' }, lg);

  // fill e stroke espliciti sul nodo: un componente grafico non deve dipendere
  // dalla classe del contenitore per non disegnarsi nero (il riempimento di
  // default di un path e' nero, e una linea riempita e' una macchia)
  el('path', { class: 'ar', d: `M${linea} L${X(values.length - 1).toFixed(1)},${H} L${X(0).toFixed(1)},${H} Z`,
               fill: `url(#${grad})`, stroke: 'none' }, svg);
  const ln = el('path', { class: 'ln', d: `M${linea}`, stroke: c, fill: 'none',
                          'stroke-width': 2, 'stroke-linecap': 'round',
                          'stroke-linejoin': 'round',
                          'vector-effect': 'non-scaling-stroke' }, svg);
  el('circle', { class: 'pt', cx: X(values.length - 1).toFixed(1),
                 cy: Y(values[values.length - 1]).toFixed(1), r: 4, fill: c }, svg);

  // La linea si disegna solo se il browser sa misurare il tracciato: nel test
  // automatico (DOM finto in Node) getTotalLength non esiste e si salta.
  try {
    if (typeof ln.getTotalLength === 'function') {
      const len = ln.getTotalLength();
      ln.setAttribute('stroke-dasharray', len);
      host.style.setProperty('--len', len);
      host.classList.add('disegna');
    }
  } catch (e) { /* senza animazione il grafico resta corretto */ }

  if (dates && dates.length === values.length) {
    tipSpark(host, svg, { values, dates, X, Y, W, H, color: c });
  }
}

let CONTA_SPARK = 0;

/* Tooltip: un grafico in pagina si interroga col dito o col mouse. */
function tipSpark(host, svg, { values, dates, X, Y, W, H, color }) {
  const tip = document.createElement('div');
  tip.className = 'tip';
  tip.style.display = 'none';
  host.style.position = 'relative';
  host.appendChild(tip);
  const cross = el('line', { y1: 0, y2: H, stroke: css('--axis'), 'stroke-width': 1,
                             opacity: 0, 'vector-effect': 'non-scaling-stroke' }, svg);
  const dot = el('circle', { r: 4.5, fill: color, stroke: css('--surface-1'),
                             'stroke-width': 2, opacity: 0 }, svg);

  const muovi = (ev) => {
    const r = host.getBoundingClientRect();
    if (!r.width) return;
    const px = ('clientX' in ev ? ev.clientX : ev.touches[0].clientX) - r.left;
    const i = Math.max(0, Math.min(values.length - 1,
              Math.round((px / r.width) * (values.length - 1))));
    const vx = X(i), vy = Y(values[i]);
    cross.setAttribute('x1', vx); cross.setAttribute('x2', vx);
    cross.setAttribute('opacity', .5);
    dot.setAttribute('cx', vx); dot.setAttribute('cy', vy); dot.setAttribute('opacity', 1);
    tip.style.display = 'block';
    tip.innerHTML = `<b>${fmt.num(values[i])}</b><span>${fmt.date(dates[i])}</span>`;
    const w = tip.offsetWidth || 90;
    tip.style.left = Math.max(0, Math.min(r.width - w, (vx / W) * r.width - w / 2)) + 'px';
  };
  const esci = () => {
    tip.style.display = 'none';
    cross.setAttribute('opacity', 0);
    dot.setAttribute('opacity', 0);
  };
  host.addEventListener('mousemove', muovi);
  host.addEventListener('mouseleave', esci);
  host.addEventListener('touchstart', muovi, { passive: true });
  host.addEventListener('touchmove', muovi, { passive: true });
  host.addEventListener('touchend', esci);
}

/* ---------------------------------------------------------------------------
   ring: il voto da 0 a 100 come anello che si riempie.
   Un numero solo: la forma dice "e' una parte di un tutto", il numero al
   centro dice quanto. Il colore viene dalla fascia di classificazione, e non
   viaggia da solo - accanto c'e' sempre il semaforo con la parola scritta.
   --------------------------------------------------------------------------- */
function ring(host, { score, color = null, label = 'su 100' } = {}) {
  host.innerHTML = '';
  const c = color || css('--series-1');
  const R = 32, CIRC = 2 * Math.PI * R;
  const svg = el('svg', { viewBox: '0 0 74 74' }, host);
  el('circle', { class: 'track', cx: 37, cy: 37, r: R }, svg);
  const val = el('circle', { class: 'val', cx: 37, cy: 37, r: R, stroke: c,
                             'stroke-dasharray': CIRC.toFixed(1),
                             'stroke-dashoffset': CIRC.toFixed(1) }, svg);
  const num = document.createElement('div');
  num.className = 'num';
  num.innerHTML = `<span>${score}<small>${label}</small></span>`;
  host.appendChild(num);
  // si riempie subito dopo il disegno, cosi' l'animazione parte da zero
  const arrivo = CIRC * (1 - Math.max(0, Math.min(100, score)) / 100);
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(() => val.setAttribute('stroke-dashoffset', arrivo.toFixed(1)));
  } else {
    val.setAttribute('stroke-dashoffset', arrivo.toFixed(1));
  }
}

const colors = () => ({
  s1: css('--series-1'), s2: css('--series-2'), s3: css('--series-3'),
  seq: css('--seq-450'), seqLight: css('--seq-200'), seqDark: css('--seq-600'),
  good: css('--good'), warning: css('--warning'), serious: css('--serious'),
  critical: css('--critical'), muted: css('--muted'), axis: css('--axis'),
  up: css('--up'), down: css('--down'), text2: css('--text-2'),
});

return { fmt, lineChart, barH, columns, diverging, meter, sparkline, sparkArea,
         ring, colors };
})();
