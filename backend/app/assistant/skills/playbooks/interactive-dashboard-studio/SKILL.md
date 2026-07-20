---
name: interactive-dashboard-studio
agents: case,financial,network,mo,legal,supervisor
description: "Build a self-contained interactive HTML dashboard (Chart.js) with KPI cards, multiple charts, contextual filters and a sortable table, delivered as ONE downloadable .html artifact. Use whenever the officer asks to create / build a dashboard, an interactive dashboard, a case/crime dashboard, an interactive report or panel with filters, or 'put these numbers into a dashboard'. For a SINGLE chart use visualize-data instead; this is for a multi-widget, filterable dashboard."
---

# Interactive Dashboard Studio

Patterns for building self-contained HTML/JS dashboards that are correct (no invisible dropdown options), well-organized (filters live next to what they affect), well-designed (not a templated "AI dashboard" look), and use the right chart for the data.

A dashboard has a different job than a marketing page: clarity beats novelty. Take design risks in one place (see Signature, below) and keep the rest disciplined — a reader should never have to think about the chrome to get to the number.

## Running in CLARA (read this first)

You have `run_python` (a fresh subprocess each call; Chart.js loads from the jsDelivr CDN inside the sandboxed artifact iframe). A dashboard request MUST end with ONE **self-contained `.html`** artifact — never a `.txt`, screenshot, or bare table.

### ⚠️ The rule that matters most: keep the file COMPACT so it writes in a single `run_python` call

Each tool call can only emit a few thousand tokens. If you paste a ~350-line document as one `html = """ … """`, the call is **cut off before the closing `"""`** and you get `SyntaxError: unterminated triple-quoted string literal`. That is the #1 way this skill fails. Avoid it:

- Treat §4 as a **menu to copy FROM, not a block to paste whole.** Include ONLY the chart helper(s) and CSS rules the dashboard actually uses. A 2–4 chart dashboard is ~120–180 lines — well within one call. Drop unused chart types, the sortable-table helper when there's no table, print styles, etc.
- Write the page in ONE `run_python` call and keep it under ~200 lines.
- Put the data in with a `__DATA__` placeholder + `.replace(...)`, NOT an f-string — the CSS/JS is full of `{ }` that would break `.format`/f-strings.

### Steps
1. **Get real numbers first** — never invent KPI values. For common breakdowns call `query_case_stats(group_by="district" | "crime_type" | "month" | "status")`; use `run_sql_select` for anything it can't express, and the money-trail / graph tools for financial or network widgets.
2. **Embed the aggregated rows as JSON** (`const DATA = <json.dumps(rows)>`), not raw records — keep to the pre-aggregated shape in §5.
3. **Write the compact page in ONE call.** Name the file with **spaces** (the artifact title comes from the filename). This complete example fits in a single call — adapt the tokens, layout, hero metric and chart choice per §1–§3; it is a starting point, not a fixed template:
   ```python
   import json
   rows = [("Bengaluru Urban", 13), ("Mysuru", 6), ("Mandya", 4)]  # from query_case_stats
   html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
   <meta name="viewport" content="width=device-width, initial-scale=1.0">
   <title>Crime Dashboard</title>
   <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1"></script>
   <style>
     :root{--bg:#f5f6f8;--card:#fff;--ink:#1a1f2b;--muted:#6c757d;--accent:#1f4e79}
     *{box-sizing:border-box;margin:0;padding:0}
     body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--ink);padding:16px}
     header{margin-bottom:16px}h1{font-size:20px}
     .kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:16px}
     .kpi-card,.chart-container{background:var(--card);border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
     .kpi-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
     .kpi-value{font-size:28px;font-weight:700}
     .chart-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}
     .chart-container h3{font-size:14px;margin-bottom:12px}canvas{max-height:320px}
   </style></head><body>
   <header><h1>Crime Dashboard — Karnataka</h1></header>
   <section class="kpi-row">
     <div class="kpi-card"><div class="kpi-label">Total cases</div><div class="kpi-value" id="kTotal">0</div></div>
     <div class="kpi-card"><div class="kpi-label">Districts</div><div class="kpi-value" id="kDist">0</div></div>
   </section>
   <section class="chart-row">
     <div class="chart-container"><h3>Cases by district</h3><canvas id="byDistrict"></canvas></div>
   </section>
   <script>
   const ACCENT = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
   const DATA = __DATA__;
   document.getElementById('kTotal').textContent = DATA.reduce((a,r)=>a+r[1],0);
   document.getElementById('kDist').textContent = DATA.length;
   new Chart(document.getElementById('byDistrict'), {
     type:'bar',
     data:{labels:DATA.map(r=>r[0]),datasets:[{data:DATA.map(r=>r[1]),backgroundColor:ACCENT,borderRadius:4}]},
     options:{indexAxis:'y',responsive:true,plugins:{legend:{display:false}},scales:{x:{beginAtZero:true}}}
   });
   </script></body></html>""".replace("__DATA__", json.dumps(rows))
   with open("Crime Dashboard.html", "w", encoding="utf-8") as f:
       f.write(html)
   print("Saved dashboard;", len(rows), "rows")
   ```
   Add filters/table only when the request needs them, copying the corrected patterns from §3–§4. Keep it self-contained: no local file references, no build step.
