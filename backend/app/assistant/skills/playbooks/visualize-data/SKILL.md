---
name: visualize-data
agents: case,financial,network,mo,supervisor
description: "Turn numbers the officer asked to SEE into an interactive chart (bar, line, pie, horizontal bar). Use whenever the officer asks for a chart, graph, plot, visualisation, bar/line/pie chart, histogram, 'show me a chart of', 'visualise', or any 'by district / by month / over time / distribution' breakdown that reads better as a picture than a table. Produces a downloadable interactive HTML artifact (Plotly), never a text file."
---

# Data Visualisation (interactive Plotly HTML)

You have `run_python`, and `plotly`, `matplotlib` and `pandas` are installed. A chart
request MUST end with an interactive `.html` artifact for the on-screen panel.
NEVER write an ASCII/text "bar chart" into a `.txt` file.

## Steps

1. **Get the numbers first — prefer the hardened tool** so the chart matches the rest of
   the app. For the common breakdowns (by district, crime type, month, or status) call
   `query_case_stats(group_by="district" | "crime_type" | "month" | "status")`. Use
   `run_sql_select` ONLY for a breakdown `query_case_stats` cannot produce. Canonical
   cases-by-district (matches `query_case_stats`):
   ```sql
   SELECT g.IncidentDistrict AS district, COUNT(*) AS cases
   FROM CaseMaster c
   LEFT JOIN EXT_CaseGeo g ON g.CaseMasterID = c.CaseMasterID
   GROUP BY g.IncidentDistrict
   ORDER BY cases DESC
   ```

2. **Draw it with Plotly via `run_python`.** Paste the rows as a Python list literal.
   Name the file with **spaces**, not underscores (e.g. `Cases by District.html`):
   ```python
   import plotly.graph_objects as go

   data = [("Bengaluru Urban", 13), ("Chikkaballapur", 6), ("Bengaluru Rural", 6)]
   data = data[:15]
   labels = [str(r[0]) for r in data]
   values = [float(r[1]) for r in data]

   fig = go.Figure(go.Bar(x=values, y=labels, orientation="h",
                          marker_color="#3b82f6", text=values, textposition="outside"))
   fig.update_layout(
       title="Case count by district",
       xaxis_title="Cases",
       yaxis=dict(autorange="reversed"),
       margin=dict(l=140, r=40, t=60, b=40),
       height=max(360, 40 * len(labels) + 80),
   )
   fig.write_html("Cases by District.html", include_plotlyjs=True, full_html=True)
   print("Saved interactive chart with", len(data), "categories")
   ```

3. **Chart-type guide**
   - Category comparison → horizontal bar (`orientation="h"`).
   - Over time / trend → `go.Scatter(..., mode="lines+markers")`.
   - Share of a whole → `go.Pie(labels=..., values=...)`.

4. **PDF-bound charts** (only when a report skill will embed the chart): also save a
   static matplotlib PNG of the same data (`fig.savefig("Cases by District.png")`) because
   the PDF engine does not run JavaScript. On-screen charts stay Plotly HTML.

5. **Answer.** 2–4 lines naming the top values. Tell the officer the interactive chart is
   attached below. Do not restate the whole table in prose.

## Hard rules
- Output a `.html` (Plotly). If plotly errors, fix and re-run; do not degrade to text.
- File names use spaces: `Cases by District.html`, never `cases_by_district.html`.
- Cap categories at ~15 (top-N).
- One clear figure per request unless asked otherwise.

## UI expectations
- An interactive HTML artifact opens in the artifact drawer (hover/zoom/pan).
- Optionally a small markdown table in the answer for exact numbers.
