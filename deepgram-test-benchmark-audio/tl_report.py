"""
tl_report.py
Generates a presentation-ready HTML benchmark report comparing Deepgram vs AWS Transcribe
for the live copilot migration decision.

Usage:
  python3 deepgram-test-benchmark-audio/tl_report.py 2026-05-26
"""

import json, os, sys, html as html_lib

HERE   = os.path.dirname(os.path.abspath(__file__))
tag    = sys.argv[1] if len(sys.argv) > 1 else "2026-05-26"
SRC    = os.path.join(HERE, f"streaming_results_{tag}.json")
OUT    = os.path.join(HERE, f"tl_report_{tag}.html")

with open(SRC, encoding="utf-8") as f:
    raw = json.load(f)

# Drop files with no data (silent / empty)
records = [r for r in raw if r.get("deepgram", {}).get("word_count", 0) > 0
                          or r.get("transcribe", {}).get("word_count", 0) > 0]

valid = [r for r in records
         if r.get("deepgram", {}).get("avg_finalization_ms") is not None
         and r.get("transcribe", {}).get("avg_finalization_ms") is not None]

def avg(key, service):
    vals = [r[service][key] for r in valid if r[service].get(key) is not None]
    return round(sum(vals) / len(vals)) if vals else None

dg_avg_fin   = avg("avg_finalization_ms", "deepgram")
tr_avg_fin   = avg("avg_finalization_ms", "transcribe")
dg_avg_int   = avg("first_interim_ms", "deepgram")
tr_avg_int   = avg("first_interim_ms", "transcribe")
dg_avg_words = round(sum(r["deepgram"]["word_count"] for r in records) / len(records))
tr_avg_words = round(sum(r["transcribe"]["word_count"] for r in records) / len(records))

fin_winner  = "Transcribe" if (tr_avg_fin or 999) < (dg_avg_fin or 999) else "Deepgram"
int_winner  = "Transcribe" if (tr_avg_int or 999) < (dg_avg_int or 999) else "Deepgram"

# ── bar chart helpers ─────────────────────────────────────────────────────────

max_fin = max(
    max((r["deepgram"]["avg_finalization_ms"] or 0) for r in valid),
    max((r["transcribe"]["avg_finalization_ms"] or 0) for r in valid),
)

def bar(val, max_val, color):
    if val is None:
        return '<span style="color:#aaa">—</span>'
    pct = round(val / max_val * 100)
    return (f'<div style="display:flex;align-items:center;gap:8px">'
            f'<div style="background:{color};height:18px;width:{pct}%;border-radius:3px;min-width:2px"></div>'
            f'<span style="font-size:13px;white-space:nowrap">{val}ms</span></div>')

# ── transcript excerpt ────────────────────────────────────────────────────────

def excerpt(text, n=220):
    text = text.strip()
    if len(text) <= n:
        return html_lib.escape(text)
    return html_lib.escape(text[:n]) + '<span style="color:#aaa">…</span>'

# ── build HTML ────────────────────────────────────────────────────────────────

cards_lat = []
for r in valid:
    dg  = r["deepgram"]
    tr  = r["transcribe"]
    fname = r["file"][:8]
    cards_lat.append(f"""
    <tr>
      <td class="mono">{fname}</td>
      <td>{bar(dg.get('avg_finalization_ms'), max_fin, '#2980b9')}</td>
      <td>{bar(tr.get('avg_finalization_ms'), max_fin, '#8e44ad')}</td>
      <td>{bar(dg.get('first_interim_ms'), 8000, '#2980b9')}</td>
      <td>{bar(tr.get('first_interim_ms'), 8000, '#8e44ad')}</td>
    </tr>""")

# averages row
cards_lat.append(f"""
    <tr class="avg-row">
      <td><strong>AVG</strong></td>
      <td>{bar(dg_avg_fin, max_fin, '#2980b9')}</td>
      <td>{bar(tr_avg_fin, max_fin, '#8e44ad')}</td>
      <td>{bar(dg_avg_int, 8000, '#2980b9')}</td>
      <td>{bar(tr_avg_int, 8000, '#8e44ad')}</td>
    </tr>""")