4. **If a dashboard genuinely must be large** (many charts + a table) and won't fit one call, build it across several `run_python` calls **into a temporary `Crime Dashboard.part` file** (`open(path, "a", encoding="utf-8")` to append), and only in the LAST call `os.replace("Crime Dashboard.part", "Crime Dashboard.html")`. A `.part` file is not a known artifact type, so it is never shown — the officer only ever sees the finished dashboard, never a half-written one. (Each call is a fresh subprocess, so nothing but files persists between calls — always append to the file, never rely on Python variables from a previous call.)
5. **Answer.** 2–4 lines naming the hero metric and the one or two things the dashboard surfaces, then tell the officer the interactive dashboard is attached below. Do not restate every number in prose.

---

## 1. Design foundations — decide before you write markup

### Ground it in the audience and the decision
Before touching HTML, answer three questions and write the answers down as a comment at the top of your `<script>` block:
- **Who reads this and what decision does it drive?** (an exec skimming for anomalies vs. an analyst drilling into rows needs different density)
- **What's the one number or trend this dashboard exists to surface?** — that becomes the hero, not just another KPI card in a row of six identical cards.
- **What's the refresh cadence / data size?** — static snapshot vs. something that will be re-embedded daily changes how much interactivity is worth building.

### A compact token system, not ad-hoc colors
Define this once, at the top, and derive everything else from it — don't hand-pick colors per chart later:

