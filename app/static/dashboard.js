(() => {
  const d = window.DASH;
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const money = (cents) => (cents < 0 ? "-$" : "$") + (Math.abs(cents) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  Chart.defaults.color = v("--text-secondary");
  Chart.defaults.borderColor = v("--grid");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

  const tooltip = { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${money(ctx.raw)}` } };
  const axisMoney = { ticks: { callback: (x) => money(x).replace(".00", ""), maxRotation: 0, maxTicksLimit: 6 }, grid: { color: v("--grid") } };
  const bar = { borderRadius: 4, borderSkipped: "start", borderColor: v("--surface"), borderWidth: { right: 2 } };

  const direct = d.direct.map((total, i) => total - d.viaCards[i]);
  const datasets = [{ label: d.view === "cash" ? "Paid from bank" : "Spent", data: direct, backgroundColor: v("--series-1"), ...bar }];
  if (d.view === "cash") datasets.push({ label: "Via credit cards", data: d.viaCards, backgroundColor: v("--series-2"), ...bar });

  new Chart(document.getElementById("byCategory"), {
    type: "bar",
    data: { labels: d.categories, datasets },
    options: {
      indexAxis: "y", maintainAspectRatio: false, barThickness: 16,
      plugins: { legend: { display: false }, tooltip: { ...tooltip, mode: "y", intersect: false,
        footer: (items) => `Total: ${money(items.reduce((s, i) => s + i.raw, 0))}` } },
      scales: { x: { stacked: true, ...axisMoney }, y: { stacked: true, grid: { display: false } } },
      onClick: (_, els) => {
        if (!els.length) return;
        const name = d.categories[els[0].index];
        const el = [...document.querySelectorAll("details.cat")].find((x) => x.querySelector(".name").textContent === name);
        if (el) { el.open = true; el.scrollIntoView({ behavior: "smooth", block: "center" }); }
      },
    },
  });

  new Chart(document.getElementById("trend"), {
    type: "bar",
    data: {
      labels: d.trend.map((t) => t[0]),
      datasets: [
        { label: "Income", data: d.trend.map((t) => t[1]), backgroundColor: v("--income"), borderRadius: 4, maxBarThickness: 28 },
        { label: "Expenses", data: d.trend.map((t) => t[2]), backgroundColor: v("--expense"), borderRadius: 4, maxBarThickness: 28 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...tooltip, mode: "index", intersect: false } },
      scales: { y: axisMoney, x: { grid: { display: false } } },
    },
  });
})();
