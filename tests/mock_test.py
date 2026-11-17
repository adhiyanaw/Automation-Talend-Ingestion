"""Uji deploy.py terhadap server tiruan (Nexus + TAC) di localhost."""
import base64, json, os, subprocess, sys, threading, zipfile, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        if self.path.startswith("/service/rest/v1/components"):
            LOG.append(("nexus", self.path, len(body), b"maven2.artifactId" in body))
            self.send_response(204); self.end_headers(); return
        if self.path.endswith("/metaServlet"):
            req = json.loads(base64.b64decode(body))
            LOG.append(("tac", req))
            res = {"returnCode": 0, "result": 42 if req["actionName"] == "getTaskIdByName" else None}
            out = json.dumps(res).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(out); return
        self.send_response(404); self.end_headers()

srv = HTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

w = ROOT / "tests" / "work"; shutil.rmtree(w, ignore_errors=True); (w / "builds").mkdir(parents=True)
with zipfile.ZipFile(w / "builds" / "ZZ_SAMPLE_PUSH_0.1.zip", "w") as z: z.writestr("a.txt", "x")
(w / "config.yaml").write_text(f"""
tac: {{url: "http://127.0.0.1:{port}/org.talend.administrator", user_env: TU, pass_env: TP, verify_ssl: false}}
nexus: {{url: "http://127.0.0.1:{port}", user_env: NU, pass_env: NP, repository: rel, group_id: org.example.bsim_local}}
defaults: {{execution_server: srv1, context_name: Default}}
""")
(w / "jobs.yaml").write_text("""
jobs:
  - {job_code: ZZ_SAMPLE_PUSH, category: SAMPLE, artifact_id: ZZ_SAMPLE_PUSH, version: "0.1",
     build_zip: builds/ZZ_SAMPLE_PUSH_0.1.zip,
     schedule: {minutes: "30", hours: "2"}}
  - {job_code: OFF, category: A, artifact_id: OFF, version: "1", build_zip: x.zip, active: false}
""")
env = dict(os.environ, TU="u", TP="SECRETPW", NU="n", NP="SECRETNX")
def run(*extra):
    return subprocess.run([sys.executable, str(ROOT / "deploy.py"), "--config", "config.yaml",
                           "--jobs", "jobs.yaml", *extra], cwd=w, env=env, capture_output=True, text=True)

r = run()                       # dry-run
assert r.returncode == 0 and not LOG, (r.stdout, r.stderr, LOG)
assert "SECRETPW" not in r.stdout + r.stderr and "SECRETNX" not in r.stdout + r.stderr
r = run("--apply", "--steps", "upload,task,trigger,run")
print(r.stdout, r.stderr)
assert r.returncode == 0
acts = [x[1]["actionName"] for x in LOG if x[0] == "tac"]
assert acts == ["associatePreGeneratedJob", "getTaskIdByName", "createTrigger", "getTaskIdByName", "runTask"], acts
assert any(x[0] == "nexus" and x[3] for x in LOG)
assert "SECRETPW" not in r.stdout + r.stderr
t = next(x[1] for x in LOG if x[0] == "tac" and x[1]["actionName"] == "createTrigger")
assert t["taskId"] == 42 and t["minutes"] == "30" and t["triggerType"] == "CronTrigger"
r = run("--job", "NOPE"); assert r.returncode != 0
print("SEMUA UJI LULUS")
