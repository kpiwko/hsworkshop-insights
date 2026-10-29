# Safe Component Refresh Implementation Plan

- **Date:** 2026-10-29
- **Status:** T1 executed 2026-10-29; T2/T3 pending (not yet execution-assigned)
- **Parent orchestrator:** executes T1 -> T2 -> T3 with separate validation gates.
- **Roots:**
  - Insights: `/Users/kpiwko/devel/workshops/hsworkshop-insights`
  - Gitops: `/Users/kpiwko/devel/workshops/genaidemo25-gitops`

## Global constraints

- Both repositories expected clean on `origin/main` with remote
  `git@github.com:kpiwko/{repo}.git`.
- Read-only Git plus scoped local edits only: no branch/fetch/switch/merge/
  stage/commit/push/PR; preserve user work. Every shell call uses an explicit
  `shell.workdir`; checkpoint after 6-8 calls.
- No cluster mutation, deployment/operator install, RHOAI reinstall, Argo
  sync/refresh, image publication, migration/history changes.
- Preserve Vue/FastAPI and Langfuse PG/ClickHouse contracts.
- Cluster reported: RHOAI 3.6 EA, OCP 4.21, one 46GB L40S GPU, no ArgoCD —
  verify, do not presume.
- No accepted ADR found; inspect bounded instructions only.
- Do not touch dotfiles (separate gated work).

## T1 — Insights dependencies and offline regression

Scope: `backend/requirements.txt`, `frontend/package.json` and
`package-lock.json`, `SummaryPanel.vue`, new `backend/tests/test_contracts.py`,
new `frontend/src/lib/summaryMarkdown.ts` and `.test.ts`,
`frontend/vitest.config.ts`, README; conditional Containerfile engine change
only if needed.

1. Verify baseline Git status and current compatible package metadata/engine
   support with official docs/Context7.
2. Candidates (architect verified, reverify rather than force; maintain other
   majors):
   - Backend: FastAPI 0.162.0, uvicorn 0.54.0, psycopg2-binary 2.9.13,
     sse-starlette 3.6.0, httpx 0.28.1 (unchanged).
   - Frontend: Vue 3.5.44, Vite 6.4.5, plugin-vue 5.2.4, Tailwind 3.4.19,
     TypeScript 5.9.3, vue-tsc 2.2.12, marked 17.0.6.
3. Python 3.12, native BUILDPLATFORM frontend build, and amd64 output
   preserved.
4. Add offline unittest/TestClient baseline **before** bump, with dummy env
   vars set before app import; no real DB/HTTP/LLM calls:
   - health → `{"status": "ok"}`;
   - projects/wordcloud/wordgraph response shapes;
   - invalid filter → 422;
   - `_get_data` blocked → traces, valid/all → generations;
   - `/api/blocked` tagged/detected;
   - empty summary → existing message;
   - summarizer failure → 500;
   - ClickHouse `_query` parameter forwarding and JSONEachRow parsing;
   - summarizer `_chat` OpenAI contract.
5. SSE test: read the response as an async body iterator via bounded
   `asyncio.wait_for`, close in `finally`. Verify update events carry JSON
   `wordcloud`/`wordgraph` and failure events carry JSON `error`; never
   infinitely consume TestClient.
6. Add a minimal compatible Vitest DOM harness plus DOMPurify; write failing
   tests first, then implement `renderSummaryMarkdown(markdown: string):
   string` using sync `marked.parse` followed by DOMPurify; wire into
   `SummaryPanel` computed. Tests must cover: empty input; headings/lists/
   emphasis with Czech text preserved; scripts/event handlers/SVG-onload/
   javascript: links removed; HTTPS links preserved.
7. Validate: isolated backend install with `pip check` + unittest; `npm ci` +
   `npm test -- --run` + `npm run build`; inspect `npm audit` without forcing
   majors. If engine available, build existing containers `linux/amd64` with
   no push; otherwise report the gap.
8. README: document versions/test commands; retain Langfuse advice (projects
   SQL and observations/traces/guardrail tags bind the app; MLflow requires a
   separately approved supported-API/ingest/mapping/session/blocked/cutover/
   history plan).
9. Acceptance: installs/tests/build pass, sanitizer proven, API/SSE contracts
   unchanged, gaps honest.

## T2 — Evidence-gated GitOps refresh

Other root (`genaidemo25-gitops`). Read-only inspection of existing
`main`/`highschool-workshop/hs-hackathon` trees/refs, no fetching or
transplanting; inventory versions and ref/commit/paths for Langfuse,
ClickHouse, PG, guardrails, Insights, runtime, Argo; check branch instructions.

- Read-only `oc` to verify cluster runtime template digest, KServe mode,
  Serverless/Knative/Istio, GPU. Current GPTOSS custom
  `vllm0.10.1-gptoss` + `/app/data/template/template_gptoss.jinja`
  context 10000, 0.95 util; Gemma RHOAI 2.24 digest
  `b2391f71951de276722ee5c91a92da4537da36297c9b9d1f2a67ecbaee0214eb`;
  generic values template older digest.
- Conditional version-only model YAML edits only if architecture/
  quantization/Ada/template/CLI/serving-mode are all supported. If
  unverified, leave the exact image unchanged with a specific reason. Never
  treat digest existence as inference proof.
- Preserve names/storage/resources/chart behavior.
- README: repo-relative helm examples; do not reinstall existing RHOAI.
- `docs/component-refresh-2026-10-29.md`: dated source/version/evidence table.
- L40S candidate guidance only: Qwen3.5-9B BF16 8192 context;
  Qwen3-14B-FP8 subject to Ada/backend; GPTOSS20B MXFP4 subject to Ada
  fallback. One full GPU means existing two minReplica=1 models will not both
  schedule. No new deployment/model manifests.
- `helm lint`/`template` with both current concrete values; parse and assert
  expected names/ns/storage/GPU/images/no operators.
- Preserve Argo upstream `red-hat-data-services` source/revision/sync and
  operator manifests.
- Acceptance: evidenced bumps or exact unchanged explained; lint/render;
  conditional model advice.

## T3 — Afterwards read-only Argo check

Append to the Gitops report. Discover Applications/ApplicationSets/ArgoCD/
operator APIs plus subscriptions/CSVs/namespaces.

- Distinguish forbidden from absent, and Workflows from CD.
- If APIs present: read source/revision/path/dest/sync/health/controller
  readiness, no refresh/sync. If absent: report ArgoCD not installed,
  reconciliation uncheckable.
- Document API discovery, then conditional inspection; workshop namespaces
  absent; fork edits not reconciled through upstream app.
- Final status/diff with no secrets; rerun affected checks; zero cluster
  mutations.

## Approvals required (any of these)

- MLflow migration/history changes
- Branch sync/alternate implementation
- Serving redesign/new model
- Upstream -> fork source changes
- Operators/deployment
- Publication
