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
    # also json
    import json
    j = REPORTS / f"{report_date.isoformat()}.json"
    j.write_text(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    return out
