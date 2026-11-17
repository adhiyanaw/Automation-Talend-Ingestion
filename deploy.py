#!/usr/bin/env python3
"""
Talend push tool - Nexus + TAC (v1.8)
Langkah: [upload] zip job -> Nexus, [task] buat execution task di TAC dari
artefak Nexus, [context] isi nilai context per task, [deploy] deploy task ke execution server, [trigger] pasang jadwal cron, [run] jalankan task.
v1.8: [version] arahkan task yang sudah ada ke versi artefak baru (urutan: upload,version,context,deploy),
[delete] hapus task (rollback; minta konfirmasi), opsi tac.project (projectName) dan
maven_version_style: xyz (0.1 -> 0.1.0, seperti Publish Studio/felix).

DEFAULT = DRY-RUN (hanya mencetak apa yang akan dikirim). Tambahkan --apply
untuk benar-benar mengirim. Password tidak pernah dicetak atau disimpan.
"""
import argparse, base64, datetime, getpass, json, os, re, sys, zipfile
from pathlib import Path
import requests, yaml

TOOL_VERSION = "1.8"
requests.packages.urllib3.disable_warnings()


# ---------- log file ----------
class Tee:
    """Tulis ke layar dan ke file log (tiap baris diberi waktu)."""
    def __init__(self, stream, fh):
        self.stream, self.fh, self.newline = stream, fh, True

    def write(self, text):
        self.stream.write(text)
        for part in text.splitlines(True):
            if self.newline:
                self.fh.write(datetime.datetime.now().strftime("%H:%M:%S "))
            self.fh.write(part)
            self.newline = part.endswith("\n")
        self.fh.flush()

    def flush(self):
        self.stream.flush()
        self.fh.flush()

    def isatty(self):
        return self.stream.isatty()


def setup_log():
    """log/<YYYYMMDD>_process.log di folder script; ditambah (append) bila sudah ada."""
    d = Path(__file__).resolve().parent / "log"
    d.mkdir(exist_ok=True)
    path = d / f"{datetime.date.today():%Y%m%d}_process.log"
    fh = open(path, "a", encoding="utf-8")
    sys.stdout, sys.stderr = Tee(sys.__stdout__, fh), Tee(sys.__stderr__, fh)
    return path


# ---------- util ----------
def load_yaml(p):
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def secret(section, what, apply_):
    """Ambil user/password dari env var; kalau tidak ada dan --apply, tanya."""
    env = section.get(f"{what}_env", "")
    val = os.environ.get(env, "") if env else ""
    if val:
        return val
    if not apply_:
        return "<dry-run>"
    prompt = f"{env or what}: "
    return getpass.getpass(prompt) if "pass" in what else input(prompt)


SECRET_CTX = set()   # nama context rahasia (nilainya disamarkan di layar dan log)


def mask(d):
    out = {k: ("***" if k in ("authPass",) else v) for k, v in d.items()}
    if isinstance(out.get("context"), dict):
        out["context"] = {k: ("***" if k in SECRET_CTX else v)
                          for k, v in out["context"].items()}
    return out


def maven_version(cfg, job):
    """Versi yang dipakai di Nexus dan TAC.
    plain (default): persis seperti di yaml. xyz: 0.1 -> 0.1.0 (bentuk Maven seperti Publish dari Studio)."""
    v = str(job["version"])
    style = job.get("maven_version_style") or cfg.get("defaults", {}).get("maven_version_style", "plain")
    if style == "xyz" and re.fullmatch(r"\d+\.\d+", v):
        return v + ".0"
    return v


def tac_project(cfg, job):
    """Nama project TAC (projectName untuk getTaskIdByName). Opsional; diisi di config.yaml: tac.project."""
    return job.get("project") or cfg["tac"].get("project") or cfg.get("defaults", {}).get("project", "")


# ---------- Nexus ----------
def nexus_upload(cfg, job, creds, apply_):
    nx = cfg["nexus"]
    zpath = Path(job["build_zip"])
    group = job.get("group_id") or nx["group_id"]
    repo = nx.get("repository", "")
    fields = {
        "maven2.groupId": group,
        "maven2.artifactId": job["artifact_id"],
        "maven2.version": maven_version(cfg, job),
        "maven2.generate-pom": "true",
        "maven2.asset1.extension": "zip",
    }
    url = f"{nx['url'].rstrip('/')}/service/rest/v1/components?repository={repo}"
    print(f"  [nexus] POST {url}")
    print(f"          {fields}  file={zpath}")
    if not repo:
        print("          ! nexus.repository belum diisi")
        if apply_:
            raise SystemExit("nexus.repository kosong")
    if not apply_:
        return True
    if not zpath.is_file():
        raise SystemExit(f"build_zip tidak ditemukan: {zpath}")
    if not zipfile.is_zipfile(zpath):
        raise SystemExit(f"bukan file zip valid: {zpath}")
    with open(zpath, "rb") as fh:
        r = requests.post(url, data=fields,
                          files={"maven2.asset1": (zpath.name, fh)},
                          auth=creds, verify=nx.get("verify_ssl", True),
                          timeout=nx.get("timeout_sec", 120))
    print(f"          -> HTTP {r.status_code} {r.text[:200]}")
    return r.status_code in (200, 204)


