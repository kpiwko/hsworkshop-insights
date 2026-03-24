# HSWorkshop Insights

Visualizes Langfuse conversation traces from the HS Workshop AI — word cloud, word graph, and AI-generated summary. Blocked content (detected by TrustyAI guardrails) can be toggled on/off.

## Local development

### Prerequisites

- podman (4.x+, includes `podman compose` built-in)
- `oc` logged in to the cluster

### 1. Port-forward cluster services

```bash
oc port-forward svc/clickhouse -n hsworkshop 18123:8123 &
oc port-forward svc/postgres   -n hsworkshop 15432:5432 &
# Optional — only needed for AI summary
oc port-forward svc/gpt-oss-20b-service-predictor -n hsworkshop 18080:80 &
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in the passwords (get them from the cluster secrets):

```bash
# ClickHouse password
oc get secret clickhouse-secret -n hsworkshop \
  -o jsonpath='{.data.CLICKHOUSE_PASSWORD}' | base64 -d

# PostgreSQL password (langfuse user)
oc get secret langfuse-secret -n hsworkshop \
  -o jsonpath='{.data.DATABASE_URL}' | base64 -d
# → extract password from the postgresql://langfuse:<password>@... URL
```

### 3. Run

```bash
podman compose up --build
```

- Frontend: http://localhost:8080
- Backend API: http://localhost:8000/docs

### Hot reload

The backend mounts `./backend/app` as a volume and runs with `--reload`, so Python changes take effect immediately. For frontend changes, use the Vite dev server instead:

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 — proxies /api to localhost:8000
```

## Switching between workshop runs

When switching from `testing-evalution` to `run-1` or `run-2`:

1. Create a new API key in Langfuse UI for the target project (Settings → API Keys → Create)
2. Update the cluster secret:
   ```bash
   oc create secret generic guardrails-langfuse-secret -n hsworkshop \
     --from-literal=LANGFUSE_HOST=http://langfuse:3000 \
     --from-literal=LANGFUSE_PUBLIC_KEY=pk-lf-... \
     --from-literal=LANGFUSE_SECRET_KEY=sk-lf-... \
     --dry-run=client -o yaml | oc apply -f -
   oc rollout restart deployment/guardrails-proxy -n hsworkshop
   ```
3. Insights app automatically shows all projects in the dropdown — no restart needed.

## Images

```bash
# Build and push
podman build -t quay.io/dprod/hsworkshop-insights-backend:latest ./backend -f ./backend/Containerfile
podman build -t quay.io/dprod/hsworkshop-insights-frontend:latest ./frontend -f ./frontend/Containerfile
podman push quay.io/dprod/hsworkshop-insights-backend:latest
podman push quay.io/dprod/hsworkshop-insights-frontend:latest
```
