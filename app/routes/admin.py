"""
Admin dashboard — protected by HTTP Basic Auth.
Set ADMIN_USER and ADMIN_PASSWORD in .env before deploying.
"""

import os
import secrets
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.jobs import list_jobs

router   = APIRouter(prefix="/admin")
security = HTTPBasic()

ADMIN_USER     = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if not ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured. Set ADMIN_USER and ADMIN_PASSWORD in .env.",
        )
    # Constant-time comparison to prevent timing attacks
    user_ok = secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/", response_class=HTMLResponse)
async def dashboard(admin: str = Depends(require_admin)):
    jobs = sorted(list_jobs(), key=lambda j: j.created_at, reverse=True)

    rows = ""
    for j in jobs:
        color = {
            "queued":  "#718096",
            "running": "#3182ce",
            "done":    "#38a169",
            "failed":  "#e53e3e",
        }.get(j.status, "#718096")
        file_name = j.pdf_path.split("/")[-1]
        created   = j.created_at[:19]
        completed = j.completed_at[:19] if j.completed_at else "—"
        check     = "✓" if j.check_report and j.check_report.get("failed", 1) == 0 else ("✗" if j.check_report else "—")
        rows += f"""
        <tr>
          <td style="font-family:monospace;font-size:.8rem">{j.id[:8]}…</td>
          <td>{file_name}</td>
          <td><span style="color:{color};font-weight:600">{j.status}</span></td>
          <td>{j.progress}%</td>
          <td>{j.current_page}/{j.total_pages}</td>
          <td style="font-size:.8rem">{created}</td>
          <td style="font-size:.8rem">{completed}</td>
          <td>{check}</td>
        </tr>"""

    empty = '<tr><td colspan="8" style="text-align:center;color:#a0aec0;padding:2rem">No jobs yet</td></tr>'
    return f"""<!DOCTYPE html>
<html><head><title>AccessiFix Admin</title>
<style>
  body{{font-family:system-ui;padding:2rem;background:#f7fafc}}
  h1{{color:#2b6cb0;margin-bottom:1.5rem}}
  table{{width:100%;border-collapse:collapse;background:white;border-radius:8px;overflow:hidden;box-shadow:0 1px 6px rgba(0,0,0,.08)}}
  th{{background:#edf2f7;padding:.6rem 1rem;text-align:left;font-size:.8rem;color:#4a5568}}
  td{{padding:.6rem 1rem;border-top:1px solid #edf2f7;font-size:.85rem}}
  tr:hover td{{background:#f7fafc}}
  .badge{{display:inline-block;padding:.1rem .5rem;border-radius:4px;font-size:.75rem;background:#e2e8f0;color:#4a5568}}
</style>
<meta http-equiv="refresh" content="10">
</head><body>
<h1>AccessiFix — Admin Dashboard <span class="badge">{admin}</span></h1>
<p style="color:#718096;margin-bottom:1rem">{len(jobs)} total jobs · auto-refreshes every 10s</p>
<table>
  <thead><tr>
    <th>Job ID</th><th>File</th><th>Status</th><th>Progress</th>
    <th>Pages</th><th>Created</th><th>Completed</th><th>Check</th>
  </tr></thead>
  <tbody>{rows if rows else empty}</tbody>
</table>
</body></html>"""