- **Color** (4–6 named hex values): a background pair (page + card), a text pair (primary + secondary), 1 brand/accent color, and a positive/negative pair for deltas. Pick the accent to fit the domain (e.g., a fintech dashboard doesn't need the same teal every SaaS dashboard uses).
- **Type**: one display face for the hero number/title, one body face for labels and table text, and — if you need a data/utility face — a tabular-figure numeric font so columns of numbers align. Do not just default to the system font stack for everything; a single deliberate pairing makes the dashboard feel considered rather than templated.
- **Layout**: sketch the grid in one sentence + ASCII before coding it: is this "hero metric + supporting grid," "sidebar filters + main canvas," or "tabs per business unit"? Don't default to "header bar + KPI row + 2x2 chart grid" just because it's the most common pattern — check whether the actual content calls for it.
- **Signature**: pick the one element this dashboard will be remembered by — an unusual but justified chart choice, a distinctive hero stat treatment, a well-executed hover interaction. Spend your design boldness there; keep KPI cards, tables, and chart chrome quiet everywhere else.

### Three "AI dashboard" defaults to actively avoid
Generated dashboards cluster around a few templated looks. None are wrong, but reach for them only if the brief actually calls for it, not by default:
1. Dark navy/near-black header with a neon or gradient accent and glassy translucent filter pills — the exact pattern this skill used to ship, and the direct cause of the invisible-dropdown bug (see §3).
2. Purple-to-blue gradients on KPI cards or buttons, paired with a generic geometric sans (Inter, Poppins) everywhere.
3. Uniform heavy border-radius on every card, button, and chart container with no variation — it reads as a component-library default rather than a designed surface.

### Writing on the dashboard
KPI labels, empty states, and filter labels are content decisions, not filler. Name filters by what the user is selecting ("Region," not "dim_region"), and make empty/loading states say what's happening ("No orders match these filters" beats a blank chart).

### Self-critique before shipping
Once built: remove one accessory (per Coco Chanel's advice cited in the frontend-design skill) — is there a decorative element that doesn't serve reading the data? Check keyboard focus visibility on every filter, verify contrast (see §3), and confirm the design still works at 768px.

---

## 2. Choosing the right chart

Pick the chart by the **question**, then narrow by **data shape**. Don't pick a chart because it looks impressive — the wrong type actively misleads.

### Step 1 — What question is this chart answering?

| Question | Chart types | Notes |
|---|---|---|
| How do categories compare? | Bar / column chart | The default workhorse. Use horizontal bars once you have >7-8 categories or long labels. |
| How has a value changed over time? | Line chart, area chart | Requires a genuinely continuous x-axis (dates, sequential periods). |
| What's the composition / part-to-whole? | Pie/doughnut (≤5-6 slices), 100% stacked bar, treemap | Pie charts fail once slices are numerous or similarly sized — switch to stacked bar or treemap. |
| What's the relationship between two numeric variables? | Scatter plot, bubble chart | Bubble adds a 3rd dimension via point size — cap at ~1,000 points or sample. |
| What's the distribution of a single variable? | Histogram, box plot | Not a bar chart of raw values — bin continuous data first. |
| Where, geographically? | Choropleth / point map | Out of scope for Chart.js; use a mapping library if this comes up. |

### Step 2 — Sanity-check against the data type

| Data type | Good fit | Poor fit |
|---|---|---|
| Categorical, few categories (≤6) | Bar, pie | Line (implies false continuity between categories) |
| Categorical, many categories (>8) | Horizontal bar (sorted), treemap | Pie (unreadable past ~6 slices), vertical bar (label collision) |
| Continuous time series | Line, area | Pie/doughnut (no such thing as "trend over time" composition) |
| Two continuous variables | Scatter, bubble | Bar (loses the joint relationship) |
| Single continuous variable's spread | Histogram, box plot | Line chart connecting sorted values (implies an order that isn't real) |

### Why position-based charts win when in doubt
Human perception decodes **position along a common scale** and **length** far more accurately than **angle** or **area** — this is the well-established finding behind why bar/line charts are usually the safer default and pie/bubble charts are usually the riskier one (Cleveland and McGill's 1985 study ranked the visual encodings people read most and least accurately). When you're unsure between two chart types for the same data, prefer the one that encodes value as position or length.

### Common pitfalls to check before shipping a chart
- Pie/doughnut with more than ~6 slices, or slices too close in size to compare by eye.
- Stacked bars used to compare anything except the first segment or the total — the middle segments have no shared baseline, so precise comparison across bars is impossible.
- A line chart drawn across categorical (non-ordered) labels — implies a trend that doesn't exist.
- Y-axis that doesn't start at zero on a bar chart (fine for a line chart focused on rate of change, misleading for a bar chart which encodes magnitude via length).
- More than ~5-6 lines on one line chart — split into small multiples instead.

### Additional Chart.js snippets (relationship & composition, not in the base set)

**Scatter plot** (relationship between two numeric variables):
```javascript
function createScatterChart(canvasId, points, options = {}) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: options.label || 'Data points',
                data: points, // [{x: 10, y: 20}, ...]
                backgroundColor: (COLORS[0] || '#4C72B0') + 'AA',
                pointRadius: 4,
                pointHoverRadius: 7,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { title: { display: true, text: options.xLabel || '' } },
                y: { title: { display: true, text: options.yLabel || '' } }
            }
        }
    });
}
```

**100% stacked bar** (composition across categories — safer than pie once you have >2 series or >6 categories):
```javascript
function createStackedBarChart(canvasId, labels, datasets) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: datasets.map((ds, i) => ({
                label: ds.label,
                data: ds.data,
                backgroundColor: COLORS[i % COLORS.length],
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { stacked: true },
                y: { stacked: true, beginAtZero: true }
            },
            plugins: { legend: { position: 'bottom' } }
        }
    });
}
```

(Line, bar, and doughnut implementations are in §4 below — unchanged from the base pattern, since those were already correct.)

---

## 3. Filters that work: fixing contrast and placement

### 3a. The invisible-dropdown fix

**Don't do this** (what caused the bug): put a dark, translucent background behind a native `<select>` and rely on styling `<option>` to match.

```css
/* AVOID — relies on option background-color rendering, which many browsers
   apply inconsistently, leaving white text on a white native popup until hover */
.filter-group select {
    background: rgba(255, 255, 255, 0.1);
    color: white;
}
.filter-group select option {
    background: var(--bg-header);
    color: white;
}
```

**Do this instead — Option A (safe default): light-themed selects everywhere**, regardless of what the surrounding header looks like. This is the single most reliable fix, because it never depends on a browser correctly re-styling the native popup:

```css
.filter-group select,
.filter-group input[type="date"] {
    padding: 6px 10px;
    border: 1px solid var(--border-color, #d0d5dd);
    border-radius: 6px;
    background: #ffffff;
    color: var(--text-primary, #212529);
    font-size: 13px;
}
/* No need to style <option> at all — default dark-on-light is correct everywhere */
```
If the header itself is dark, put the filter row on a light "toolbar" strip below or beside the header (see 3b) rather than embedding light controls directly on a dark bar — that also sets up the contextual placement fix.

**Do this instead — Option B (when you truly need dark, on-brand controls): a custom listbox**, which sidesteps native `<option>` styling entirely because you render the option list yourself:

```html
<div class="custom-select" data-value="all">
    <button class="custom-select-trigger" aria-haspopup="listbox" aria-expanded="false">
        All Regions <span class="chevron">▾</span>
    </button>
    <ul class="custom-select-options" role="listbox" hidden></ul>
</div>
```

```css
.custom-select { position: relative; display: inline-block; }
.custom-select-trigger {
    background: rgba(255,255,255,0.1);
    color: var(--text-on-dark);
    border: 1px solid rgba(255,255,255,0.25);
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
}
.custom-select-options {
    position: absolute; top: 100%; left: 0; z-index: 20;
    list-style: none; margin: 4px 0 0; padding: 4px;
    min-width: 100%; max-height: 240px; overflow-y: auto;
    background: var(--bg-header); /* fully author-controlled, no native popup involved */
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
}
.custom-select-options li {
    padding: 8px 10px; border-radius: 4px; color: var(--text-on-dark);
    cursor: pointer; font-size: 13px;
}
.custom-select-options li:hover,
.custom-select-options li:focus {
    background: rgba(255,255,255,0.15); /* contrast guaranteed since you wrote both colors */
}
```

```javascript
function initCustomSelect(root, onChange) {
    const trigger = root.querySelector('.custom-select-trigger');
    const list = root.querySelector('.custom-select-options');

    trigger.addEventListener('click', () => {
        const isOpen = !list.hidden;
        list.hidden = isOpen;
        trigger.setAttribute('aria-expanded', String(!isOpen));
    });

    list.addEventListener('click', (e) => {
        const li = e.target.closest('li');
        if (!li) return;
        root.dataset.value = li.dataset.value;
        trigger.firstChild.textContent = li.textContent + ' ';
        list.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        onChange(li.dataset.value);
    });

    document.addEventListener('click', (e) => {
        if (!root.contains(e.target)) { list.hidden = true; trigger.setAttribute('aria-expanded', 'false'); }
    });
}
```
Option B costs more code and you're responsible for keyboard navigation (arrow keys, Escape) if accessibility matters for this dashboard — reach for it only when the dark aesthetic is a real requirement, not a default.

### 3b. Stop pinning every filter to the top

A single always-visible header filter bar implicitly claims every filter affects the whole page. That's often false, and it forces the reader to scroll back up to check what's currently filtering the chart in front of them. Use scope to decide placement:

- **Global filters** (date range, region — affect everything): keep these in one place, but consider a slim sticky sub-bar *under* the header rather than baked into the header itself, so it can be light-themed independently (solves 3a for free) and stays visible on scroll without competing with the title.
- **Section-scoped filters** (a metric toggle that only changes one chart): put the control inside that `chart-container`, next to its title — not in the global bar.
- **Table-scoped filters** (column search, row-level toggle): inside the `table-section`, near the header row it filters.

```html
<div class="chart-container">
    <div class="chart-header">
        <h3 class="chart-title">Revenue by Channel</h3>
        <div class="chart-scope-filter">
            <!-- segmented control below, scoped to only this chart -->
        </div>
    </div>
    <canvas id="revenue-by-channel"></canvas>
</div>
```
```css
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
```

### 3c. Reach for the right control, not always a dropdown

| Situation | Better control than a dropdown |
|---|---|
| ≤5 mutually exclusive options | Segmented control / pill toggle group — every option visible at once, no click-to-reveal |
| Multiple values selectable at once | Chip/checkbox multi-select |
| Many possible values (>15) | Search/typeahead input filtering a list |
| Numeric threshold or range | A range slider (dual-handle for min/max) |
| Binary on/off | A switch, not a 2-item dropdown |

**Segmented control** (good replacement for small single-select dropdowns — also sidesteps the native `<option>` problem entirely, since it's just buttons):
```html
<div class="segmented-control" role="tablist">
    <button class="segment active" data-value="all">All</button>
    <button class="segment" data-value="north">North</button>
    <button class="segment" data-value="south">South</button>
</div>
```
```css
.segmented-control { display: inline-flex; background: rgba(255,255,255,0.08); border-radius: 8px; padding: 3px; }
.segment { border: none; background: transparent; color: var(--text-on-dark); padding: 6px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.segment.active { background: rgba(255,255,255,0.9); color: var(--text-primary); font-weight: 600; }
```
```javascript
function initSegmentedControl(root, onChange) {
    root.querySelectorAll('.segment').forEach(btn => {
        btn.addEventListener('click', () => {
            root.querySelectorAll('.segment').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            onChange(btn.dataset.value);
        });
    });
}
```

### 3d. Combined filter logic (unchanged, still the right pattern)
```javascript
applyFilters() {
    const region = this.getScopedFilterValue('region');   // from global bar
    const channel = this.getScopedFilterValue('channel');  // from a chart-scoped segmented control
    const startDate = document.getElementById('filter-date-start').value;
    const endDate = document.getElementById('filter-date-end').value;

    this.filteredData = this.rawData.filter(row => {
        if (region && row.region !== region) return false;
        if (channel && row.channel !== channel) return false;
        if (startDate && row.date < startDate) return false;
        if (endDate && row.date > endDate) return false;
        return true;
    });

    this.renderKPIs();
    this.updateCharts();
    this.renderTable();
}
```

---

## 4. Base template & standard components — a MENU, copy only what you use

These are reference implementations that don't require judgment. **Do NOT paste this whole section into one file** — that is what overruns a single `run_python` call and truncates the string (see "Running in CLARA" above). Copy ONLY the pieces your dashboard actually uses (the chart helpers for the chart types you chose, the table helper only if there's a table) and spend your attention on §1–§3 (design, chart choice, filters), which are where dashboards actually go wrong. The CSS already uses the corrected light-themed `.filter-group select` (§3a) — don't re-introduce the old dark translucent select styling.

### Base HTML structure
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Title</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0" integrity="sha384-cVMg8E3QFwTvGCDuK+ET4PD341jF3W8nO1auiXfuZNQkzbUUiBGLsIQUE+b1mxws" crossorigin="anonymous"></script>
    <style>
        /* Design tokens + component styles — see CSS block below */
    </style>
</head>
<body>
    <div class="dashboard-container">
        <header class="dashboard-header">
            <h1>Dashboard Title</h1>
            <div class="filters filters-global"><!-- global-scope filters only --></div>
        </header>

        <section class="kpi-row"><!-- KPI cards --></section>
        <section class="chart-row"><!-- chart containers, each with its own scoped filter if needed --></section>
        <section class="table-section"><!-- data table --></section>

        <footer class="dashboard-footer">
            <span>Data as of: <span id="data-date"></span></span>
        </footer>
    </div>

    <script>
        const DATA = []; // embedded, pre-aggregated data — see §5 for size limits

        class Dashboard {
            constructor(data) {
                this.rawData = data;
                this.filteredData = data;
                this.charts = {};
                this.init();
            }
            init() {
                this.setupFilters();
                this.renderKPIs();
                this.renderCharts();
                this.renderTable();
            }
            applyFilters() { /* see §3d */ }
        }

        const dashboard = new Dashboard(DATA);
    </script>
</body>
</html>
```

### KPI card
```html
<div class="kpi-card">
    <div class="kpi-label">Total Revenue</div>
    <div class="kpi-value" id="kpi-revenue">$0</div>
    <div class="kpi-change positive" id="kpi-revenue-change">+0%</div>
</div>
```
```javascript
function renderKPI(elementId, value, previousValue, format = 'number') {
    const el = document.getElementById(elementId);
    const changeEl = document.getElementById(elementId + '-change');
    el.textContent = formatValue(value, format);
    if (previousValue && previousValue !== 0) {
        const pctChange = ((value - previousValue) / previousValue) * 100;
        const sign = pctChange >= 0 ? '+' : '';
        changeEl.textContent = `${sign}${pctChange.toFixed(1)}% vs prior period`;
        changeEl.className = `kpi-change ${pctChange >= 0 ? 'positive' : 'negative'}`;
    }
}

function formatValue(value, format) {
    switch (format) {
        case 'currency':
            if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
            if (value >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
            return `$${value.toFixed(0)}`;
        case 'percent':
            return `${value.toFixed(1)}%`;
        case 'number':
            if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
            if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
            return value.toLocaleString();
        default:
            return value.toString();
    }
}
```

### Chart.js: line, bar, doughnut (unchanged — these were already correct)
```javascript
function createLineChart(canvasId, labels, datasets) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets.map((ds, i) => ({
                label: ds.label,
                data: ds.data,
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: COLORS[i % COLORS.length] + '20',
                borderWidth: 2,
                fill: ds.fill || false,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 6,
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top', labels: { usePointStyle: true, padding: 20 } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${formatValue(ctx.parsed.y, 'currency')}`
                    }
                }
            },
            scales: {
                x: { grid: { display: false } },
                y: { beginAtZero: true, ticks: { callback: (v) => formatValue(v, 'currency') } }
            }
        }
    });
}