# ---------- TAC metaServlet ----------
def meta_call(cfg, payload, creds, apply_):
    tac = cfg["tac"]
    url = f"{tac['url'].rstrip('/')}/metaServlet"
    body = dict(payload, authUser=creds[0], authPass=creds[1])
    print(f"  [tac] {payload['actionName']}  {json.dumps(mask(body), ensure_ascii=False)}")
    if not apply_:
        return {"returnCode": 0, "dry_run": True}
    b64 = base64.b64encode(json.dumps(body).encode()).decode()
    r = requests.post(url, data=b64, verify=tac.get("verify_ssl", True),
                      timeout=tac.get("timeout_sec", 60))
    try:
        res = r.json()
    except ValueError:
        raise SystemExit(f"respons TAC bukan JSON (HTTP {r.status_code}): {r.text[:200]}")
    print(f"        -> returnCode={res.get('returnCode')} {res.get('error', '')}")
    print(f"           respons: {json.dumps(res, ensure_ascii=False)[:400]}")
    return res


def create_task(cfg, job, creds, apply_):
    d = cfg.get("defaults", {})
    nx = cfg["nexus"]
    payload = {
        "actionName": "associatePreGeneratedJob",
        "taskName": job["job_code"],
        "description": f"category={job.get('category','')}",
        "importType": "Nexus",
        "nexusRepository": nx.get("repository", ""),
        "nexusGroupId": job.get("group_id") or nx["group_id"],
        "nexusArtifactId": job["artifact_id"],
        "nexusVersion": maven_version(cfg, job),
        "executionServerName": job.get("execution_server") or d.get("execution_server", ""),
        "contextName": job.get("context_name") or d.get("context_name", "Default"),
        "logLevel": d.get("log_level", "Info"),
        # parameter wajib menurut metaServlet (v1.2): TAC menolak bila tidak ada
        "active": job.get("active_task", d.get("active_task", True)),
        "taskType": "Artifact",
        "timeout": int(job.get("timeout", d.get("timeout", 3600))),
        "onUnknownStateJob": d.get("on_unknown_state", "WAIT"),
        "pauseOnError": bool(d.get("pause_on_error", False)),
    }
    # runAsUser kosong ("") membuat parser TAC gagal ("Missing value"): kirim hanya bila diisi
    run_as = job.get("run_as_user", d.get("run_as_user", ""))
    if run_as:
        payload["runAsUser"] = run_as
    return meta_call(cfg, payload, creds, apply_)


def find_task_id(res):
    """Cari id task di respons getTaskIdByName (nama field berbeda antar versi)."""
    def num(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v)
        return None
    for k in ("result", "taskId", "id", "task_id"):
        if k in res:
            v = res[k]
            if num(v) is not None:
                return num(v)
            if isinstance(v, dict):
                n = find_task_id(v)
                if n:
                    return n
    for v in res.values():          # cadangan: objek/daftar bertingkat
        if isinstance(v, dict):
            n = find_task_id(v)
            if n:
                return n
    return None


def get_task_id(cfg, job, creds, apply_):
    q = {"actionName": "getTaskIdByName", "taskName": job["job_code"]}
    if tac_project(cfg, job):
        q["projectName"] = tac_project(cfg, job)     # tanpa ini TAC bisa menjawab "not found" palsu
    res = meta_call(cfg, q, creds, apply_)
    if not apply_:
        return "<taskId>"
    tid = find_task_id(res)
    if not tid:
        raise SystemExit("ID task tidak ditemukan di respons getTaskIdByName "
                         "(lihat baris 'respons' di atas). Task mungkin belum terbuat, "
                         "atau format respons berbeda.")
    return tid


