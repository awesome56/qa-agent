from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.models import ProjectType, TestScope

router = APIRouter(tags=["intake"])

INTAKE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>QA Intake — qa.awesometech.com.ng</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:system-ui,sans-serif;max-width:780px;margin:24px auto;padding:0 16px}
 h1{border-bottom:3px solid #ff0055;padding-bottom:8px}
 label{display:block;margin:10px 0 4px;font-weight:600}
 input,select,textarea{width:100%;padding:8px;border:1px solid #ccc;border-radius:6px}
 textarea{height:80px}
 .row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
 .hint{color:#64748b;font-size:12px}
 button{background:#ff0055;color:#fff;border:none;padding:10px 18px;border-radius:8px;cursor:pointer;font-weight:700}
 button:disabled{opacity:.5}
 #log{white-space:pre-wrap;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;max-height:360px;overflow:auto;font:12px/1.4 monospace}
 .badge{padding:2px 8px;border-radius:12px;color:#fff;font-size:12px}
</style>
</head><body>
<h1>QA Intake — Universal</h1>
<p class="hint">Project: hrms-new, aperte, examco, power, phonestation, awesometech, other. Feeds <code>POST /api/v1/test/run</code> with auth + scope. Video + trace + k6 + edge cases via muse-spark-1.2.</p>
<form id="f">
 <label>Project <select name="project" id="project">
  <option value="hrms-new">hrms-new (https://hrms.awesometech.com.ng)</option>
  <option value="aperte">aperte</option>
  <option value="examco">examco</option>
  <option value="power">power</option>
  <option value="phonestation">phonestation</option>
  <option value="awesometech">awesometech</option>
  <option value="other" selected>other</option>
 </select></label>
 <label>Target URL <input name="target_url" placeholder="https://hrms.awesometech.com.ng/leave" required></label>
 <label>Feature / Bug description <textarea name="scenario" placeholder="cannot approve expired leave"></textarea></label>
 <label>Scope
  <select name="scope">
   <option value="feature" selected>feature — just verify</option>
   <option value="test_cases">test_cases</option>
   <option value="edge_cases">edge_cases (muse-spark-1.2)</option>
   <option value="load">load</option>
   <option value="stress">stress</option>
   <option value="all">all</option>
  </select>
 </label>
 <div class="row">
  <div><label>Login URL <input name="login_url" placeholder="https://hrms.awesometech.com.ng/login"></label></div>
  <div><label>VUs / Duration <div class="row"><input name="vus" value="10"><input name="duration" value="30s"></div></label></div>
 </div>
 <div class="row">
  <div><label>Username <input name="username" autocomplete="username"></label></div>
  <div><label>Password <input name="password" type="password" autocomplete="current-password"></label></div>
 </div>
 <div class="row">
  <div><label>Admin username (to grant permission) <input name="admin_username"></label></div>
  <div><label>Admin password <input name="admin_password" type="password"></label></div>
 </div>
 <label>Permission feature (e.g. leave_approval) <input name="permission_feature"></label>
 <p><button type="submit" id="btn">Run QA</button> <a href="/api/v1/reports/daily/today" target="_blank">Daily report</a> | <a href="/docs" target="_blank">API docs</a></p>
</form>
<div id="log"></div>
<script>
const f=document.getElementById('f'), log=document.getElementById('log'), btn=document.getElementById('btn');
const projectDefaults={ 'hrms-new':'https://hrms.awesometech.com.ng','aperte':'https://aparte.awesometech.com.ng','examco':'https://examco.awesometech.com.ng','power':'https://power.awesometech.com.ng','phonestation':'https://phonestation.awesometech.com.ng','awesometech':'https://awesometech.com.ng' };
document.getElementById('project').addEventListener('change', e=>{
  const v=e.target.value;
  if(projectDefaults[v] && !f.target_url.value) f.target_url.value=projectDefaults[v];
  if(v==='hrms-new' && !f.login_url.value) f.login_url.value=projectDefaults[v]+'/login';
});
function append(m){ log.textContent += m+"\\n"; log.scrollTop=log.scrollHeight; }
f.addEventListener('submit', async e=>{
  e.preventDefault(); btn.disabled=true; log.textContent='';
  const fd=new FormData(f);
  const body={
    project: fd.get('project'),
    target_url: fd.get('target_url'),
    scenario: fd.get('scenario')||'smoke',
    scope: fd.get('scope'),
    vus: parseInt(fd.get('vus')||10),
    duration: fd.get('duration')||'30s',
    record_video:true, highlight_buttons:true,
    auth:{}
  };
  if(fd.get('login_url')) body.auth.login_url=fd.get('login_url');
  if(fd.get('username')) body.auth.username=fd.get('username');
  if(fd.get('password')) body.auth.password=fd.get('password');
  if(fd.get('admin_username')) body.auth.admin_username=fd.get('admin_username');
  if(fd.get('admin_password')) body.auth.admin_password=fd.get('admin_password');
  if(fd.get('permission_feature')) body.auth.permission_feature=fd.get('permission_feature');
  if(Object.keys(body.auth).length===0) delete body.auth;
  append('POST /api/v1/test/run '+JSON.stringify({...body, auth: body.auth?{...body.auth,password:'***',admin_password:body.auth.admin_password?'***':undefined}:undefined},null,2));
  const r=await fetch('/api/v1/test/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json();
  if(!r.ok){ append('ERROR '+JSON.stringify(j)); btn.disabled=false; return; }
  append('queued id='+j.id+' stream='+j.stream);
  const es=new EventSource(j.stream);
  es.addEventListener('need_auth', ev=>{ append('NEED_AUTH '+ev.data+' — provide username/password'); });
  es.addEventListener('need_admin', ev=>{ append('NEED_ADMIN '+ev.data+' — provide admin login'); });
  es.addEventListener('log', ev=> append('[log] '+JSON.parse(ev.data).msg));
  es.addEventListener('phase', ev=> append('[phase] '+ev.data));
  es.addEventListener('edge_cases', ev=> append('[edge] '+ev.data));
  es.addEventListener('status', ev=> append('[status] '+ev.data));
  es.addEventListener('done', ev=>{ append('[done] '+ev.data); es.close(); btn.disabled=false; append('Report: /api/v1/reports/daily/today'); });
  es.onerror=()=>{ append('SSE error/closed'); es.close(); btn.disabled=false; };
});
</script>
</body></html>
"""

@router.get("/intake", response_class=HTMLResponse)
async def intake_page():
    return INTAKE_HTML
