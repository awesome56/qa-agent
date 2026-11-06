from pathlib import Path
from datetime import datetime, date
from typing import List
from jinja2 import Template
from app.models import TestResult
from app.config import REPORTS

HTML_TEMPLATE = Template("""
<!doctype html>
<html>
<head>
<meta charset="utf-8"><title>QA Daily Report {{ date }}</title>
<style>
 body{font-family:system-ui, sans-serif; max-width:900px; margin:40px auto; padding:0 20px}
 h1{border-bottom:2px solid #ff0055}
 .badge{display:inline-block; padding:2px 8px; border-radius:12px; color:#fff; font-size:12px}
 .pass{background:#16a34a} .fail{background:#dc2626} .run{background:#f59e0b}
 table{width:100%; border-collapse:collapse; margin-top:16px}
 th,td{border:1px solid #ddd; padding:8px; text-align:left; font-size:14px}
 th{background:#f8fafc}
 video{max-width:320px}
 small{color:#64748b}
</style>
</head>
<body>
<h1>QA Daily Report — {{ date }}</h1>
<p><small>Generated {{ now }} | Total {{ results|length }} | Passed {{ passed }} | Failed {{ failed }}</small></p>
<table>
<tr><th>ID</th><th>Target</th><th>Scenario</th><th>Status</th><th>p95</th><th>Checks</th><th>Video</th></tr>
{% for r in results %}
<tr>
<td><code>{{ r.id }}</code></td>
<td>{{ r.request.target_url }}</td>
<td>{{ r.request.scenario }}</td>
<td><span class="badge {{ 'pass' if r.status=='passed' else 'fail' if r.status=='failed' else 'run' }}">{{ r.status }}</span></td>
<td>{{ r.k6_summary.metrics.http_req_duration.p95 if r.k6_summary and r.k6_summary.metrics else '-' }}</td>
<td>{{ r.k6_summary.checks_passed if r.k6_summary else '-' }}/{{ r.k6_summary.checks_total if r.k6_summary else '-' }}</td>
<td>{% if r.video_path %}<a href="file://{{ r.video_path }}">video</a>{% else %}-{% endif %}</td>
</tr>
{% endfor %}
</table>
<h2>Highlights</h2>
<ul>
{% for r in results %}
<li><b>{{ r.id }}</b> — buttons highlighted: {{ r.playwright_summary.button_stats if r.playwright_summary else '-' }} | log tail: <code>{{ r.logs[-1] if r.logs else '' }}</code></li>
{% endfor %}
</ul>
</body>
</html>
""")

def _html_to_pdf_bytes(html: str) -> bytes:
    """Generate PDF bytes from HTML via fpdf2 — handles unicode via replacement."""
    try:
        from fpdf import FPDF
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)[:15000]
        # replace unicode that Helvetica can't handle
        text = text.replace("—", "-").replace("–", "-").replace("•", "-").replace("·", "-").replace("’", "'").replace("“", '"').replace("”", '"')
        # encode to latin1 fallback
        text = text.encode('latin-1', 'replace').decode('latin-1')
        pdf = FPDF(format='A4')
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, "QA Daily Report", new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(4)
        pdf.set_font("Helvetica", size=9)
        for chunk in [text[i:i+120] for i in range(0, len(text), 120)]:
            # ensure chunk is latin1 safe
            chunk = chunk.encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 5, chunk, new_x="LMARGIN", new_y="NEXT")
        return pdf.output()
    except Exception as e:
        print(f"[reporter] pdf error: {e}")
        return b""

def build_daily_report(results: List[TestResult], report_date: date) -> Path:
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    html = HTML_TEMPLATE.render(
        date=report_date.isoformat(),
        now=datetime.utcnow().isoformat(),
        results=results,
        passed=passed,
        failed=failed,
    )
    out = REPORTS / f"{report_date.isoformat()}.html"
    out.write_text(html)
    import json
    j = REPORTS / f"{report_date.isoformat()}.json"
    j.write_text(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    # pdf
    pdf_bytes = _html_to_pdf_bytes(html)
    if pdf_bytes:
        (REPORTS / f"{report_date.isoformat()}.pdf").write_bytes(pdf_bytes)
    # also upload to R2 with timestamp folder for daily
    try:
        from app.services.r2 import upload_file, upload_bytes
        from datetime import datetime as dt
        ts = dt.utcnow().strftime("%H-%M-%S")
        # use first result's project or "mixed"
        proj = results[0].request.project if results else "mixed"
        proj = str(proj).replace("ProjectType.","")
        base = f"reports/{proj}/{report_date.isoformat()}/{ts}"
        upload_file(out, f"{base}/report.html", "text/html")
        upload_file(j, f"{base}/report.json", "application/json")
        if pdf_bytes:
            upload_bytes(pdf_bytes, f"{base}/report.pdf", "application/pdf")
        print(f"[reporter] daily uploaded to R2 {base}/")
    except Exception as e:
        print(f"[reporter] R2 daily upload skip: {e}")
    return out

def build_single_report(result) -> dict:
    """Per-test report folder with timestamp — called when single run finishes"""
    from datetime import datetime as dt
    import json
    ts_folder = dt.utcnow().strftime("%Y-%m-%d/%H-%M-%S")
    proj = str(result.request.project).replace("ProjectType.","") if hasattr(result.request, 'project') else "other"
    base = f"reports/{proj}/{ts_folder}/{result.id}"
    html = HTML_TEMPLATE.render(date=ts_folder, now=dt.utcnow().isoformat(), results=[result], passed=1 if result.status=="passed" else 0, failed=1 if result.status=="failed" else 0)
    pdf_bytes = _html_to_pdf_bytes(html)
    # local
    local_dir = REPORTS / proj / ts_folder / result.id
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "report.html").write_text(html)
    (local_dir / "report.json").write_text(json.dumps(result.model_dump(mode="json"), indent=2))
    if pdf_bytes:
        (local_dir / "report.pdf").write_bytes(pdf_bytes)
    # R2 upload — html/pdf/json + video/trace if exists
    r2_urls = {}
    try:
        from app.services.r2 import upload_file, upload_bytes
        from pathlib import Path as _P
        r2_urls["html"] = upload_file(local_dir / "report.html", f"{base}/report.html", "text/html")
        r2_urls["json"] = upload_file(local_dir / "report.json", f"{base}/report.json", "application/json")
        if pdf_bytes:
            r2_urls["pdf"] = upload_bytes(pdf_bytes, f"{base}/report.pdf", "application/pdf")
        if result.video_path and _P(result.video_path).exists():
            # video may be a dir (playwright saves under dir) — find .webm
            vp = _P(result.video_path)
            if vp.is_dir():
                vids = list(vp.glob("*.webm"))
                if vids: vp = vids[0]
            if vp.exists() and vp.is_file():
                r2_urls["video"] = upload_file(vp, f"{base}/video.webm", "video/webm")
        if result.trace_path and _P(result.trace_path).exists():
            r2_urls["trace"] = upload_file(_P(result.trace_path), f"{base}/trace.zip", "application/zip")
        print(f"[reporter] single {result.id} uploaded to R2 {base}/")
    except Exception as e:
        print(f"[reporter] R2 single upload skip: {e}")
    return {"local_dir": str(local_dir), "r2_base": base, "r2_urls": r2_urls, "pdf_bytes": len(pdf_bytes) if pdf_bytes else 0}
