"""
compare_transcripts.py
Generates:
  - compare_report.html  : side-by-side transcript viewer
  - compare_metrics.xlsx : metrics summary + full transcripts
"""

import json, os, sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))

# Optional tag arg: python compare_transcripts.py 2026-05-26
# Defaults to the original batch (no suffix)
tag = sys.argv[1] if len(sys.argv) > 1 else None
suffix = f"_{tag}" if tag else ""

DG_JSON  = os.path.join(HERE, f"deepgram_results{suffix}.json")
TR_JSON  = os.path.join(HERE, f"transcribe_results{suffix}.json")
HTML_OUT = os.path.join(HERE, f"compare_report{suffix}.html")
XLSX_OUT = os.path.join(HERE, f"compare_metrics{suffix}.xlsx")

# ── Load data ────────────────────────────────────────────────────────────────

with open(DG_JSON) as f:
    dg_list = json.load(f)
with open(TR_JSON) as f:
    tr_list = json.load(f)

dg = {r["file"]: r for r in dg_list}
tr = {r["file"]: r for r in tr_list}
files = sorted(dg.keys())


def dg_speakers(result):
    utterances = result.get("utterances", [])
    return len(set(u.get("speaker") for u in utterances if "speaker" in u))


def dg_avg_confidence(result):
    utterances = result.get("utterances", [])
    confs = [u.get("confidence", 0) for u in utterances if "confidence" in u]
    return round(sum(confs) / len(confs), 3) if confs else None


def tr_speakers(result):
    return len(result.get("speakers_detected", []))


# ── Build rows ───────────────────────────────────────────────────────────────

rows = []
for fname in files:
    d = dg.get(fname, {})
    t = tr.get(fname, {})
    rows.append({
        "file":              fname,
        "short":             fname[:8],
        "dg_words":          d.get("word_count", 0),
        "tr_words":          t.get("word_count", 0),
        "word_diff":         t.get("word_count", 0) - d.get("word_count", 0),
        "dg_latency":        d.get("latency_seconds", 0),
        "tr_latency":        t.get("latency_seconds", 0),
        "latency_diff":      round(t.get("latency_seconds", 0) - d.get("latency_seconds", 0), 2),
        "dg_speakers":       dg_speakers(d),
        "tr_speakers":       tr_speakers(t),
        "dg_confidence":     dg_avg_confidence(d),
        "dg_transcript":     d.get("transcript", "ERROR"),
        "tr_transcript":     t.get("transcript", t.get("error", "ERROR")),
    })

# ── HTML report ──────────────────────────────────────────────────────────────

def build_html(rows):
    cards = []
    for r in rows:
        word_color = "#c0392b" if abs(r["word_diff"]) > 30 else "#27ae60"
        lat_color  = "#c0392b" if r["tr_latency"] > r["dg_latency"] * 2 else "#27ae60"
        card = f"""
        <div class="card">
          <div class="card-header">
            <span class="fname">{r['file']}</span>
            <span class="badge" style="background:#2980b9">DG {r['dg_latency']}s</span>
            <span class="badge" style="background:#8e44ad">TR {r['tr_latency']}s</span>
            <span class="badge" style="background:{lat_color}">Δlat {r['latency_diff']:+.1f}s</span>
            <span class="badge" style="background:#7f8c8d">DG {r['dg_words']}w</span>
            <span class="badge" style="background:#7f8c8d">TR {r['tr_words']}w</span>
            <span class="badge" style="background:{word_color}">Δwords {r['word_diff']:+d}</span>
            <span class="badge" style="background:#16a085">DG spk:{r['dg_speakers']}</span>
            <span class="badge" style="background:#d35400">TR spk:{r['tr_speakers']}</span>
          </div>
          <div class="transcripts">
            <div class="col">
              <div class="col-label deepgram">Deepgram</div>
              <div class="text">{r['dg_transcript']}</div>
            </div>
            <div class="col">
              <div class="col-label transcribe">AWS Transcribe</div>
              <div class="text">{r['tr_transcript']}</div>
            </div>
          </div>
        </div>"""
        cards.append(card)

    avg_dg_lat = sum(r["dg_latency"] for r in rows) / len(rows)
    avg_tr_lat = sum(r["tr_latency"] for r in rows) / len(rows)
    avg_dg_w   = sum(r["dg_words"]   for r in rows) / len(rows)
    avg_tr_w   = sum(r["tr_words"]   for r in rows) / len(rows)

    summary = f"""
    <div class="summary">
      <h2>Summary — {len(rows)} files</h2>
      <table>
        <tr><th></th><th>Deepgram</th><th>AWS Transcribe</th><th>Winner</th></tr>
        <tr><td>Avg latency</td><td>{avg_dg_lat:.1f}s</td><td>{avg_tr_lat:.1f}s</td>
            <td>{'🟢 Deepgram' if avg_dg_lat < avg_tr_lat else '🟢 Transcribe'}</td></tr>
        <tr><td>Avg words</td><td>{avg_dg_w:.0f}</td><td>{avg_tr_w:.0f}</td>
            <td>{'more words → TR' if avg_tr_w > avg_dg_w else 'more words → DG'}</td></tr>
        <tr><td>Success rate</td><td>{len(rows)}/{len(rows)}</td><td>{len(rows)}/{len(rows)}</td><td>🟡 Tie</td></tr>
      </table>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Transcriber Benchmark Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f5f6fa; margin: 0; padding: 20px; color: #2c3e50; }}
  h1   {{ text-align: center; color: #2c3e50; }}
  .summary {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 24px;
              box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
  .summary table {{ border-collapse: collapse; width: 100%; }}
  .summary th, .summary td {{ padding: 8px 16px; border: 1px solid #ddd; text-align: left; }}
  .summary th {{ background: #ecf0f1; }}
  .card {{ background: white; border-radius: 8px; margin-bottom: 24px;
           box-shadow: 0 2px 8px rgba(0,0,0,.08); overflow: hidden; }}
  .card-header {{ background: #2c3e50; padding: 12px 16px; display: flex;
                  flex-wrap: wrap; gap: 6px; align-items: center; }}
  .fname {{ color: white; font-family: monospace; font-size: 13px; margin-right: 8px; }}
  .badge {{ color: white; font-size: 11px; padding: 2px 8px; border-radius: 12px;
            font-weight: 600; }}
  .transcripts {{ display: grid; grid-template-columns: 1fr 1fr; }}
  .col {{ padding: 16px; }}
  .col:first-child {{ border-right: 1px solid #ecf0f1; }}
  .col-label {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                letter-spacing: 1px; margin-bottom: 8px; }}
  .deepgram   {{ color: #2980b9; }}
  .transcribe {{ color: #8e44ad; }}
  .text {{ font-size: 14px; line-height: 1.7; color: #34495e; white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>Transcriber Benchmark — Deepgram vs AWS Transcribe</h1>
{summary}
{''.join(cards)}
</body>
</html>"""