def build_context(cfg, job, apply_):
    """Gabungkan context biasa (defaults + job) dan rahasia (dari env var)."""
    d = cfg.get("defaults", {})
    ctx = {}
    ctx.update(d.get("context") or {})
    ctx.update(job.get("context") or {})
    sec = {}
    sec.update(d.get("secrets") or {})
    sec.update(job.get("secrets") or {})
    skipped = []
    for name, env in sec.items():
        SECRET_CTX.add(name)
        val = os.environ.get(env, "")
        if not val and apply_:
            val = getpass.getpass(f"{env} (untuk context {name}): ")
        ctx[name] = val if apply_ else "<dry-run>"
    out = {}
    for k, v in ctx.items():
        if v is None or v == "":
            skipped.append(k)        # nilai kosong tidak dikirim (parser TAC bisa gagal)
        else:
            out[k] = str(v)
    if skipped:
        print(f"  [ctx] dilewati (kosong): {', '.join(skipped)}")
    return out


def update_context(cfg, job, creds, apply_):
    """Atur nilai context per task (updateTask). Dilewati bila tidak ada context."""
    ctx = build_context(cfg, job, apply_)
    if not ctx:
        print("  [tac] (tanpa context khusus)")
        return None
    d = cfg.get("defaults", {})
    task_id = get_task_id(cfg, job, creds, apply_)
    payload = {
        "actionName": "updateTask",
        "taskId": task_id,
        "contextName": job.get("context_name") or d.get("context_name", "Default"),
        "context": ctx,
        "contextParamsRefresh": bool(d.get("context_refresh", False)),
        "createContextIfNotExist": True,
    }
    return meta_call(cfg, payload, creds, apply_)


def deploy_task(cfg, job, creds, apply_):
    """Deploy task ke execution server (tombol Deploy di Job Conductor)."""
    task_id = get_task_id(cfg, job, creds, apply_)
    return meta_call(cfg, {"actionName": "requestDeploy", "taskId": task_id},
                     creds, apply_)


def add_trigger(cfg, job, creds, apply_):
    s = job.get("schedule")
    if not s:
        print("  [tac] (tanpa jadwal)")
        return None
    task_id = get_task_id(cfg, job, creds, apply_)
    payload = {
        "actionName": "createTrigger",
        "triggerType": "CronTrigger",
        "taskId": task_id,
        "label": f"{job['job_code']}_cron",
        "description": "dibuat oleh deploy.py",
        "minutes": s.get("minutes", "0"),
        "hours": s.get("hours", "0"),
        "daysOfMonth": s.get("days_of_month", "*"),
        "months": s.get("months", "*"),
        "years": s.get("years", "*"),
        "timezoneOption": s.get("timezone", "JOBSERVER_TIMEZONE"),
        "pauseOnError": False,
    }
    return meta_call(cfg, payload, creds, apply_)


def update_version(cfg, job, creds, apply_):
    """Arahkan task yang sudah ada ke versi artefak baru (updateTask, mode Nexus).
    contextParamsRefresh=True memuat ulang parameter context dari artefak baru, jadi nilai context per task
    bisa kembali ke bawaan: jalankan step 'context' sesudahnya (urutan: upload,version,context,deploy)."""
    d = cfg.get("defaults", {})
    nx = cfg["nexus"]
    task_id = get_task_id(cfg, job, creds, apply_)
    payload = {
        "actionName": "updateTask",
        "taskId": task_id,
        "taskName": job["job_code"],
        "active": job.get("active_task", d.get("active_task", True)),
        "description": f"category={job.get('category','')} versi={maven_version(cfg, job)}",
        "executionServerName": job.get("execution_server") or d.get("execution_server", ""),
        "nexusRepository": nx.get("repository", ""),
        "nexusGroupId": job.get("group_id") or nx["group_id"],
        "nexusArtifactId": job["artifact_id"],
        "nexusVersion": maven_version(cfg, job),
        "contextName": job.get("context_name") or d.get("context_name", "Default"),
        "contextParamsRefresh": True,
        "logLevel": d.get("log_level", "Info"),
        "timeout": int(job.get("timeout", d.get("timeout", 3600))),
        "onUnknownStateJob": d.get("on_unknown_state", "WAIT"),
        "pauseOnError": bool(d.get("pause_on_error", False)),
    }
    return meta_call(cfg, payload, creds, apply_)


def delete_task(cfg, job, creds, apply_):
    """Hapus task di TAC (rollback). Tidak termasuk step default; minta konfirmasi mengetik job_code."""
    task_id = get_task_id(cfg, job, creds, apply_)
    if apply_:
        ans = input(f"  Hapus task '{job['job_code']}' (id {task_id}) di TAC? Ketik job_code untuk lanjut: ")
        if ans.strip() != job["job_code"]:
            print("  dibatalkan")
            return {"returnCode": 1, "error": "dibatalkan oleh pengguna"}
    return meta_call(cfg, {"actionName": "deleteTask", "taskId": task_id}, creds, apply_)


