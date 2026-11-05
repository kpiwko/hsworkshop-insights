# HSWorkshop Insights

Visualizes Langfuse conversation traces from the HS Workshop AI — word cloud, word graph, and AI-generated summary. Blocked content (detected by TrustyAI guardrails) can be toggled on/off.

## Local development

### Prerequisites

- podman (4.x+, includes `podman compose` built-in)
- `oc` logged in to the cluster

### 1. Port-forward the cluster services

Insights reads from the Langfuse public API (no direct database access) and,
for the AI summary, calls the model endpoint.

```bash
oc port-forward svc/langfuse -n hsworkshop 3000:3000 &
# Optional — only needed for AI summary
# (headless service; must target the pod directly)
oc port-forward -n hsworkshop \
  $(oc get pod -n hsworkshop -l serving.kserve.io/inferenceservice=qwen36-service -o name | head -1) \
  18080:8080 &
```

### 2. Configure environment

```bash
cp .env.example .env
```

Set `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` (a project
API key from the Langfuse UI: Settings → API Keys), and `MODEL_URL` /
`MODEL_NAME` for the summary. `.env.example` has working defaults for the
port-forwards above.

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

## Container images

Images are built and published by GitHub Actions (`.github/workflows/build.yaml`)
on every push to `main`, natively on `ubuntu-24.04` (amd64) and
`ubuntu-24.04-arm` (arm64). Each image is smoke-tested as an arbitrary UID
before it is pushed to GHCR with `GITHUB_TOKEN`, then combined into a
multi-arch manifest tagged `:<commit-sha>` and `:main`:

- `ghcr.io/kpiwko/hsworkshop-insights-backend`
- `ghcr.io/kpiwko/hsworkshop-insights-frontend`

Deploy by digest or `:<commit-sha>`, not a moving tag. New GHCR packages start
private; set them to public in the package settings for anonymous pulls.

Base images are pinned by multi-arch index digest; update them deliberately.
No manual `podman push` is needed.