html = build_html(rows)
with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"✅ HTML report → {HTML_OUT}")


# ── Excel report ─────────────────────────────────────────────────────────────

try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    # ── Sheet 1: Metrics ─────────────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Metrics"

    header_fill = PatternFill("solid", fgColor="2C3E50")
    dg_fill     = PatternFill("solid", fgColor="D6EAF8")
    tr_fill     = PatternFill("solid", fgColor="E8DAEF")
    good_fill   = PatternFill("solid", fgColor="D5F5E3")
    bad_fill    = PatternFill("solid", fgColor="FADBD8")

    headers = [
        "File (short)", "Full filename",
        "DG latency (s)", "TR latency (s)", "Latency diff (s)",
        "DG words", "TR words", "Word diff",
        "DG speakers", "TR speakers",
        "DG avg confidence",
    ]
    ws1.append(headers)
    for col, _ in enumerate(headers, 1):
        cell = ws1.cell(1, col)
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")

    for r in rows:
        row = [
            r["short"], r["file"],
            r["dg_latency"], r["tr_latency"], r["latency_diff"],
            r["dg_words"], r["tr_words"], r["word_diff"],
            r["dg_speakers"], r["tr_speakers"],
            r["dg_confidence"],
        ]
        ws1.append(row)
        ri = ws1.max_row
        # Colour latency diff
        ld_cell = ws1.cell(ri, 5)
        ld_cell.fill = good_fill if r["latency_diff"] < 0 else bad_fill
        # Colour word diff
        wd_cell = ws1.cell(ri, 8)
        wd_cell.fill = good_fill if abs(r["word_diff"]) <= 20 else bad_fill
        # Light fill for DG / TR columns
        for c in [3, 6, 9, 11]:
            ws1.cell(ri, c).fill = dg_fill
        for c in [4, 7, 10]:
            ws1.cell(ri, c).fill = tr_fill

    # Averages row
    ws1.append([
        "AVERAGE", "",
        round(sum(r["dg_latency"] for r in rows)/len(rows), 2),
        round(sum(r["tr_latency"] for r in rows)/len(rows), 2),
        round(sum(r["latency_diff"] for r in rows)/len(rows), 2),
        round(sum(r["dg_words"] for r in rows)/len(rows)),
        round(sum(r["tr_words"] for r in rows)/len(rows)),
        round(sum(r["word_diff"] for r in rows)/len(rows)),
        "", "", "",
    ])
    avg_row = ws1.max_row
    for c in range(1, len(headers)+1):
        ws1.cell(avg_row, c).font = Font(bold=True)
        ws1.cell(avg_row, c).fill = PatternFill("solid", fgColor="F0F3F4")

    # Column widths
    col_widths = [12, 42, 14, 14, 14, 10, 10, 10, 12, 12, 18]
    for i, w in enumerate(col_widths, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w

    # ── Sheet 2: Transcripts ─────────────────────────────────────────────────
    ws2 = wb.create_sheet("Transcripts")
    t_headers = ["File", "DG words", "TR words", "Word diff",
                 "DG latency (s)", "TR latency (s)", "Deepgram transcript", "AWS Transcribe transcript"]
    ws2.append(t_headers)
    for col, _ in enumerate(t_headers, 1):
        cell = ws2.cell(1, col)
        cell.fill = header_fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center")

    for r in rows:
        ws2.append([
            r["file"],
            r["dg_words"], r["tr_words"], r["word_diff"],
            r["dg_latency"], r["tr_latency"],
            r["dg_transcript"], r["tr_transcript"],
        ])
        ri = ws2.max_row
        ws2.cell(ri, 7).fill = dg_fill
        ws2.cell(ri, 8).fill = tr_fill
        for c in [7, 8]:
            ws2.cell(ri, c).alignment = Alignment(wrap_text=True, vertical="top")
        ws2.row_dimensions[ri].height = 120

    t_widths = [42, 10, 10, 10, 14, 14, 60, 60]
    for i, w in enumerate(t_widths, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    ws2.row_dimensions[1].height = 20

    wb.save(XLSX_OUT)
    print(f"✅ Excel report  → {XLSX_OUT}")

except ImportError:
    print("⚠️  openpyxl not installed. Run: pip install openpyxl")
    print("   Excel export skipped.")