def run_task(cfg, job, creds, apply_):
    task_id = get_task_id(cfg, job, creds, apply_)
    return meta_call(cfg, {"actionName": "runTask", "taskId": task_id,
                           "mode": "synchronous"}, creds, apply_)


def _strings(o, out):
    """Kumpulkan semua string di respons (log biasanya berupa teks panjang)."""
    if isinstance(o, str):
        out.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            _strings(v, out)
    elif isinstance(o, list):
        for v in o:
            _strings(v, out)
    return out


def task_log(cfg, job, creds, apply_):
    """Ambil log eksekusi terakhir task dari TAC, simpan di log/<tgl>_<job>_taskLog.txt."""
    task_id = get_task_id(cfg, job, creds, apply_)
    res = meta_call(cfg, {"actionName": "taskLog", "taskId": task_id,
                          "lastExecution": True}, creds, apply_)
    if not apply_:
        return res
    d = Path(__file__).resolve().parent / "log"
    d.mkdir(exist_ok=True)
    f = d / f"{datetime.date.today():%Y%m%d}_{job['job_code']}_taskLog.txt"
    texts = [t for t in _strings(res, []) if "\n" in t or len(t) > 80]
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(res, ensure_ascii=False, indent=2) + "\n\n")
        fh.write("=== teks log (hasil ekstrak) ===\n")
        fh.write("\n---\n".join(texts) + "\n")
    print(f"        log TAC disimpan: {f}")
    return res


def task_status(cfg, job, creds, apply_):
    task_id = get_task_id(cfg, job, creds, apply_)
    return meta_call(cfg, {"actionName": "getTaskStatus", "taskId": task_id},
                     creds, apply_)


STEPS = {"upload": nexus_upload, "task": create_task, "context": update_context,
         "deploy": deploy_task,
         "trigger": add_trigger, "run": run_task,
         "status": task_status, "taskLog": task_log,
         "version": update_version, "delete": delete_task}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--jobs", default="jobs.yaml")
    ap.add_argument("--steps", default="upload,task,context,deploy,trigger",
                    help="pilih dari: upload,task,context,deploy,trigger,run,status,taskLog,version,delete (pisah koma)")
    ap.add_argument("--category", help="hanya job dengan kategori ini")
    ap.add_argument("--job", help="hanya job_code ini")
    ap.add_argument("--apply", action="store_true",
                    help="kirim sungguhan (default: dry-run)")
    ap.add_argument("--version", action="version", version=TOOL_VERSION)
    a = ap.parse_args()
    logfile = setup_log()
    print(f"{'='*60}\nlog: {logfile}\nperintah: {' '.join(sys.argv)}")

    cfg = load_yaml(a.config)
    jobs = [j for j in load_yaml(a.jobs).get("jobs", [])
            if j.get("active", True)
            and (not a.category or j.get("category") == a.category)
            and (not a.job or j.get("job_code") == a.job)]
    steps = [s.strip() for s in a.steps.split(",") if s.strip()]
    bad = [s for s in steps if s not in STEPS]
    if bad:
        raise SystemExit(f"step tidak dikenal: {bad}")
    if not jobs:
        raise SystemExit("tidak ada job yang cocok")

    mode = "APPLY" if a.apply else "DRY-RUN"
    print(f"deploy.py v{TOOL_VERSION}  mode={mode}  jobs={len(jobs)}  steps={steps}")
    nx_creds = tac_creds = None
    if "upload" in steps:
        nx_creds = (secret(cfg["nexus"], "user", a.apply), secret(cfg["nexus"], "pass", a.apply))
    if any(s in steps for s in ("task", "context", "deploy", "trigger", "run", "status", "taskLog", "version", "delete")):
        tac_creds = (secret(cfg["tac"], "user", a.apply), secret(cfg["tac"], "pass", a.apply))

    fail = 0
    for job in jobs:
        print(f"\n== {job['job_code']} (kategori {job.get('category','-')}, v{job['version']})")
        for s in steps:
            creds = nx_creds if s == "upload" else tac_creds
            res = STEPS[s](cfg, job, creds, a.apply)
            ok = res is None or res is True or (isinstance(res, dict) and res.get("returnCode") == 0)
            if not ok:
                print(f"  !! step {s} gagal, job ini dihentikan")
                fail += 1
                break
    print(f"\nselesai: {len(jobs) - fail} ok, {fail} gagal ({mode})")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