function createBarChart(canvasId, labels, data, options = {}) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const isHorizontal = options.horizontal || labels.length > 8;
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: options.label || 'Value',
                data: data,
                backgroundColor: options.colors || COLORS.map(c => c + 'CC'),
                borderColor: options.colors || COLORS,
                borderWidth: 1,
                borderRadius: 4,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: isHorizontal ? 'y' : 'x',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => formatValue(ctx.parsed[isHorizontal ? 'x' : 'y'], options.format || 'number')
                    }
                }
            },
            scales: {
                x: { beginAtZero: true, grid: { display: isHorizontal } },
                y: { beginAtZero: !isHorizontal, grid: { display: !isHorizontal } }
            }
        }
    });
}

function createDoughnutChart(canvasId, labels, data) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{ data: data, backgroundColor: COLORS.map(c => c + 'CC'), borderColor: '#ffffff', borderWidth: 2 }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: { position: 'right', labels: { usePointStyle: true, padding: 15 } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                            const pct = ((ctx.parsed / total) * 100).toFixed(1);
                            return `${ctx.label}: ${formatValue(ctx.parsed, 'number')} (${pct}%)`;
                        }
                    }
                }
            }
        }
    });
}

function updateChart(chart, newLabels, newData) {
    chart.data.labels = newLabels;
    if (Array.isArray(newData[0])) {
        newData.forEach((data, i) => { chart.data.datasets[i].data = data; });
    } else {
        chart.data.datasets[0].data = newData;
    }
    chart.update('none'); // disables animation for instant filter-driven updates
}
```

### Sortable table (unchanged)
```javascript
function renderTable(containerId, data, columns) {
    const container = document.getElementById(containerId);
    let sortCol = null, sortDir = 'desc';

    function render(sortedData) {
        let html = '<table class="data-table"><thead><tr>';
        columns.forEach(col => {
            const arrow = sortCol === col.field ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
            html += `<th onclick="sortTable('${col.field}')" style="cursor:pointer">${col.label}${arrow}</th>`;
        });
        html += '</tr></thead><tbody>';
        sortedData.forEach(row => {
            html += '<tr>' + columns.map(col => {
                const value = col.format ? formatValue(row[col.field], col.format) : row[col.field];
                return `<td>${value}</td>`;
            }).join('') + '</tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    }

    window.sortTable = function(field) {
        sortDir = sortCol === field ? (sortDir === 'asc' ? 'desc' : 'asc') : 'desc';
        sortCol = field;
        const sorted = [...data].sort((a, b) => {
            const cmp = a[field] < b[field] ? -1 : a[field] > b[field] ? 1 : 0;
            return sortDir === 'asc' ? cmp : -cmp;
        });
        render(sorted);
    };
    render(data);
}
```

### CSS: tokens, layout, and corrected components
```css
:root {
    --bg-primary: #f8f9fa;
    --bg-card: #ffffff;
    --bg-header: #1a1a2e;
    --text-primary: #212529;
    --text-secondary: #6c757d;
    --text-on-dark: #ffffff;
    --color-1: #4C72B0; --color-2: #DD8452; --color-3: #55A868;
    --color-4: #C44E52; --color-5: #8172B3; --color-6: #937860;
    --positive: #28a745; --negative: #dc3545; --neutral: #6c757d;
    --gap: 16px; --radius: 8px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
}

.dashboard-container { max-width: 1400px; margin: 0 auto; padding: var(--gap); }

.dashboard-header {
    background: var(--bg-header);
    color: var(--text-on-dark);
    padding: 20px 24px;
    border-radius: var(--radius);
    margin-bottom: var(--gap);
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 12px;
}
.dashboard-header h1 { font-size: 20px; font-weight: 600; }

.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--gap); margin-bottom: var(--gap); }
.kpi-card { background: var(--bg-card); border-radius: var(--radius); padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.kpi-label { font-size: 13px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.kpi-value { font-size: 28px; font-weight: 700; margin-bottom: 4px; }
.kpi-change { font-size: 13px; font-weight: 500; }
.kpi-change.positive { color: var(--positive); }
.kpi-change.negative { color: var(--negative); }

.chart-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: var(--gap); margin-bottom: var(--gap); }
.chart-container { background: var(--bg-card); border-radius: var(--radius); padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.chart-container h3 { font-size: 14px; font-weight: 600; }
.chart-container canvas { max-height: 300px; }

/* Filters — corrected: light-themed, no reliance on styling native <option> */
.filters { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.filter-group { display: flex; align-items: center; gap: 6px; }
.filter-group label { font-size: 12px; color: var(--text-secondary); }
.filter-group select,
.filter-group input[type="date"] {
    padding: 6px 10px;
    border: 1px solid #d0d5dd;
    border-radius: 6px;
    background: #ffffff;
    color: var(--text-primary);
    font-size: 13px;
}

/* If a filter row must sit on the dark header, use a segmented control (§3c)
   or the custom listbox (§3a Option B) instead of a native <select> — never
   a native <select> styled with light text on a dark background. */

.table-section { background: var(--bg-card); border-radius: var(--radius); padding: 20px 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table thead th {
    text-align: left; padding: 10px 12px; border-bottom: 2px solid #dee2e6;
    color: var(--text-secondary); font-weight: 600; font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.5px; white-space: nowrap; user-select: none;
}
.data-table thead th:hover { color: var(--text-primary); background: #f8f9fa; }
.data-table tbody td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }
.data-table tbody tr:hover { background: #f8f9fa; }
.data-table tbody tr:last-child td { border-bottom: none; }

@media (max-width: 768px) {
    .dashboard-header { flex-direction: column; align-items: flex-start; }
    .kpi-row { grid-template-columns: repeat(2, 1fr); }
    .chart-row { grid-template-columns: 1fr; }
    .filters { flex-direction: column; align-items: flex-start; }
}

@media print {
    body { background: white; }
    .dashboard-container { max-width: none; }
    .filters { display: none; }
    .chart-container { break-inside: avoid; }
    .kpi-card { border: 1px solid #dee2e6; box-shadow: none; }
}
```

---

## 5. Performance considerations for large datasets

| Data size | Approach |
|---|---|
| <1,000 rows | Embed directly in HTML. Full interactivity. |
| 1,000–10,000 rows | Embed in HTML. May need to pre-aggregate for charts. |
| 10,000–100,000 rows | Pre-aggregate server-side. Embed only aggregated data. |
| >100,000 rows | Not suitable for a client-side dashboard. Use a BI tool or paginate. |

```javascript
// DON'T: embed 50,000 raw rows
const RAW_DATA = [/* 50,000 rows */];

// DO: pre-aggregate before embedding
const CHART_DATA = {
    monthly_revenue: [{ month: '2024-01', revenue: 150000, orders: 1200 }, /* 12 rows, not 50,000 */],
    top_products: [{ product: 'Widget A', revenue: 45000 } /* 10 rows */],
    kpis: { total_revenue: 1980000, total_orders: 15600, avg_order_value: 127 }
};
```

- Limit line charts to <500 points per series (downsample if needed); bar charts to <50 categories; scatter plots to ~1,000 points.
- `animation: false` in Chart.js options when a dashboard has many charts.
- Use `chart.update('none')` instead of `chart.update()` for filter-triggered updates.
- Paginate tables past 100–200 visible rows ("Showing 1–50 of 2,340").
- Update only the DOM elements that changed on filter change — don't rebuild the whole dashboard.
