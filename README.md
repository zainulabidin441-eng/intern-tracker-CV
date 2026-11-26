# Zigron CV Sprint Portal

FastAPI + SQLite app. Interns submit a GitHub repo URL; the server reads the real repo
(file tree, commits, README, key .py files) via the GitHub API and grades it with Claude
against the sprint rubric (40/20/25/15).

## Run locally
    pip install -r requirements.txt
    cp .env.example .env   # fill ANTHROPIC_API_KEY, then: export $(grep -v '^#' .env | xargs)
    uvicorn main:app --reload
Open http://localhost:8000. Set ALLOW_FUTURE=1 to test locked days.

## Deploy on Railway
1. Push this folder to a GitHub repo.
2. Railway -> New Project -> Deploy from GitHub repo (railway.json is picked up automatically).
3. Service -> Variables: ANTHROPIC_API_KEY, GITHUB_TOKEN (recommended), ADMIN_KEY, DATA_DIR=/data
4. Service -> Settings -> Volumes -> add a volume mounted at /data (keeps the SQLite DB across deploys).
5. Settings -> Networking -> Generate Domain.

## Notes
- Only public repos can be inspected.
- Resubmitting the same day overwrites the grade (attempt count is stored).
- Delete a grade: curl -X DELETE -H "x-admin-key: $ADMIN_KEY" https://<domain>/api/submissions/sidra_2
- Submissions open by Pakistan date (UTC+5); one submission per IP every 20 s.
