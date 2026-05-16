# Boldr Customer Intelligence Engine

An AI-powered customer support system for **Boldr Supply Co.**, a Singapore titanium watch micro-brand. Built for the Echelon 2026 competition.

The system reads incoming customer emails, classifies them, drafts replies from a structured knowledge base, flags unanswerable questions as knowledge gaps, and surfaces weekly/monthly marketing intelligence from accumulated ticket data — all running on self-hosted n8n.

**Live demo:** [customer-ai-engine.netlify.app](https://customer-ai-engine.netlify.app)

---

## Architecture Overview

```
Customer Email
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│  Workflow 1 — Email Processing (runs on every email)    │
│                                                         │
│  Gmail IMAP → Fetch KB → Claude API → Route by type    │
│       │                                    │            │
│       │              ┌─────────────────────┤            │
│       │              ▼         ▼           ▼            │
│       │         Order     Answerable     Gap            │
│       │        Escalate  Draft reply   Log gap          │
│       │           │          │            │             │
│       └───────────┴──────────┴────────────┘            │
│                      Supabase (tickets table)           │
└─────────────────────────────────────────────────────────┘
             │ (gap logged)
             ▼
┌─────────────────────────────────────────────────────────┐
│  Workflow 2 — Gap Resolution (triggered by CS team)     │
│                                                         │
│  Webhook → Fetch gap record → Claude drafts KB entry    │
│         → Update knowledge_gaps + Insert kb_chunks      │
│         → Slack notification to #cs-team               │
└─────────────────────────────────────────────────────────┘
             │ (kb_chunks grows over time)
             ▼
┌─────────────────────────────────────────────────────────┐
│  Workflow 3 — Weekly Clustering (every Monday 8am SGT)  │
│                                                         │
│  Fetch 7d tickets + gaps → Claude theme analysis        │
│  → Store in theme_clusters → Slack digest               │
└─────────────────────────────────────────────────────────┘
             │ (theme_clusters accumulates)
             ▼
┌─────────────────────────────────────────────────────────┐
│  Workflow 4 — Monthly Brief (1st Monday of month)       │
│                                                         │
│  Fetch 4 weeks of clusters → Claude marketing brief     │
│  → Store in marketing_briefs → Slack notification       │
└─────────────────────────────────────────────────────────┘
```

---

## Database Tables (Supabase)

| Table | Purpose |
|---|---|
| `kb_chunks` | Knowledge base — all content Claude reads when answering |
| `tickets` | Every processed email: classification, persona, draft reply |
| `knowledge_gaps` | Questions Claude could not answer from the KB |
| `theme_clusters` | Weekly theme analysis output |
| `marketing_briefs` | Monthly marketing intelligence reports |

---

## Knowledge Base Builder (`build_kb.py`)

The KB is the foundation of the entire system. Before running any workflow, you must build and load the KB into Supabase.

### Three-tier priority system

Claude is instructed to use higher-priority content first and never let lower-priority content override it. This solves a real problem: the Boldr SOP document contains outdated prices that contradict the current rate cards.

**Tier 1 — Rate Cards (authoritative pricing)**

Loaded from two CSV files. These are the single source of truth for all prices and turnaround times. Claude is explicitly told to use these over anything else.

- `KB-ENG-001` — Engraving rate card: per-character pricing, character limits (60 max), rules for logo engraving and corrections
- `KB-SVC-001` — Servicing rate card: Standard Full Service (SGD 160), Premium Full Service (SGD 220), Regulation (SGD 85), Battery Replacement, add-ons

**Tier 2 — Product reference and FAQ**

Factual content for answering product questions.

- `KB-PRD-001` — Product specs for Expedition, Journey, and Ember Limited Edition: dimensions, movement, water resistance, safety certifications, strap compatibility matrix
- `KB-FAQ-001` — Materials & safety: BPA-free, nickel content, lume safety, EU REACH compliance
- `KB-FAQ-002` — Engraving: scripts supported (Latin, CJK, Arabic), multi-line, logo engraving
- `KB-FAQ-003` — Strap compatibility: lug width, quick-release, model-specific restrictions (Mesh = Journey only, Titanium bracelet = Expedition only)
- `KB-FAQ-004` — Servicing: what each tier includes, when to service, international shipping
- `KB-FAQ-005` — Orders, shipping, returns, warranty, gifting

**Tier 3 — Brand voice and process**

- `KB-SOP-001` — Extracted from the SOP PDF. Contains brand voice guidelines, escalation rules, and contact routing. **All pricing stripped out** to prevent the outdated SOP prices from influencing replies.

**Gap resolution entries (dynamic)**

When the CS team resolves a knowledge gap (via Workflow 2), the approved answer is inserted into `kb_chunks` with `source = gap_resolution` and `priority_rank = 2`. These entries are loaded alongside the regular Tier 2 chunks and grow automatically over time — this is the self-improving loop.

### Usage

```bash
pip install pandas pypdf supabase python-dotenv

# Preview what will be loaded (no Supabase write):
python build_kb.py --dry-run

# Load into Supabase:
python build_kb.py
```

`--dry-run` writes `scripts/kb_preview.txt` — read this before going live to verify prices, character limits, and strap compatibility rules are correct.

---

## Workflow 1 — Email Processing

**Trigger:** Gmail IMAP polling every minute (listens to `INBOX`)  
**File:** `n8n/workflow_1_email.json`

### Node-by-node logic

**Gmail Trigger** — polls Gmail via IMAP, fires once per new email.

**Fetch KB Chunks** — HTTP GET to Supabase `kb_chunks` ordered by `priority_rank`. Returns one item per chunk (n8n HTTP Request nodes split JSON arrays into individual items automatically).

**Set Email Fields** — attaches `customer_name`, `customer_email`, `email_subject`, and `email_body` from the Gmail trigger onto each chunk item. This is necessary because the Fetch KB Chunks node outputs N items (one per chunk), and we need the email fields to travel with them into the next node.

**Build KB Context** — Code node (`runOnceForAllItems`). Aggregates all N chunk items back into a single system prompt string, separated into their three tiers. Also extracts the email fields from the first item. Outputs a single item containing the complete system prompt and email metadata.

**Claude API** — HTTP POST to `https://api.anthropic.com/v1/messages`. Sends the assembled system prompt plus the customer email. Instructs Claude to return a JSON object with a fixed schema: `question_type`, `answerable`, `confidence`, persona tags, `draft_reply`, `gap_summary`, and `marketing_signal`.

**Attach Email Fields** — Set node that re-attaches the email fields (`customer_name`, `customer_email`, etc.) after the Claude API call replaced them. Reads from `Build KB Context` via a cross-node reference (allowed in Set nodes, unlike Code nodes).

**Parse Claude Response** — Code node that extracts `content[0].text` from the Claude API response, strips any markdown fences, and parses the JSON. Adds `ticket_id` (timestamp-based) and `received_at`. Falls back gracefully if Claude returns malformed output.

**Route by Type** — Switch node with three outputs:
- `order_status` → Order Escalation branch
- `answerable: true` → Draft Reply branch
- fallback → Knowledge Gap branch

**Order Escalation branch** — Logs to `tickets` table (with `order_escalated: true`) and posts a Slack alert to `#cs-team` with a link to Shopify admin. Claude does not attempt to answer order queries.

**Draft Reply branch** — Logs to `tickets` table (with `answerable: true`, `draft_reply` populated). The draft reply sits in Supabase for the CS team to review and send. No automated sending.

**Knowledge Gap branch** — Logs to `knowledge_gaps` table first (creates a `GAP-{timestamp}` record), then logs to `tickets` (with `gap_flag: true`), then posts a Slack alert to `#cs-team` with the gap details and a webhook URL for submitting the answer.

### Buyer persona classification

Claude tags every ticket with two persona fields:
- `raw_persona_tag` — 7-category internal tag: `health_conscious`, `gifter`, `enthusiast`, `niche_buyer`, `prospect`, `owner_aftercare`, `transactional`
- `competition_persona_tag` — 5-category competition tag: `Health-Conscious Buyer`, `Gifter`, `Enthusiast/Collector`, `Active/Outdoor Buyer`, `Sustainability Advocate`

---

## Workflow 2 — Gap Resolution

**Trigger:** HTTP POST webhook at `/webhook/gap-resolve`  
**File:** `n8n/workflow_2_gap_resolve.json`

When the CS team knows the answer to a flagged gap, they POST to this webhook:

```json
{
  "gap_id": "GAP-1234567890",
  "human_answer": "The Miyota movement is not ISO 764 certified...",
  "cs_name": "Abel"
}
```

### Node-by-node logic

**Webhook** — receives the POST, responds immediately with the gap record.

**Fetch Gap Record** — HTTP GET to Supabase to retrieve the full `knowledge_gaps` row for the given `gap_id`.

**Set Gap Context** — attaches `human_answer` and `cs_name` from the webhook payload onto the gap record (which came from Supabase). Needed because the HTTP GET replaced the webhook payload.

**Prepare Gap Context** — Code node that validates the gap record exists and shapes the data.

**Claude - Draft KB Entry** — asks Claude to write a clean FAQ entry in Boldr's brand voice, given the customer question and the verified human answer. Output format: `Q: ... / A: ...`

**Set KB Context** — re-attaches all gap metadata (`gap_id`, `question_summary`, `theme`, `persona_tag`, etc.) after the Claude API response replaced them.

**Parse KB Draft** — Code node that extracts the drafted Q&A text and generates a `chunk_id` (`KB-GAP-{gap_id}`).

**Update Gap Record** — PATCH to Supabase `knowledge_gaps`: marks `kb_draft_status: approved`, stores the draft text, sets `resolved_at`.

**Insert KB Chunk** — POST to Supabase `kb_chunks`: inserts the new entry with `source: gap_resolution` and `priority_rank: 2`. From this point on, Workflow 1 will use this answer for future similar questions.

**Slack - KB Entry Live** — notifies `#cs-team` that the answer is now live in the KB.

---

## Workflow 3 — Weekly Theme Clustering

**Trigger:** Cron `0 0 * * 1` (Monday 00:00 UTC = 08:00 SGT)  
**File:** `n8n/workflow_3_weekly_cluster.json`

Runs every Monday to aggregate the past 7 days of tickets and gaps into theme clusters for the CS team.

### Node-by-node logic

**Fetch Last 7d Gaps** — GET from `knowledge_gaps` for the past 7 days.

**Collect Gaps** — Code node (`runOnceForAllItems`) that aggregates all gap items into a single item with a `gaps_json` string. This is critical: without this step, the next HTTP Request node would run once per gap item, producing duplicate ticket data.

**Fetch Last 7d Tickets** — GET from `tickets` for the past 7 days. Runs exactly once because the previous node output one item.

**Set Tickets With Gaps** — attaches the `gaps_json` from Collect Gaps onto each ticket item.

**Merge and Prepare Data** — Code node that combines tickets and gaps into a single structured object, calculates `answered_rate_pct`, generates a `cluster_id` (`WC-YYYYMMDD`), and outputs one item.

**Claude - Theme Clustering** — sends all ticket and gap data to Claude. Instructs it to return JSON only: theme names, counts, buyer personas, marketing signal flag, recommended action per theme, and top signals (themes that appeared 3+ times).

**Set Cluster Meta** — re-attaches `cluster_id`, `week_ending`, and totals after the Claude API response replaced them.

**Parse Cluster Response** — Code node that parses Claude's JSON response. Handles the case where Claude wraps output in markdown fences.

**Insert Theme Cluster** — POST to Supabase `theme_clusters`.

**Slack - Weekly Digest** — posts a formatted summary to `#cs-team`: week summary, ticket stats, top signals, and theme breakdown with recommended actions.

---

## Workflow 4 — Monthly Marketing Brief

**Trigger:** Cron `0 0 1-7 * 1` (first Monday of each month, 00:00 UTC = 08:00 SGT)  
**File:** `n8n/workflow_4_monthly_brief.json`

Rolls up four weeks of theme clusters into a marketing brief for the Boldr marketing team.

### Node-by-node logic

**Fetch Last 4 Weeks Clusters** — GET from `theme_clusters` where `week_ending >= 28 days ago`.

**Prepare Brief Context** — Code node (`runOnceForAllItems`) that collects all cluster items and assembles a structured context payload including `brief_id`, `month_label`, and `cluster_count`.

**Claude - Marketing Brief** — instructs Claude to write a one-page marketing brief titled *"What customers are asking that is not on our product pages"*. The brief tags each insight by buyer persona, identifies whether gaps are Boldr-specific or market-wide, flags recurring themes as strong signals, and ends with three concrete action recommendations for the marketing team (product page updates, campaign angles, new FAQ entries).

**Store Brief in Supabase** — POST to `marketing_briefs`.

**Slack - Brief Ready** — posts the brief ID, month label, weeks analysed, and a 600-character preview to `#cs-team`.

---

## Setup

### 1. Prerequisites

- Python 3.10+
- n8n v2.19.5+ (self-hosted)
- Supabase project with the schema from `PRODUCT.md` (Section 5)
- Slack workspace with a `#cs-team` channel

### 2. Environment variables

Create a `.env` file in the project root:

```
SUPABASE_URL=https://your-project.supabase.co/rest/v1
SUPABASE_SERVICE_KEY=your-service-role-key
ANTHROPIC_API_KEY=your-anthropic-api-key
N8N_WEBHOOK_BASE=https://your-n8n-instance.example.com
```

### 3. Build the knowledge base

```bash
pip install pandas pypdf supabase python-dotenv

python build_kb.py --dry-run   # inspect output first
python build_kb.py             # load into Supabase
```

Verify 9 rows in Supabase: `SELECT chunk_id, priority_rank, source FROM kb_chunks ORDER BY priority_rank;`

### 4. Import workflows into n8n

1. In n8n: **Settings → Import** — import each JSON file from `n8n/`
2. In each workflow, replace `YOUR_SUPABASE_SERVICE_KEY` and `YOUR_ANTHROPIC_API_KEY` with your real credentials in every HTTP Request node header
3. Set the IMAP credential in Workflow 1 (Gmail Trigger node)
4. Set the Slack credential in all four workflows (Slack nodes)
5. Activate the workflows

### 5. Test

Before activating, manually execute Workflow 1 with a test email to verify:
- Supabase `kb_chunks` is readable (Fetch KB Chunks returns rows)
- Claude API responds with valid JSON (Parse Claude Response succeeds)
- Routing works (check the correct branch fires for an answerable vs. unanswerable question)

---

## n8n Code Node Constraint

All Code nodes in these workflows use **only `$input`** — no `$('NodeName')` cross-references. This is required because n8n's task runner sandbox (v2.19.5) does not allow cross-node references inside Code nodes. Data is bridged between nodes using **Set nodes** (which run in the main process and can reference any upstream node).

The pattern used throughout:

```
HTTP Request (returns N items)
      ↓
Set node — reads upstream data via $('NodeName').first().json,
           attaches it to each item, passes through with includeOtherFields: true
      ↓
Code node — reads only $input.all() or $input.first().json
      ↓
HTTP Request (replaces all items with API response)
      ↓
Set node — re-attaches previously available fields from upstream node
      ↓
Code node — reads only $input.first().json
```

---

## File Reference

| File | Purpose |
|---|---|
| `build_kb.py` | KB initialisation script — run before first deploy |
| `n8n/workflow_1_email.json` | Email processing workflow |
| `n8n/workflow_2_gap_resolve.json` | Gap resolution webhook workflow |
| `n8n/workflow_3_weekly_cluster.json` | Weekly theme clustering |
| `n8n/workflow_4_monthly_brief.json` | Monthly marketing brief |
| `uploads/03a_rate_card_engraving.csv` | Engraving prices (Tier 1 source) |
| `uploads/03b_rate_card_servicing.csv` | Servicing prices (Tier 1 source) |
| `uploads/04_faq_document.pdf` | FAQ (Tier 2 source) |
| `uploads/05b_product_reference.pdf` | Product specs (Tier 2 source) |
| `uploads/05a_SOP.pdf` | SOP — process and tone only, prices stripped (Tier 3 source) |
| `PRODUCT.md` | Full product specification and database schema |
| `CLAUDE.md` | Build instructions for Claude Code |
