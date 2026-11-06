// A small stand-in for the parts of the claude.ai Dashboard runtime that index.html uses:
// dash.calc, dash.data, dash.draw, dash.onData, dash.setLink and dash.colors.
// It lets the same page run as a plain static site. Data comes from window.DASH_DATA,
// which build_site.py embeds in the page.
window.dash = (() => {
  const calcs = new Map();
  const results = new Map();
  const painters = new Map();
  const listeners = [];
  let ready = false;

  function resolve(id, seen = new Set()) {
    if (results.has(id)) return results.get(id);
    let out;
    if (Object.prototype.hasOwnProperty.call(window.DASH_DATA.datasets, id)) {
      out = {status: 'ok', data: window.DASH_DATA.datasets[id]};
    } else if (calcs.has(id) && !seen.has(id)) {
      seen.add(id);
      const c = calcs.get(id);
      const inputs = c.inputs.map((name) => resolve(name, seen));
      const bad = inputs.find((g) => g.status !== 'ok');
      if (bad) out = {status: 'error', error: `${id}: an input is unavailable`};
      else {
        try {
          out = {status: 'ok', data: c.fn(...inputs.map((g) => g.data))};
        } catch (e) {
          console.error(`calc ${id} failed`, e);
          out = {status: 'error', error: String(e)};
        }
      }
    } else out = {status: 'error', error: `unknown source ${id}`};
    results.set(id, out);
    return out;
  }

  function paint(name) {
    const fn = painters.get(name);
    if (!fn) return;
    document.querySelectorAll(`[data-draw="${name}"]`).forEach((el) => {
      try {
        fn(el);
      } catch (e) {
        console.error(`draw ${name} failed`, e);
      }
    });
  }

  function start() {
    ready = true;
    painters.forEach((_, name) => paint(name));
    listeners.forEach((fn) => fn());
    let width = window.innerWidth;
    let timer;
    window.addEventListener('resize', () => {
      if (window.innerWidth === width) return;
      width = window.innerWidth;
      clearTimeout(timer);
      timer = setTimeout(() => paint('chart'), 150);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else queueMicrotask(start);

  return {
    colors: [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `var(--series-${n})`),
    calc: (id, def) => { calcs.set(id, def); },
    data: (id) => (ready ? resolve(id) : {status: 'loading'}),
    draw: (name, fn) => { painters.set(name, fn); },
    onData: (fn) => { listeners.push(fn); },
    setLink: (id) => { history.replaceState(null, '', `#${id}`); },
  };
})();
