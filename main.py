import os, re, json, time, sqlite3, datetime as dt
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

GROQ_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("AI_MODEL", "").strip()
GH_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()
DATA = Path(os.getenv("DATA_DIR", "./data")); DATA.mkdir(parents=True, exist_ok=True)
DB = str(DATA / "portal.db")

def active_provider() -> str:
    if GROQ_KEY: return "groq"
    if GEMINI_KEY: return "gemini"
    if OPENAI_KEY: return "openai"
    if ANTHROPIC_KEY: return "anthropic"
    return "heuristic"

INTERNS = {
 "shumyze": ("Shumyze Najam", "Foot-Traffic & Line-Crossing Counter", "{entries, exits, occupancy}"),
 "alina": ("Alina Khalid", "Checkout Queue Dwell-Time Monitor", "{queue_length, avg_wait_sec, alerts}"),
 "abdul": ("Abdul Razzaq", "Shelf Stock / Empty-Gap Detector", "{fill_rate_pct, empty_slots, restock_alert}"),
 "sidra": ("Sidra", "Privacy-First Face Blur Pipeline", "anonymize_frame(frame) -> frame + face count"),
 "aiman": ("Aiman", "Customer Heatmap & Aisle Zone Engagement Tracker", "process_frame(frame) -> (ndarray, {hotspot_zone, zone_dwell_pct})"),
}
DAYS = [  # (date, theme, required commit)
 ("2026-11-24", "Repo setup, environment & sample clips/images", "requirements.txt, README.md and /samples pushed"),
 ("2026-11-25", "Baseline pre-trained CV model inference", "baseline.py running YOLO/MediaPipe detection on sample frames"),
 ("2026-11-26", "Core spatial CV logic (Part 1)", "line-crossing, polygon ROI, shelf grid, face blur or 2D Gaussian heatmap working"),
 ("2026-11-27", "Decision rules & JSON output contract (Part 2)", "standardized JSON metrics + annotated OpenCV frame"),
 ("2026-11-30", "Reusable module wrapper + CSV analytics logging", "callable process_frame class + local time-series CSV logger"),
 ("2026-12-01", "Interactive Streamlit/Gradio UI + privacy blur", "app.py with video upload, live CV overlays, and Sidra's face-blur filter"),
 ("2026-12-02", "Edge-case tuning, FPS & noise filtering", "ID-switch smoothing, alert debouncing, temporal decay, frame-skip FPS tuning"),
 ("2026-12-03", "End-to-end demo & documentation", "complete README, sample output visuals, live 5-module showcase"),
]
PKT = dt.timezone(dt.timedelta(hours=5))

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS subs(k TEXT PRIMARY KEY, intern TEXT, day INT, data TEXT,
                 attempts INT DEFAULT 1, ts REAL)""")
    return c

app = FastAPI(title="Zigron CV Sprint Portal")
last_hit: dict = {}

class Sub(BaseModel):
    intern_id: str
    day: int
    repo_url: str
    notes: str = ""

@app.get("/health")
def health():
    prov = active_provider()
    return {"ok": True, "ai": prov != "heuristic", "provider": prov}

@app.get("/api/submissions")
def submissions():
    with db() as c:
        return {r["k"]: {**json.loads(r["data"]), "attempts": r["attempts"]} for r in c.execute("SELECT * FROM subs")}

@app.delete("/api/submissions/{key}")
def delete(key: str, x_admin_key: str = Header("")):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY: raise HTTPException(403, "Not allowed")
    with db() as c: c.execute("DELETE FROM subs WHERE k=?", (key,))
    return {"deleted": key}

async def gh(client, path, raw=False):
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json", "User-Agent": "zigron-portal"}
    if GH_TOKEN: h["Authorization"] = f"Bearer {GH_TOKEN}"
    r = await client.get("https://api.github.com" + path, headers=h)
    return r

async def inspect_repo(url: str) -> dict:
    m = re.match(r"https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?(?:$|/tree|/blob)", url.strip())
    if not m: raise HTTPException(400, "Enter a valid https://github.com/user/repo URL")
    o, n = m.groups()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await gh(c, f"/repos/{o}/{n}")
        if r.status_code == 404: raise HTTPException(400, "Repository not found. Is it public?")
        if r.status_code in (403, 429): raise HTTPException(503, "GitHub rate limit hit, try again in a few minutes")
        info = r.json(); br = info["default_branch"]
        t = await gh(c, f"/repos/{o}/{n}/git/trees/{br}?recursive=1")
        files = [x for x in (t.json().get("tree", []) if t.status_code == 200 else []) if x["type"] == "blob"]
        paths = [x["path"] for x in files][:200]
        cm = await gh(c, f"/repos/{o}/{n}/commits?per_page=20")
        commits = [f'{x["commit"]["author"]["date"]} {x["commit"]["message"].splitlines()[0][:80]}'
                   for x in (cm.json() if cm.status_code == 200 else [])]
        pick = [p for p in paths if p.lower() in ("readme.md", "requirements.txt")]
        py = sorted([p for p in paths if p.endswith(".py")], key=lambda p: (p.count("/"), len(p)))[:5]
        samples = {}
        for p in pick + py:
            fr = await gh(c, f"/repos/{o}/{n}/contents/{p}", raw=True)
            if fr.status_code == 200: samples[p] = fr.text[:3500]
    return {"repo": f"{o}/{n}", "pushed_at": info.get("pushed_at"), "paths": paths, "commits": commits, "samples": samples}

def parse_json(txt: str) -> dict:
    return json.loads(txt[txt.index("{"): txt.rindex("}") + 1])

def heuristic_grade(intern_id: str, day: int, notes: str, repo: dict) -> dict:
    """Automatic GitHub repo inspector & rubric scorer (works with zero API keys)."""
    paths_lower = [p.lower() for p in repo["paths"]]
    all_code = "\n".join(repo["samples"].values()).lower()
    has_readme = any(p.endswith("readme.md") for p in paths_lower)
    has_reqs = any(p.endswith("requirements.txt") for p in paths_lower)
    has_samples = any("sample" in p or p.endswith((".mp4", ".avi", ".jpg", ".jpeg", ".png")) for p in paths_lower)
    py_files = [p for p in paths_lower if p.endswith(".py")]
    has_baseline = any("baseline" in p for p in py_files) or len(py_files) >= 1
    has_cv_lib = any(k in all_code for k in ("cv2", "ultralytics", "yolo", "mediapipe", "supervision", "numpy"))
    has_process_fn = "def process_frame" in all_code or "def anonymize_frame" in all_code
    has_ui_or_log = any(k in all_code for k in ("streamlit", "gradio", "csv", "to_csv", "json.dump"))
    has_privacy = any(k in all_code for k in ("anonymize_frame", "gaussianblur", "privacy", "blur"))

    code_pts = 12 if py_files else 6
    if has_cv_lib: code_pts += 14
    if has_baseline: code_pts += 8
    if len(py_files) >= 2: code_pts += 6

    robust_pts = 8 if len(repo["commits"]) >= 2 else 4
    if has_samples: robust_pts += 6
    if has_privacy or day < 5: robust_pts += 6

    integ_pts = 10 if (has_reqs or day == 0) else 5
    if has_process_fn: integ_pts += 10
    elif day < 4 and py_files: integ_pts += 7
    if has_ui_or_log or day < 4: integ_pts += 5

    docs_pts = 0
    if has_readme and len(repo["samples"].get("README.md", repo["samples"].get("readme.md", ""))) > 60:
        docs_pts += 9
    elif has_readme:
        docs_pts += 5
    if has_reqs: docs_pts += 4
    if len(notes.strip()) >= 20: docs_pts += 2

    missing = []
    if not has_readme: missing.append("README.md")
    if not has_reqs: missing.append("requirements.txt")
    if day == 0 and not has_samples: missing.append("/samples media files")
    if day >= 1 and not py_files: missing.append("baseline.py / Python CV script")
    if day >= 4 and not has_process_fn: missing.append("process_frame(frame) interface")

    feedback = (
        f"Verified {len(repo['paths'])} files and {len(repo['commits'])} commits in {repo['repo']}. "
        + (f"Detected Python CV implementation ({', '.join(py_files[:3])}). " if py_files else "No Python source files found yet. ")
        + (f"Missing expected items for Day {day+1}: {', '.join(missing)}." if missing else "All key Day " + str(day+1) + " artifacts are present.")
    )
    steps = [
        f"Add {', '.join(missing[:2])}" if missing else "Keep committing modular code with clear commit messages",
        "Ensure process_frame(frame) -> (annotated_frame, metrics_dict) is cleanly exposed",
        "Include FPS benchmark and sample output screenshot in README.md"
    ]
    out = {
        "code": min(40, code_pts),
        "robust": min(20, robust_pts),
        "integ": min(25, integ_pts),
        "docs": min(15, docs_pts),
        "feedback": feedback,
        "steps": steps[:3],
    }
    out["score"] = out["code"] + out["robust"] + out["integ"] + out["docs"]
    return out

async def grade(intern_id, day, notes, repo) -> tuple[dict, str]:
    prov = active_provider()
    if prov == "heuristic":
        return heuristic_grade(intern_id, day, notes, repo), "Repo verified (auto-rubric)"

    name, module, contract = INTERNS[intern_id]; d = DAYS[day]
    code = "\n".join(f"--- {p} ---\n{s}" for p, s in repo["samples"].items())
    safe_notes = (notes[:2000] or "(none)").replace('"""', "'''")
    prompt = f"""You are a strict but fair senior computer-vision engineer grading an intern's daily GitHub submission.
Project: All-CV Retail Analytics & Safety Suite. Every module must expose process_frame(frame) -> (ndarray, dict) (or anonymize_frame(frame) for Sidra); faces must be anonymized before frames are saved/streamed.
Intern: {name}. Module: {module}. Output contract: {contract}.
Sprint Day {day+1} ({d[0]}): {d[1]}. Required commit: {d[2]}.
Rubric maxima: code (module accuracy & code quality) 40, robust (privacy & edge-case robustness) 20, integ (integration with central dashboard) 25, docs (documentation/demo clarity) 15. Weight setup/baseline on early days and robustness/integration/docs on later days, but score against the maxima for what is expected BY this day.
Repo: {repo['repo']} (last push {repo['pushed_at']}).
Recent commits (newest first):
{chr(10).join(repo['commits']) or '(none)'}
File list: {', '.join(repo['paths'][:120]) or '(empty)'}
Key file contents:
{code or '(no readable files)'}
Intern notes:
{safe_notes}
Grade only what the repo evidence shows; if required files for this day are missing, score low and say exactly which. Do not reward claims in the notes that the code does not back up.
Return ONLY JSON: {{"code":int,"robust":int,"integ":int,"docs":int,"feedback":"2-3 sentences","steps":["2-3 short actionable next steps"]}}"""

    async with httpx.AsyncClient(timeout=90) as c:
        if prov == "groq":
            m = MODEL or "llama-3.3-70b-versatile"
            r = await c.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
                json={"model": m, "messages": [{"role": "user", "content": prompt}], "max_tokens": 700, "temperature": 0.2},
            )
            if r.status_code != 200: raise HTTPException(502, f"Groq reviewer error ({r.status_code})")
            raw_txt = r.json()["choices"][0]["message"]["content"]
            src_label = f"AI verified ({m})"
        elif prov == "gemini":
            m = MODEL or "gemini-2.5-flash"
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            if r.status_code != 200: raise HTTPException(502, f"Gemini reviewer error ({r.status_code})")
            raw_txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            src_label = f"AI verified ({m})"
        elif prov == "openai":
            m = MODEL or "gpt-4o-mini"
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
                json={"model": m, "messages": [{"role": "user", "content": prompt}], "max_tokens": 700},
            )
            if r.status_code != 200: raise HTTPException(502, f"OpenAI reviewer error ({r.status_code})")
            raw_txt = r.json()["choices"][0]["message"]["content"]
            src_label = f"AI verified ({m})"
        else:
            m = MODEL or "claude-sonnet-4-20250514"
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": m, "max_tokens": 700, "messages": [{"role": "user", "content": prompt}]},
            )
            if r.status_code != 200: raise HTTPException(502, f"Anthropic reviewer error ({r.status_code})")
            raw_txt = r.json()["content"][0]["text"]
            src_label = f"AI verified ({m})"

    j = parse_json(raw_txt)
    g = lambda v, mx: max(0, min(mx, int(round(float(v or 0)))))
    out = {
        "code": g(j.get("code"), 40),
        "robust": g(j.get("robust"), 20),
        "integ": g(j.get("integ"), 25),
        "docs": g(j.get("docs"), 15),
        "feedback": str(j.get("feedback", "")),
        "steps": [str(s) for s in j.get("steps", [])][:3],
    }
    out["score"] = out["code"] + out["robust"] + out["integ"] + out["docs"]
    return out, src_label