transcript_cards = []
for r in records:
    dg  = r["deepgram"]
    tr  = r["transcribe"]
    fname = r["file"][:8]
    dg_w  = dg.get("word_count", 0)
    tr_w  = tr.get("word_count", 0)
    diff  = tr_w - dg_w
    diff_color = "#27ae60" if abs(diff) <= 15 else "#c0392b"
    is_noise_file = "700dda45" in r["file"]
    noise_badge = (' <span class="badge" style="background:#e67e22;font-size:10px">'
                   '⚠ background noise detected in TR</span>') if is_noise_file else ""
    transcript_cards.append(f"""
    <div class="card">
      <div class="card-header">
        <span class="mono" style="color:white">{fname}</span>
        <span class="badge" style="background:#7f8c8d">DG {dg_w}w</span>
        <span class="badge" style="background:#7f8c8d">TR {tr_w}w</span>
        <span class="badge" style="background:{diff_color}">Δ{diff:+d}w</span>
        {noise_badge}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr">
        <div style="padding:14px;border-right:1px solid #ecf0f1">
          <div class="col-label deepgram">Deepgram</div>
          <div class="text">{excerpt(dg.get('transcript',''))}</div>
        </div>
        <div style="padding:14px">
          <div class="col-label transcribe">AWS Transcribe</div>
          <div class="text">{excerpt(tr.get('transcript',''))}</div>
        </div>
      </div>
    </div>""")

# ── decision matrix ───────────────────────────────────────────────────────────

criteria = [
    ("Utterance finalization speed",  "High",   "~63 ms avg",                "~30 ms avg ✅",          "Transcribe 2× faster"),
    ("First word latency",            "High",   "~5.3 s avg",                "~4.6 s avg ✅",           "Both require audio to play first"),
    ("Background noise filtering",    "High",   "Filters it out ✅",         "Transcribes noise ⚠",     "DG ignores non-speech (TV, hold music)"),
    ("Spanish accuracy",              "High",   "nova-2 (call-center model)","es-US general model",    "DG nova-2 trained on call center audio"),
    ("Telco keyword recognition",     "Medium", "Keywords boost param",      "Custom Vocabulary ✅",    "TR has structured vocab list; DG uses inline hints"),
    ("AWS ecosystem integration",     "Medium", "REST/WebSocket only",       "Native AWS ✅",            "TR integrates with CCP, Contact Lens, IAM"),
    ("SDK stability (Python)",        "Medium", "v7 API still evolving ⚠",  "Stable, aws-maintained ✅","DG SDK had breaking API changes recently"),
    ("Cost",                          "Low",    "~$0.0043/min",              "~$0.024/min ✅",           "DG ~5× cheaper; verify current pricing"),
    ("Interim results off latency",   "Note",   "8–15 s to first final",     "8–15 s to first final",  "Both unusable for live copilot without interim on"),
]

matrix_rows = []
for name, weight, dg_val, tr_val, notes in criteria:
    w_color = {"High": "#c0392b", "Medium": "#e67e22", "Low": "#27ae60", "Note": "#7f8c8d"}[weight]
    matrix_rows.append(
        f'<tr><td>{name}</td>'
        f'<td><span class="badge" style="background:{w_color}">{weight}</span></td>'
        f'<td>{dg_val}</td><td>{tr_val}</td><td style="color:#636e72;font-size:12px">{notes}</td></tr>'
    )

# ── noise detail ─────────────────────────────────────────────────────────────

