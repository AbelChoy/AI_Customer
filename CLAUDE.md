# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Read PRODUCT.md for the full specification. When PRODUCT.md and this file conflict, PRODUCT.md wins.

---

## Project Context

Boldr Customer Intelligence Engine — an AI-powered email support pipeline for Boldr Supply Co. (Singapore titanium watch brand), built on n8n + Claude API + Supabase.

**Stack:** n8n (self-hosted, Docker on GCP) · Claude API (`claude-sonnet-4-6`) · Supabase (PostgreSQL) · Gmail OAuth2 · Slack

**Live demo:** https://customer-ai-engine.netlify.app (`demo.html` — no server required, open directly in browser)

---

## Setup Commands

```bash
# Install Python dependencies
pip install pandas pypdf supabase python-dotenv

# Preview KB output (no Supabase write)
python build_kb.py --dry-run

# Load KB into Supabase
python build_kb.py
```

**Note:** `build_kb.py` is at the project root, not in `scripts/`. Preview output writes to `./scripts/kb_preview.txt`.

### Required `.env`

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
ANTHROPIC_API_KEY=your-anthropic-api-key
N8N_WEBHOOK_BASE=https://abelchoy-n8n.duckdns.org
```

Use the **service_role** key (not anon key) — writes to Supabase require it.

---

## Architecture

Four sequential n8n workflows:

1. **Workflow 1** — Gmail trigger → fetch all `kb_chunks` from Supabase → Claude classifies + drafts reply → Switch routes to: Gmail draft (answerable), knowledge gap log + Slack alert (unanswerable), or CS Shopify alert (order queries)
2. **Workflow 2** — Webhook: CS submits gap answer → Claude drafts KB entry → inserts into `kb_chunks` (self-improving loop)
3. **Workflow 3** — Monday 08:00 SGT: pull 7d tickets/gaps → Claude theme clustering → `theme_clusters` table + Slack digest
4. **Workflow 4** — 1st Monday of month: pull 4 weeks of clusters → Claude marketing brief → `marketing_briefs` table

### Supabase tables

| Table | Role |
|---|---|
| `kb_chunks` | All KB content injected into every Claude call |
| `tickets` | Every processed email: classification, persona, draft reply |
| `knowledge_gaps` | Unanswerable questions, lifecycle through resolution |
| `theme_clusters` | Weekly clustering output |
| `marketing_briefs` | Monthly marketing intelligence |

Schema SQL is in PRODUCT.md Section 5. Run it in the Supabase SQL editor before running `build_kb.py`.

---

## Critical Architectural Decisions

### 1. Three-tier KB priority (never reverse this)

The SOP (`05a_SOP.pdf`) contains known pricing errors. The KB enforces strict tier ordering:

- **Tier 1** (priority_rank=1): Rate cards — authoritative for all pricing/turnaround
- **Tier 2** (priority_rank=2): FAQ + product reference + gap resolutions
- **Tier 3** (priority_rank=3): SOP — brand voice and escalation rules **only**, all pricing stripped

`build_kb.py` assembles chunks in this order; `assemble_system_prompt()` enforces the tier separator headers. The Claude system prompt explicitly tells Claude to never use SOP for pricing.

### 2. n8n Code Node constraint

n8n v2.19.5's task runner sandbox **does not allow `$('NodeName')` cross-references inside Code nodes**. Only `$input` is available. The pattern used throughout all four workflows:

```
HTTP Request (N items) → Set node (bridges upstream data) → Code node (reads $input only)
→ HTTP Request (response replaces items) → Set node (re-attaches prior fields) → Code node
```

Never use `$('NodeName').first().json` inside a Code node — it will fail at runtime. Put cross-node reads in Set nodes (which run in the main process).

### 3. Emails are never auto-sent

Workflow 1 creates Gmail **drafts** only. A human must review and click Send. This is a non-negotiable product constraint.

### 4. Order queries bypass the KB entirely

If Claude sets `question_type: "order_status"`, the Switch node routes immediately to a Shopify Slack alert. No KB search, no draft reply. Do not attempt to answer order queries from KB content.

### 5. Gap resolution is the self-improving loop

When Workflow 2 inserts a resolved gap into `kb_chunks` with `source="gap_resolution"` and `priority_rank=2`, it becomes live immediately — the next Workflow 1 execution will include it in the Claude context without any restart or redeploy.

---

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| SOP prices appearing in draft replies | KB tier ordering wrong | Verify SOP chunk has priority_rank=3; rate cards have priority_rank=1 |
| `answerable: true` but draft_reply is null | Claude output schema mismatch | Log `content[0].text` raw before parsing; check schema matches exactly |
| All tickets routing to gap branch | Parse error in Parse Claude Response node | Log rawText before JSON.parse; check Claude API response structure |
| Mesh bracelet suggested for Expedition | KB-PRD-001 not loaded | Re-run `python build_kb.py`; verify row exists in Supabase |
| Engraving quoted as SGD 35 for 21–40 chars | SOP loaded as Tier 1 | SOP must have priority_rank=3 |
| Supabase connection fails | Wrong key type | Use service_role key, not anon key |
| Claude returns non-JSON | Model added preamble | Parse node strips ` ```json ` fences — verify regex covers the actual output |

---

## KB Verification Checklist

After running `python build_kb.py --dry-run`, read `scripts/kb_preview.txt` and confirm:

- Engraving 21–40 chars = SGD 40 (not SGD 35)
- Max engraving characters = 60 (not 40)
- Full Service: SGD 160 Standard / SGD 220 Premium
- Regulation Service = SGD 85 (not SGD 60)
- Mesh bracelet = JOURNEY ONLY
- Titanium bracelet = EXPEDITION ONLY

Supabase check after live run: `SELECT chunk_id, priority_rank, source FROM kb_chunks ORDER BY priority_rank;` — expect 9 rows (2 rate cards + 1 product ref + 5 FAQ sections + 1 SOP).

---

## Four Demo Scenarios (for testing Workflow 1)

| | Ticket | Expected outcome |
|---|---|---|
| **A** | BPA question (health_conscious buyer) | answerable: true, Gmail draft created |
| **B** | Arabic engraving (sample data tagged as gap — AI should correct) | answerable: true — AI catches answer human missed |
| **C** | MRI/magnetic resistance | answerable: false, Slack gap alert fires |
| **D** | Tracking not updated (order_status) | Shopify Slack alert, no KB search |

Scenario B is the key competition demo moment: the AI correctly answers what a human CS agent tagged as a gap.