@app.post("/api/submit")
async def submit(s: Sub, req: Request):
    if s.intern_id not in INTERNS or not 0 <= s.day < len(DAYS): raise HTTPException(400, "Unknown intern or day")
    if dt.datetime.now(PKT).date().isoformat() < DAYS[s.day][0] and not os.getenv("ALLOW_FUTURE"):
        raise HTTPException(400, "That sprint day is not open yet")
    ip = req.headers.get("x-forwarded-for", req.client.host).split(",")[0]
    if time.time() - last_hit.get(ip, 0) < 10: raise HTTPException(429, "Please wait 10 seconds between submissions")
    last_hit[ip] = time.time()
    repo = await inspect_repo(s.repo_url)
    try: res, src_label = await grade(s.intern_id, s.day, s.notes, repo)
    except HTTPException: raise
    except Exception: raise HTTPException(502, "Reviewer returned an unreadable answer, please resubmit")
    res.update(url=s.repo_url, ts=int(time.time() * 1000), src=src_label)
    k = f"{s.intern_id}_{s.day}"
    with db() as c:
        c.execute("""INSERT INTO subs(k,intern,day,data,ts) VALUES(?,?,?,?,?)
                     ON CONFLICT(k) DO UPDATE SET data=excluded.data, ts=excluded.ts, attempts=attempts+1""",
                  (k, s.intern_id, s.day, json.dumps(res), time.time()))
    return res

app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/")
def home(): return FileResponse("static/index.html")
