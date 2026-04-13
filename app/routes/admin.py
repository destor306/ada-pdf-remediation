"""
Minimal admin dashboard — view all jobs and their status.
No auth in MVP; add HTTP Basic Auth before exposing publicly.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from app.jobs import list_jobs

router = APIRouter(prefix="/admin")


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    jobs = sorted(list_jobs(), key=lambda j: j.created_at, reverse=True)

    rows = ""
    for j in jobs:
        color = {"queued": "#718096", "running": "#3182ce", "done": "#38a169", "failed": "#e53e3e"}.get(j.status, "#718096")
        rows += f"""
        <tr>
          <td style="font-family:monospace;font-size:0.8rem">{j.id[:8]}…</td>
          <td>{j.pdf_path.split('/')[-1]}</td>
          <td><span style="color:{color};font-weight:600">{j.status}</span></td>
          <td>{j.progress}%</td>
          <td>{j.current_page}/{j.total_pages}</td>
          <td style="font-size:0.8rem">{j.created_at[:19]}</td>
          <td style="font-size:0.8rem">{j.completed_at[:19] if j.completed_at else '—'}</td>
          <td>{"✓" if j.check_report and j.check_report.get("failed", 1) == 0 else ("✗" if j.check_report else "—")}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html><head><title>ADA Admin</title>
<style>
  body{{font-family:system-ui;padding:2rem;background:#f7fafc}}
  h1{{color:#2b6cb0;margin-bottom:1.5rem}}
  table{{width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;box-shadow:0 1px 6px rgba(0,0,0,.08)}}
  th{{background:#edf2f7;padding:.6rem 1rem;text-align:left;font-size:.8rem;color:#4a5568}}
  td{{padding:.6rem 1rem;border-top:1px solid #edf2f7;font-size:.85rem}}
  tr:hover td{{background:#f7fafc}}
</style>
<meta http-equiv="refresh" content="5">
</head><body>
<h1>ADA Remediation — Job Dashboard</h1>
<p style="color:#718096;margin-bottom:1rem">{len(jobs)} total jobs · auto-refreshes every 5s</p>
<table>
  <thead><tr>
    <th>ID</th><th>File</th><th>Status</th><th>Progress</th>
    <th>Pages</th><th>Created</th><th>Completed</th><th>Check</th>
  </tr></thead>
  <tbody>{rows if rows else '<tr><td colspan="8" style="text-align:center;color:#a0aec0;padding:2rem">No jobs yet</td></tr>'}</tbody>
</table>
</body></html>"""