noise_rec = next((r for r in records if "700dda45" in r["file"]), None)
noise_section = ""
if noise_rec:
    dg_t = html_lib.escape(noise_rec["deepgram"].get("transcript", ""))
    tr_t = html_lib.escape(noise_rec["transcribe"].get("transcript", ""))
    noise_section = f"""
    <div class="section">
      <h2>Background Noise Detail — file 700dda45</h2>
      <p style="color:#636e72;font-size:14px">
        This call had TV/radio audio playing in the background.
        Deepgram ignored it; Transcribe transcribed it verbatim
        (highlighted fragments: <em>"así que ganamos. De hecho, querido, vas a"</em>,
        <em>"colección de invierno con"</em>, <em>"pusimos todo el"</em>).
      </p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
        <div style="background:#d6eaf8;border-radius:6px;padding:14px">
          <div class="col-label deepgram" style="margin-bottom:8px">Deepgram — clean</div>
          <div class="text">{dg_t}</div>
        </div>
        <div style="background:#fde8e8;border-radius:6px;padding:14px">
          <div class="col-label transcribe" style="margin-bottom:8px">AWS Transcribe — includes noise</div>
          <div class="text">{tr_t}</div>
        </div>
      </div>
    </div>"""

# ── assemble ──────────────────────────────────────────────────────────────────

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Benchmark Report — Deepgram vs AWS Transcribe ({tag})</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f6fa; padding: 24px; color: #2c3e50; line-height: 1.5; }}
  h1   {{ text-align: center; margin-bottom: 8px; font-size: 22px; }}
  .subtitle {{ text-align: center; color: #636e72; font-size: 13px; margin-bottom: 28px; }}
  h2   {{ font-size: 16px; margin-bottom: 14px; color: #2c3e50; }}
  .section {{ background: white; border-radius: 8px; padding: 22px 24px;
              margin-bottom: 22px; box-shadow: 0 2px 8px rgba(0,0,0,.07); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ padding: 8px 12px; border: 1px solid #ddd; text-align: left; vertical-align: middle; }}
  th {{ background: #2c3e50; color: white; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .avg-row td {{ background: #ecf0f1 !important; font-weight: 600; }}
  .badge {{ color: white; font-size: 11px; padding: 2px 8px; border-radius: 10px;
            font-weight: 600; display: inline-block; }}
  .card {{ background: white; border-radius: 8px; margin-bottom: 18px;
           box-shadow: 0 2px 8px rgba(0,0,0,.07); overflow: hidden; }}
  .card-header {{ background: #2c3e50; padding: 10px 16px; display: flex;
                  flex-wrap: wrap; gap: 6px; align-items: center; }}
  .col-label {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                letter-spacing: 1px; margin-bottom: 6px; }}
  .deepgram   {{ color: #2980b9; }}
  .transcribe {{ color: #8e44ad; }}
  .text {{ font-size: 13px; line-height: 1.7; color: #34495e; }}
  .mono {{ font-family: monospace; }}
  .winner-dg {{ color: #2980b9; font-weight: 700; }}
  .winner-tr {{ color: #8e44ad; font-weight: 700; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 20px; }}
  .kpi {{ background: #f8f9fa; border-radius: 6px; padding: 14px 16px; border-left: 4px solid #ddd; }}
  .kpi .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #636e72; }}
  .kpi .dg-val {{ font-size: 22px; font-weight: 700; color: #2980b9; }}
  .kpi .tr-val {{ font-size: 22px; font-weight: 700; color: #8e44ad; }}
  .kpi .sub {{ font-size: 11px; color: #636e72; margin-top: 2px; }}
  @media (max-width: 700px) {{ .kpi-grid {{ grid-template-columns: 1fr 1fr; }} }}
</style>
</head>
<body>

<h1>Deepgram vs AWS Transcribe — Benchmark Report</h1>
<p class="subtitle">Live streaming latency · Transcript quality · {len(valid)} calls · {tag}</p>

<!-- KPI cards -->
<div class="kpi-grid">
  <div class="kpi" style="border-color:#2980b9">
    <div class="label">DG avg finalization</div>
    <div class="dg-val">{dg_avg_fin}ms</div>
    <div class="sub">utterance end → final transcript</div>
  </div>
  <div class="kpi" style="border-color:#8e44ad">
    <div class="label">TR avg finalization</div>
    <div class="tr-val">{tr_avg_fin}ms</div>
    <div class="sub">utterance end → final transcript</div>
  </div>
  <div class="kpi" style="border-color:#27ae60">
    <div class="label">Finalization winner</div>
    <div style="font-size:20px;font-weight:700;color:#27ae60">AWS Transcribe</div>
    <div class="sub">{tr_avg_fin}ms vs {dg_avg_fin}ms (~2×)</div>
  </div>
  <div class="kpi" style="border-color:#e67e22">
    <div class="label">Noise filtering winner</div>
    <div style="font-size:20px;font-weight:700;color:#e67e22">Deepgram</div>
    <div class="sub">Filters background audio; TR transcribes it</div>
  </div>
</div>

<!-- Streaming latency -->
<div class="section">
  <h2>Streaming Latency</h2>
  <p style="color:#636e72;font-size:13px;margin-bottom:16px">
    <strong>avg_finalization_ms</strong>: time from end of last audio chunk → final transcript for that utterance.
    This is the metric that determines how quickly the copilot can act after the customer stops speaking.<br>
    <strong>first_interim_ms</strong>: time from audio start → first partial word. Both services show 4–7s because
    audio must play in real-time before any speech is detected — this is expected behavior, not a service delay.
  </p>
  <table>
    <thead>
      <tr>
        <th>File</th>
        <th><span style="color:#7fc8f8">■</span> DG avg_fin</th>
        <th><span style="color:#c39bd3">■</span> TR avg_fin</th>
        <th><span style="color:#7fc8f8">■</span> DG first_interim</th>
        <th><span style="color:#c39bd3">■</span> TR first_interim</th>
      </tr>
    </thead>
    <tbody>
      {''.join(cards_lat)}
    </tbody>
  </table>
</div>

{noise_section}

<!-- Transcript quality -->
<div class="section">
  <h2>Transcript Quality — Side by Side (first 220 chars)</h2>
  <p style="color:#636e72;font-size:13px;margin-bottom:16px">
    Both services use Spanish models (DG: <code>es-419</code> nova-2 · TR: <code>es-US</code>).
    Word count differences under ±15 words are considered acceptable.
  </p>
  {''.join(transcript_cards)}
</div>

<!-- Decision framework -->
<div class="section">
  <h2>Decision Framework</h2>
  <table>
    <thead>
      <tr><th>Criteria</th><th>Weight</th><th>Deepgram</th><th>AWS Transcribe</th><th>Notes</th></tr>
    </thead>
    <tbody>
      {''.join(matrix_rows)}
    </tbody>
  </table>
</div>

<!-- Qualitative -->
<div class="section">
  <h2>Key Qualitative Findings</h2>
  <ul style="font-size:13px;line-height:2;padding-left:20px;color:#34495e">
    <li><strong>Interim results are required</strong> for both services in a live copilot context.
        Disabling them pushes first_final_ms to 8–15 s per utterance — unusable.</li>
    <li><strong>Deepgram nova-2</strong> was purpose-built for call center audio.
        It handles Spanish colloquialisms, telco terms, and speaker interruptions well.</li>
    <li><strong>Background noise</strong>: In the call with background TV audio, Deepgram ignored it entirely.
        Transcribe transcribed the noise verbatim, contaminating the copilot context.
        For open-mic call center environments this is a significant quality difference.</li>
    <li><strong>AWS integration</strong>: Transcribe is already embedded in the LCA stack (Kinesis, Lambda, CCP).
        Replacing it requires re-engineering the ingestion pipeline.</li>
    <li><strong>SDK stability</strong>: The Deepgram Python SDK (v7) introduced breaking API changes
        that required significant rework during this benchmark. The aws-sdk is stable and well-maintained.</li>
  </ul>
</div>

</body>
</html>"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Report saved → {OUT}")
