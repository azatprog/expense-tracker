(() => {
  const { typical, actual, hasActuals } = window.PLAN;
  const form = document.getElementById('plan-form');
  const money = (c) => (c < 0 ? '-$' : '$') + (Math.abs(c) / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const cents = (s) => Math.round((parseFloat(String(s).replace(/[$,\s]/g, '')) || 0) * 100);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  const kindOf = (tr) => tr.closest('table.plan').dataset.kind;
  const linksOf = (tr) => tr.querySelector('input[name=categories]').value.split('|').filter(Boolean);
  const setLinks = (tr, cats) => { tr.querySelector('input[name=categories]').value = cats.join('|'); };
  const sumOf = (map, cats) => {
    const known = cats.filter((c) => c in map);
    return known.length ? known.reduce((a, c) => a + map[c], 0) : null;
  };

  // Fill a line's Avg/Actual cells, its "linked to" caption and its expanded breakdown.
  function renderLine(tr) {
    const kind = kindOf(tr), cats = linksOf(tr), detail = tr.nextElementSibling;
    const avg = sumOf(typical[kind] || {}, cats);
    tr.querySelector('.avg').textContent = avg == null ? '—' : money(avg);
    if (hasActuals) {
      const act = cats.length ? cats.reduce((a, c) => a + ((actual[kind] || {})[c] || 0), 0) : null;
      tr.querySelector('.actual').textContent = act == null ? '—' : money(act);
    }
    const name = tr.querySelector('input[name=name]').value.trim();
    tr.querySelector('.linked').textContent =
      cats.length && !(cats.length === 1 && cats[0] === name) ? cats.join(' + ') : '';

    const planned = cents(tr.querySelector('input[name=amount]').value);
    const weights = cats.map((c) => Math.max((typical[kind] || {})[c] || 0, 0));
    const wsum = weights.reduce((a, b) => a + b, 0);
    const body = detail.querySelector('.parts tbody');
    body.replaceChildren(...cats.map((c, i) => {
      const r = el('tr');
      r.append(el('td', null, c));
      r.append(el('td', 'num', c in (typical[kind] || {}) ? money(typical[kind][c]) : '—'));
      r.append(el('td', 'num', wsum ? money(Math.round(planned * weights[i] / wsum)) : '—'));
      if (hasActuals) r.append(el('td', 'num', money((actual[kind] || {})[c] || 0)));
      const x = el('button', 'btn small unlink', '✕');
      x.type = 'button'; x.dataset.category = c; x.setAttribute('aria-label', 'Unlink ' + c);
      const td = el('td'); td.append(x); r.append(td);
      return r;
    }));
    if (!cats.length) {
      const r = el('tr'); const td = el('td', 'sub', 'Not linked to any category yet.');
      td.colSpan = hasActuals ? 5 : 4; r.append(td); body.append(r);
    }
  }

  function recalc() {
    const totals = {};
    form.querySelectorAll('table.plan').forEach((t) => {
      const lines = [...t.querySelectorAll('tr.line')];
      const sum = lines.reduce((a, tr) => a + cents(tr.querySelector('input[name=amount]').value), 0);
      totals[t.dataset.kind] = sum;
      t.querySelector('.total').textContent = money(sum);
      const kind = t.dataset.kind;
      const avgAll = sumOf(typical[kind] || {}, [...new Set(lines.flatMap(linksOf))]);
      t.querySelector('.avg-total').textContent = avgAll == null ? '' : money(avgAll);
      if (hasActuals) {
        const actAll = [...new Set(lines.flatMap(linksOf))].reduce((a, c) => a + ((actual[kind] || {})[c] || 0), 0);
        t.querySelector('.actual-total').textContent = money(actAll);
      }
    });
    const left = (totals.income || 0) - (totals.expense || 0);
    document.getElementById('t-income').textContent = money(totals.income || 0);
    document.getElementById('t-expense').textContent = money(totals.expense || 0);
    const l = document.getElementById('t-left');
    l.textContent = money(left);
    l.classList.toggle('neg', left < 0);
  }

  const markDirty = () => { document.getElementById('dirty').hidden = false; };
  const lineOf = (node) => { const tr = node.closest('tr.line, tr.detail'); return tr.classList.contains('line') ? tr : tr.previousElementSibling; };

  form.addEventListener('input', (e) => {
    if (e.target.closest('tr.line')) renderLine(lineOf(e.target));
    recalc(); markDirty();
  });
  form.addEventListener('change', (e) => {
    if (!e.target.classList.contains('link-cat') || !e.target.value) return;
    const tr = lineOf(e.target), cats = linksOf(tr);
    if (!cats.includes(e.target.value)) setLinks(tr, [...cats, e.target.value]);
    e.target.value = '';
    renderLine(tr); recalc(); markDirty();
  });
  form.addEventListener('click', (e) => {
    const t = e.target;
    if (t.classList.contains('toggle')) {
      const tr = lineOf(t), detail = tr.nextElementSibling, open = detail.hidden;
      detail.hidden = !open;
      t.textContent = open ? '▾' : '▸';
      t.setAttribute('aria-expanded', String(open));
    } else if (t.classList.contains('unlink')) {
      const tr = lineOf(t);
      setLinks(tr, linksOf(tr).filter((c) => c !== t.dataset.category));
      renderLine(tr); recalc(); markDirty();
    } else if (t.classList.contains('remove')) {
      const tr = lineOf(t);
      tr.nextElementSibling.remove(); tr.remove();
      recalc(); markDirty();
    } else if (t.classList.contains('add')) {
      const kind = t.dataset.kind;
      const rows = [...document.getElementById('row-' + kind).content.children].map((r) => r.cloneNode(true));
      form.querySelector(`table.plan[data-kind=${kind}] > tbody`).append(...rows);
      renderLine(rows[0]);
      rows[0].querySelector('input[name=name]').focus();
      recalc(); markDirty();
    }
  });
  window.addEventListener('beforeunload', (e) => { if (!document.getElementById('dirty').hidden) e.preventDefault(); });
  form.addEventListener('submit', () => { document.getElementById('dirty').hidden = true; });

  form.querySelectorAll('tr.line').forEach(renderLine);
  recalc();
})();
