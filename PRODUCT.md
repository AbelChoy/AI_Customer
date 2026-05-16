# Boldr Customer Intelligence Engine — Product Specification
## For Claude Code: Read this entire document before writing any code.

> **Project:** AI Workflow Automation — Echelon 2026 Boldr Challenge
> **Builder:** Abel Choy
> **Deadline:** Sunday 17 May 2026, 3pm
> **Repo:** https://github.com/AbelChoy/AI-Workflow
> **Live n8n:** https://abelchoy-n8n.duckdns.org
> **Stack:** n8n (self-hosted) · Claude API · Supabase · Gmail

---

## 1. What We Are Building

A self-improving customer intelligence engine for Boldr Supply Co., a Singapore-based
titanium watch micro-brand. The system transforms their reactive, manual email support
into an automated pipeline that:

1. **Answers** known questions by drafting replies in Boldr's brand voice (human approves before send)
2. **Detects** questions not in the knowledge base (knowledge gaps) and routes to CS staff
3. **Learns** — once a human resolves a gap, the system auto-drafts a new KB entry and adds it permanently
4. **Surfaces intelligence** — weekly theme clustering and monthly marketing briefs showing what customers
   ask that is not on Boldr's product pages

The system does NOT auto-send emails. Every reply requires human approval. This is non-negotiable.

---

## 2. Architecture Overview

```
INBOUND EMAIL (Gmail)
        │
        ▼
[n8n Workflow 1 — Real-time email processing]
        │
        ├── Code Node: Extract KB content from Supabase
        │
        ├── HTTP Node: Claude API — Intent + KB search + classification
        │       Returns JSON: question_type, persona_tag, answerable,
        │                     draft_reply, gap_summary, marketing_signal
        │
        └── Switch Node (3 branches):
              │
              ├── order_status → CS Alert (Shopify deeplink, no KB attempt)
              │
              ├── answerable: true → Gmail Draft (human approves, then sends)
              │                    → Log to Supabase tickets table
              │
              └── answerable: false → Supabase knowledge_gaps (status: pending)
                                    → Slack/email alert to CS team
                                    → CS submits answer via form/webhook

[n8n Workflow 2 — Gap resolution] (webhook trigger from CS form)
        │
        ├── HTTP Node: Claude API — Auto-draft KB entry from human answer
        │
        ├── Slack: Send KB draft to CS for 1-click approval
        │
        └── On approval: INSERT into kb_chunks (immediately live)
                       + UPDATE knowledge_gaps status → resolved

[n8n Workflow 3 — Weekly theme clustering] (schedule: Monday 8am SGT)
        │
        ├── Supabase: Pull last 7 days of knowledge_gaps + tickets
        ├── HTTP Node: Claude API — cluster by theme, tag personas
        └── INSERT into theme_clusters + Slack digest to CS team

[n8n Workflow 4 — Monthly marketing brief] (schedule: 1st Monday of month)
        │
        ├── Supabase: Pull last 4 weeks of theme_clusters
        ├── HTTP Node: Claude API — marketing brief + external benchmarking
        └── Email PDF/markdown to Boldr team
```

---

## 3. Technology Stack

| Layer | Tool | Notes |
|---|---|---|
| Orchestration | n8n v2.19.5 self-hosted, Docker on GCP | DuckDNS public URL |
| AI | Claude API — `claude-sonnet-4-6` | Single call per ticket: classify + draft + score |
| Email trigger | n8n Gmail node (OAuth2) | Primary inbound channel |
| KB storage | Supabase (PostgreSQL) | kb_chunks table; pgvector-ready |
| Ticket logging | Supabase | tickets, knowledge_gaps, theme_clusters tables |
| Human approval | Gmail Drafts + Slack | Draft created in inbox; human clicks Send |
| CS alerts | Slack | Gap alerts + weekly digest |
| External search | Claude API with web_search tool | Bonus: external sentiment benchmarking |

---

## 4. Source Documents & Data Files

All files are in `/uploads/` relative to the project root.

| File | Type | Role | Trust level |
|---|---|---|---|
| `03a_rate_card_engraving.csv` | CSV | Engraving prices (authoritative) | **Tier 1 — highest** |
| `03b_rate_card_servicing.csv` | CSV | Servicing prices (authoritative) | **Tier 1 — highest** |
| `04_faq_document.pdf` | PDF | 28 Q&A entries across all themes | Tier 2 |
| `05b_product_reference.pdf` | PDF | Model specs, strap catalogue, safety | Tier 2 |
| `05a_SOP.pdf` | PDF | Process guidance, brand voice | **Tier 3 — tone only** |
| `01_customer_tickets.csv` | CSV | 70 sample tickets — demo + test data | Input data |

### ⚠️ Critical: SOP Has Outdated Prices — Do Not Use for Pricing

The SOP (`05a_SOP.pdf`) contains the following known errors vs. the rate cards:

| Field | SOP (WRONG) | Rate card (CORRECT) |
|---|---|---|
| Engraving 21–40 chars | SGD 35 | SGD 40 |
| Max engraving characters | 40 | 60 |
| Full service range | SGD 180–250 | SGD 160 (Standard) / SGD 220 (Premium) |
| Regulation service | SGD 60 | SGD 85 |
| Battery turnaround | 5–7 days | 3–5 days |
| Crystal replacement | SGD 80–120 | SGD 65 |

**The SOP is used ONLY for brand voice and process guidance. Strip all pricing from it before loading.**

---

## 5. Supabase Schema

Run this SQL in Supabase SQL editor to create all tables.

```sql
-- Enable pgvector extension (RAG-ready; embeddings null for now)
create extension if not exists vector;

-- ─────────────────────────────────────────
-- TABLE 1: kb_chunks
-- Single source of truth for all KB content.
-- All rows injected into every Claude call (full-context injection).
-- embedding column null now; populate with pgvector when KB > 100 entries.
-- ─────────────────────────────────────────
create table kb_chunks (
  chunk_id      text primary key,            -- e.g. 'KB-ENG-001', 'KB-FAQ-003'
  source        text not null,               -- rate_card_engraving | rate_card_servicing |
                                             -- faq | product_reference | sop_process | gap_resolution
  category      text not null,              -- engraving | servicing | materials_safety |
                                             -- strap_compatibility | product_general | product_specs | process
  content       text not null,              -- formatted text chunk (as it appears in system prompt)
  priority_rank int  not null default 2,    -- 1=rate cards (authoritative), 2=faq+product, 3=sop
  approved_by   text,                        -- null for original docs; CS name for gap_resolution entries
  approved_at   timestamptz,
  created_at    timestamptz default now(),
  embedding     vector(1536)                -- null now; populate for pgvector RAG later
);

create index on kb_chunks (priority_rank);
create index on kb_chunks (source);
create index on kb_chunks (category);

-- ─────────────────────────────────────────
-- TABLE 2: tickets
-- Log of every processed inbound email.
-- ─────────────────────────────────────────
create table tickets (
  ticket_id          text primary key,       -- e.g. 'TKT-2026-001' (generate in n8n)
  received_at        timestamptz not null,
  customer_name      text,
  customer_email     text not null,
  channel            text not null,          -- email | whatsapp | instagram_dm | chat
  subject            text,
  message_body       text not null,
  question_type      text,                   -- engraving | servicing | materials_safety |
                                             -- strap_compatibility | product_general |
                                             -- order_status | knowledge_gap
  intent_summary     text,                   -- Claude's 1-line summary of the question
  answerable         boolean,                -- true = KB answer found; false = gap
  persona_tag        text,                   -- raw 7-category tag (see Section 8)
  competition_persona text,                  -- mapped 5-category tag for marketing brief
  theme              text,                   -- materials | sustainability | sizing | gifting | servicing
  marketing_signal   boolean default false,  -- true = could be a marketing insight
  draft_reply        text,                   -- Claude's draft (null if order_status or gap)
  kb_sources_used    text[],                 -- which kb_chunks answered this (chunk_ids)
  gap_flag           boolean default false,
  order_escalated    boolean default false,
  created_at         timestamptz default now()
);

-- ─────────────────────────────────────────
-- TABLE 3: knowledge_gaps
-- Tracks every unanswered question through resolution.
-- ─────────────────────────────────────────
create table knowledge_gaps (
  gap_id             text primary key,       -- 'GAP-2026-001'
  ticket_id          text references tickets(ticket_id),
  question_summary   text not null,          -- Claude's paraphrase of the gap question
  theme              text,
  persona_tag        text,
  marketing_signal   boolean default false,  -- should this appear in monthly brief?
  frequency_count    int  default 1,         -- incremented when same theme recurs
  human_answer       text,                   -- CS team's resolved answer (from webhook)
  kb_draft_text      text,                   -- Claude's auto-drafted KB entry
  kb_draft_status    text default 'pending', -- pending | approved | rejected
  approved_by        text,
  approved_at        timestamptz,
  kb_chunk_id        text,                   -- set when inserted into kb_chunks
  created_at         timestamptz default now(),
  resolved_at        timestamptz
);

-- ─────────────────────────────────────────
-- TABLE 4: theme_clusters
-- Weekly roll-up output from Workflow 3.
-- ─────────────────────────────────────────
create table theme_clusters (
  cluster_id         text primary key,
  week_ending        date not null,
  themes_json        jsonb,                  -- array of {theme, count, personas[], tickets[]}
  top_signals        jsonb,                  -- top 3 marketing signals this week
  new_gaps_count     int,
  resolved_gaps_count int,
  created_at         timestamptz default now()
);

-- ─────────────────────────────────────────
-- TABLE 5: marketing_briefs
-- Monthly output from Workflow 4.
-- ─────────────────────────────────────────
create table marketing_briefs (
  brief_id           text primary key,
  month_ending       date not null,
  brief_markdown     text,                   -- full brief text
  persona_insights   jsonb,                  -- per-persona signals
  external_signals   jsonb,                  -- bonus: external benchmarking results
  created_at         timestamptz default now()
);
```

---

## 6. Knowledge Base Structure

### 6.1 Source Hierarchy (Claude must respect this order for conflicts)

```
Tier 1 — AUTHORITATIVE (rate cards) ──── Always wins for pricing/turnaround
Tier 2 — INFORMATIONAL (FAQ + product) ── Wins for specs, Q&A, compatibility
Tier 3 — PROCESS ONLY (SOP) ──────────── Tone and escalation rules ONLY
          ↓ auto-appended
Gap resolutions ─────────────────────────  Treated as Tier 2 once approved
```

### 6.2 Engraving Rate Card (source of truth)

| Service | Price (SGD) | Notes |
|---|---|---|
| Caseback engraving — up to 20 characters | 25.0 | Standard Roman/Latin script only |
| Caseback engraving — 21 to 40 characters | 40.0 | Standard Roman/Latin script only |
| Caseback engraving — per additional character (beyond 40) | 1.5 | Max 60 characters total |
| Caseback engraving — Chinese/Japanese/Korean (per character) | 3.0 | Up to 15 CJK characters |
| Caseback engraving — Arabic script (per character) | 3.0 | Up to 15 characters |
| Strap buckle engraving — up to 10 characters | 15.0 | Metal buckle only; not rubber/NATO |
| Logo/symbol engraving (custom vector art) | 60.0 | Customer supplies .ai or .svg; team approval required |
| Multi-line engraving (2 lines) | 35.0 | Up to 30 characters total across both lines |
| Rush engraving (same-day processing) | 20.0 | Before 12pm SGT; subject to availability |
| Engraving correction (within 1 hour of order) | 0.0 | Free within 1hr; SGD 15 thereafter |

### 6.3 Servicing Rate Card (source of truth)

| Service | Price (SGD) | Turnaround | Notes |
|---|---|---|---|
| Battery Replacement | 35 | 3–5 days | Quartz movements only |
| Regulation Service | 85 | 7–10 days | Automatic movements only |
| Full Service — Standard | 160 | 14–21 days | Recommended every 3–5 years |
| Full Service — Premium | 220 | 14–21 days | Includes 12-month service warranty |
| Crystal Replacement | 65 | 5–7 days | OEM sapphire |
| Case & Bracelet Polish | 45 | 3–5 days | Add-on to any service tier |
| Strap/Bracelet Replacement (fitting only) | 10 | 1 day | — |
| Water Resistance Re-test | 20 | 1–2 days | Standalone |
| International Service surcharge | 25 | Add 7–14 days | Boldr covers insured return shipping |
| Service Warranty Extension (12 months) | 30 | — | Must be purchased at time of service |

### 6.4 Product Models

**Expedition Titanium | SGD 485 | SKU: BLD-EXP-TI-40**
- Case: 40mm, 11.5mm thick, Grade 5 Ti (Ti-6Al-4V), brushed + polished
- Crystal: Sapphire with AR coating
- Movement: Miyota 9015 auto, 42hr power reserve, +/-10s/day
- Water resistance: 100m — safe for swimming, not diving
- Lume: Super-LumiNova C3, non-radioactive, ISO 3157
- Lug width: 20mm (fits all standard 20mm straps)
- Safety: BPA-free YES · Nickel-free YES · Hypoallergenic YES · EU REACH YES
- Dials: Slate Grey, Forest Green, Midnight Blue, Sandstone
- Included strap: 20mm FKM rubber (black) | Weight: 68g
- Availability: IN STOCK

**Journey Titanium | SGD 395 | SKU: BLD-JRN-TI-38**
- Case: 38mm, 10.8mm thick, Grade 2 Ti (commercially pure), full brushed
- Crystal: Sapphire with AR coating
- Movement: Miyota 6T33 auto, 40hr power reserve, +/-15s/day
- Water resistance: 50m — splash resistant ONLY, not for swimming
- Lug width: 20mm (fits all standard 20mm straps)
- Safety: BPA-free YES · Nickel-free YES · Hypoallergenic YES · EU REACH YES
- Dials: Ivory White, Charcoal, Terracotta, Ocean Blue
- Included strap: 20mm Nylon NATO (olive)
- Availability: IN STOCK

**Expedition Ember Limited Edition | SGD 595 | SKU: BLD-EXP-TI-40-LE**
- Case: 40mm, Grade 5 Ti, PVD bronze coating
- Safety: BPA-free YES · Nickel-free YES · Hypoallergenic NO (leather strap)
- ⚠️ SOLD OUT — direct customers to boldr.co/waitlist. Do not promise restock date.

**Strap Catalogue (all models 20mm lug width):**
- FKM Rubber Black/Navy/Olive/Red: SGD 35 — BPA-free, nickel-free — all models
- Nylon NATO Olive/Black/Tan: SGD 25 — BPA-free — all models
- Leather Brown/Black: SGD 55 — BPA-free, NOT hypoallergenic — all models
- Mesh Bracelet Silver: SGD 75 — **JOURNEY ONLY**
- Titanium Bracelet: SGD 145 — **EXPEDITION ONLY**

---

## 7. Claude API Configuration

### 7.1 Model
```
claude-sonnet-4-6
```

### 7.2 System Prompt Template

The system prompt is assembled at query time by an n8n Code node. It pulls all rows
from `kb_chunks` ordered by `priority_rank ASC` and inserts them into this template.

```
You are the AI customer service assistant for Boldr Supply Co., a premium Singapore-based
titanium watch micro-brand. You process inbound customer enquiries.

YOUR TASK: Analyse the customer email and return a single JSON object (no other text).

RULES — READ CAREFULLY:
1. PRICING: Always use Tier 1 (Rate Cards) for all prices and turnaround times.
   Never use the SOP for pricing — it is outdated.
2. HONESTY: If the answer is not in the knowledge base, set answerable: false.
   Do NOT guess, estimate, or hallucinate. Return gap_summary instead.
3. ORDER QUERIES: If the email is about an order (tracking, refund, cancellation,
   wrong item, delivery address), set question_type: "order_status" immediately.
   Do not search the KB. Set answerable: false and draft_reply: null.
4. DRAFT REPLIES: Write in Boldr's brand voice — friendly, direct, premium.
   Opening: "Hi [Name], thanks for reaching out!"
   Never start with "Great question!" or "Dear Sir/Madam".
   Never promise timelines you cannot confirm from the KB.
5. PERSONA TAGGING: Tag using the 7-category system (raw_persona_tag) AND
   the 5-category competition system (competition_persona_tag).
6. ESCALATION: Flag requires_escalation: true for questions about MRI/magnetic safety,
   shock ratings, discontinued model servicing, corporate bulk orders (5+ units),
   angry customers, logo engraving, or any question not in the KB.

═══════════════════════════════════════════
TIER 1 — RATE CARDS — AUTHORITATIVE PRICING
Use these for ALL price and turnaround queries. Overrides FAQ and SOP.
═══════════════════════════════════════════
{kb_tier1_content}

═══════════════════════════════════════════
TIER 2 — FAQ AND PRODUCT REFERENCE
Use for specifications, materials, compatibility, Q&A.
═══════════════════════════════════════════
{kb_tier2_content}

═══════════════════════════════════════════
TIER 3 — BRAND VOICE AND PROCESS (no prices)
═══════════════════════════════════════════
{kb_tier3_content}

{gap_resolution_block}
```

### 7.3 Output JSON Schema

Claude must return ONLY this JSON — no markdown, no preamble.

```json
{
  "question_type": "engraving | servicing | materials_safety | strap_compatibility | product_general | order_status | knowledge_gap",
  "intent_summary": "One sentence summarising what the customer is actually asking",
  "answerable": true,
  "confidence": "high | medium | low",
  "raw_persona_tag": "health_conscious | gifter | enthusiast | niche_buyer | prospect | owner_aftercare | transactional",
  "competition_persona_tag": "Health-Conscious Buyer | Gifter | Enthusiast/Collector | Active/Outdoor Buyer | Sustainability Advocate | null",
  "theme": "materials | sustainability | sizing | gifting | servicing | order | product_specs | other",
  "marketing_signal": false,
  "marketing_signal_reason": "null or brief reason why this question is a marketing opportunity",
  "kb_sources_used": ["KB-ENG-001", "KB-FAQ-010"],
  "requires_escalation": false,
  "escalation_reason": null,
  "draft_reply": "Hi [Name], thanks for reaching out! ...",
  "gap_summary": null
}
```

**When `answerable: false`:**
```json
{
  "answerable": false,
  "draft_reply": null,
  "gap_summary": "Customer is asking about magnetic field resistance for MRI environments. This is not covered in any current KB document. Requires supplier confirmation."
}
```

**When `question_type: order_status`:**
```json
{
  "question_type": "order_status",
  "answerable": false,
  "draft_reply": null,
  "gap_summary": null,
  "order_escalation_note": "Customer is asking about order [order_id if mentioned]. Requires Shopify login to check status."
}
```

---

## 8. Persona Mapping

### 8.1 Raw 7-category tags (from ticket data)

| raw_persona_tag | Description | Primary question types |
|---|---|---|
| health_conscious | BPA, nickel, hypoallergenic, EU REACH, kids safety | materials_safety |
| gifter | Engraving, gift wrapping, personalisation, occasions | engraving, product_general |
| enthusiast | Strap swaps, compatibility, collector questions, specs | strap_compatibility, product_general |
| niche_buyer | Unusual/unanswerable: MRI, altitude, resale, shock ratings | knowledge_gap |
| prospect | Pre-purchase: return policy, warranty, model comparison | product_general |
| owner_aftercare | Post-purchase servicing, repair, battery, regulation | servicing |
| transactional | Order tracking, refunds, cancellations, shipping issues | order_status |

### 8.2 Competition persona mapping (for marketing brief output)

| raw_persona_tag | competition_persona_tag | Mapping rule |
|---|---|---|
| health_conscious | Health-Conscious Buyer | Direct match |
| gifter | Gifter | Direct match |
| enthusiast | Enthusiast/Collector | Direct match |
| niche_buyer (sustainability keywords*) | Sustainability Advocate | Keywords: vegan, recycling, carbon, eco, sustainable |
| niche_buyer (outdoor keywords*) | Active/Outdoor Buyer | Keywords: trail, altitude, shock, MRI, extreme, hiking |
| prospect | null (exclude from competition brief) | Tag as prospect, use for internal analysis only |
| owner_aftercare | null (exclude from competition brief) | Tag for retention analytics |
| transactional | null (auto-escalate, never reaches persona tagging) | Routed before persona step |

---

## 9. Routing Logic (n8n Switch Node)

Three branches in strict priority order:

### Branch 1: Order status (evaluate first)
**Condition:** `{{$json.question_type}} === 'order_status'`

Actions:
- Log to `tickets` table with `order_escalated: true`
- Send Slack alert to CS team:
  ```
  🛍️ ORDER QUERY — [customer_name] ([customer_email])
  Subject: [subject]
  Intent: [intent_summary]
  → Shopify Admin: https://admin.shopify.com/store/boldr/orders
  ```
- Do NOT create a Gmail draft

### Branch 2: Answerable (KB hit)
**Condition:** `{{$json.answerable}} === true`

Actions:
- Create Gmail draft in support inbox with `draft_reply` as body
- Subject: `Re: [original subject]`
- Log to `tickets` table with `answerable: true`, `draft_reply`, `kb_sources_used`
- Optional: Slack notification "Draft ready for [subject]" with Gmail deeplink

### Branch 3: Knowledge gap
**Condition:** `{{$json.answerable}} === false AND question_type !== 'order_status'`

Actions:
- Insert into `knowledge_gaps` table with `status: pending`
- Log to `tickets` with `gap_flag: true`
- Send Slack alert to CS team:
  ```
  🔍 KNOWLEDGE GAP — [raw_persona_tag] | Theme: [theme]
  Customer: [customer_name] ([customer_email])
  Question: [gap_summary]
  Marketing signal: [marketing_signal] — [marketing_signal_reason]
  → Submit answer: [n8n webhook form URL]
  ```

---

## 10. n8n Workflow Specifications

### Workflow 1: Real-time email processing

| # | Node type | Name | Config |
|---|---|---|---|
| 1 | Gmail Trigger | Watch inbox | Poll every 1 min; filter: unread, label: cs-inbox |
| 2 | Code | Build KB context | SELECT all kb_chunks ORDER BY priority_rank; assemble system prompt string |
| 3 | HTTP Request | Claude API | POST api.anthropic.com/v1/messages; model: claude-sonnet-4-6; max_tokens: 1000 |
| 4 | Code | Parse response | JSON.parse(content[0].text); validate required fields |
| 5 | Switch | Route by type | 3 branches: order_status / answerable:true / answerable:false |
| 6a | Gmail | Create draft | Branch 2: create draft with reply body |
| 6b | Supabase | Log ticket | All branches: INSERT into tickets |
| 6c | Supabase | Log gap | Branch 3: INSERT into knowledge_gaps |
| 7 | Slack | Alert CS | Branches 1 and 3: send formatted Slack message |

### Workflow 2: Gap resolution (webhook trigger)

| # | Node type | Name | Config |
|---|---|---|---|
| 1 | Webhook | Receive gap answer | POST /webhook/gap-resolve; fields: gap_id, human_answer, cs_name |
| 2 | Supabase | Fetch gap record | SELECT * FROM knowledge_gaps WHERE gap_id = $gap_id |
| 3 | HTTP Request | Claude API | Prompt: "Draft a KB entry from this Q&A. Format: Q: [question] A: [answer]. Be factual, concise, Boldr brand voice." |
| 4 | Supabase | Update gap | SET human_answer, kb_draft_text, kb_draft_status = 'pending_approval' |
| 5 | Slack | Send for approval | Post kb_draft_text with Approve / Edit buttons (callback to webhook) |
| 6 | Webhook | Approval callback | On Approve: INSERT kb_chunks + UPDATE gap status = 'resolved' |

**KB entry inserted into kb_chunks:**
```json
{
  "chunk_id": "KB-GAP-{gap_id}",
  "source": "gap_resolution",
  "category": "{theme from gap record}",
  "content": "Q: {question_summary}\nA: {human_answer}",
  "priority_rank": 2,
  "approved_by": "{cs_name}",
  "approved_at": "{timestamp}"
}
```

### Workflow 3: Weekly theme clustering

**Schedule:** Every Monday 08:00 SGT (`0 0 * * 1` UTC)

| # | Node type | Config |
|---|---|---|
| 1 | Schedule Trigger | Monday 8am SGT |
| 2 | Supabase | SELECT * FROM knowledge_gaps WHERE created_at > NOW() - INTERVAL '7 days' |
| 3 | Supabase | SELECT question_type, theme, persona_tag, marketing_signal FROM tickets WHERE created_at > NOW() - INTERVAL '7 days' |
| 4 | HTTP Request | Claude API — cluster prompt (see below) |
| 5 | Supabase | INSERT into theme_clusters |
| 6 | Slack | Post weekly digest to #cs-team |

**Clustering prompt:**
```
You are a customer intelligence analyst for Boldr Supply Co.
Below are the customer questions from the past 7 days.

Group them by theme. For each theme:
- Theme name
- Ticket count
- Buyer personas represented
- Whether it's a marketing signal (yes/no)
- One-line recommended action

Also flag: which themes appeared 3+ times (strong signals).

Return JSON only:
{
  "week_summary": "...",
  "themes": [
    {
      "theme": "...",
      "count": 0,
      "personas": [],
      "marketing_signal": false,
      "recommended_action": "..."
    }
  ],
  "top_signals": []
}

TICKET DATA:
{tickets_and_gaps_json}
```

### Workflow 4: Monthly marketing brief

**Schedule:** First Monday of each month, 08:00 SGT

Pulls 4 weeks of theme_clusters. Claude call with `web_search` tool enabled.

**Brief prompt:**
```
You are a marketing analyst for Boldr Supply Co., a Singapore titanium watch micro-brand.

Internal data from the past month's customer support tickets:
{theme_clusters_json}

Your task:
1. Write a one-page marketing brief titled "What customers are asking that is not on our product pages"
2. Tag each insight with the relevant buyer persona (from: Health-Conscious Buyer, Gifter, Enthusiast/Collector, Active/Outdoor Buyer, Sustainability Advocate)
3. For each insight, state: Is this a Boldr-specific gap or a market-wide concern?
4. Use web search to check Reddit (r/Watches, r/WatchHorology), WatchUSeek forums, and competitor reviews for external validation on the top 3 themes
5. For each of the 3 validated themes: "Is this Boldr-specific or market-wide? What should Boldr do?"
6. End with 3 concrete recommendations (product page update / campaign angle / new FAQ entry)

Return structured markdown.
```

---

## 11. Demo Scenarios (using sample ticket data)

### Scenario A — Answerable (Health-Conscious Buyer)

Use ticket TKT-1048: Vikram Allen asking "Is the watch strap BPA-free? I'm buying this for my young daughter."

Expected flow:
- Claude classifies: `question_type: materials_safety`, `answerable: true`, `persona: health_conscious`
- KB source: Tier 1 rate card (strap catalogue) + Tier 2 FAQ BPA entry
- Draft reply confirms: FKM rubber strap is BPA-free and nickel-free; EU REACH compliant
- Gmail draft created → CS approves → sent in <10 seconds from receipt
- Logged to Supabase with `marketing_signal: true` (health-conscious parent = target persona)

### Scenario B — False Gap Caught (demonstrates AI > manual process)

Use ticket TKT-1070: Mila Yeo asking "Can you engrave in Arabic?"

The ticket is flagged as `knowledge_gap` in the sample data — meaning a human CS agent missed the answer.

Expected flow:
- Claude classifies: `question_type: engraving`, `answerable: true`
- KB source: Tier 1 rate card (Arabic script engraving: SGD 3/char, up to 15 chars)
- Draft reply answers correctly — the AI found it, the human didn't
- **This is the strongest demo moment**: "The AI found the answer that the CS team missed."

### Scenario C — True Gap → Self-Improving Loop

Use ticket TKT-1046: Lily Shah asking "Is the movement resistant to magnetic fields? I work near MRI equipment."

Expected flow:
- Claude classifies: `question_type: knowledge_gap`, `answerable: false`
- gap_summary: "Customer asking about magnetic field / MRI resistance. Not in current KB. Requires supplier confirmation."
- Slack alert to CS team with gap context
- CS consults supplier, submits answer via n8n form (webhook)
- Claude auto-drafts KB entry: "Q: Is the Boldr movement resistant to magnetic fields / MRI environments? A: [human-provided answer]"
- CS approves in Slack → INSERT into kb_chunks
- Next customer asking the same question gets an instant accurate reply

### Scenario D — Order status (auto-escalate)

Use ticket TKT-1056: Lucas Mehta, "My tracking number DHL9697354961 hasn't updated in 5 days."

Expected flow:
- Claude classifies: `question_type: order_status` immediately
- No KB search attempted
- CS Slack alert with Shopify deeplink
- Ticket logged with `order_escalated: true`

---

## 12. API Call Structure (n8n HTTP Request node)

```javascript
// Build request body in n8n Code node before HTTP Request
const kbContent = $('Build KB context').item.json.kb_system_prompt;
const email = $('Gmail Trigger').item.json;

const requestBody = {
  model: "claude-sonnet-4-6",
  max_tokens: 1000,
  system: kbContent,
  messages: [
    {
      role: "user",
      content: `Process this customer enquiry and return JSON only.

Customer name: ${email.from.name || 'Unknown'}
Customer email: ${email.from.email}
Subject: ${email.subject}
Message:
${email.text || email.snippet}

Return the JSON schema specified in your instructions. No other text.`
    }
  ]
};

return { json: requestBody };
```

**Parse the response:**
```javascript
// In Code node after HTTP Request
const response = $input.item.json;
const content = response.content[0].text;

let parsed;
try {
  // Strip markdown code fences if present
  const clean = content.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
  parsed = JSON.parse(clean);
} catch (e) {
  // Fallback: treat as gap
  parsed = {
    question_type: 'knowledge_gap',
    answerable: false,
    gap_summary: 'Claude response parse error — manual review required',
    parse_error: content.substring(0, 200)
  };
}

return { json: parsed };
```

---

## 13. KB Builder Script

Run `scripts/build_kb.py` to initialise the kb_chunks table from source files.
See `scripts/build_kb.py` for full implementation.

Required environment variables:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
```

The script:
1. Reads all CSV rate cards and formats as structured text
2. Reads and parses FAQ PDF into Q&A pairs
3. Reads and parses product reference PDF into model cards
4. Extracts tone/process guidance from SOP (strips all pricing)
5. INSERTs all chunks into kb_chunks with correct priority_rank
6. Writes `kb_preview.txt` — the full formatted system prompt block for inspection

Re-run this script whenever source documents are updated.

---

## 14. Project File Structure

```
boldr-intelligence-engine/
├── PRODUCT.md                    ← this file
├── README.md                     ← competition submission + public docs
├── scripts/
│   ├── build_kb.py               ← KB initialisation (run once + on doc updates)
│   ├── seed_demo_tickets.py      ← load sample tickets for demo
│   └── kb_preview.txt            ← generated: inspect formatted KB before deploy
├── n8n/
│   ├── workflow_1_email.json     ← import into n8n
│   ├── workflow_2_gap_resolve.json
│   ├── workflow_3_weekly_cluster.json
│   └── workflow_4_monthly_brief.json
├── supabase/
│   └── schema.sql                ← all CREATE TABLE statements (from Section 5)
├── prompts/
│   ├── system_prompt_template.txt   ← Workflow 1 system prompt
│   ├── kb_entry_drafter.txt         ← Workflow 2 Claude prompt
│   ├── theme_clustering.txt         ← Workflow 3 Claude prompt
│   └── marketing_brief.txt          ← Workflow 4 Claude prompt
├── demo/
│   ├── index.html                ← demo UI (submit a ticket, see result)
│   └── personas/                 ← pre-filled demo ticket payloads
│       ├── scenario_a_bpa_question.json
│       ├── scenario_b_false_gap.json
│       ├── scenario_c_true_gap.json
│       └── scenario_d_order_status.json
├── uploads/                      ← original source documents (read-only)
│   ├── 01_customer_tickets.csv
│   ├── 03a_rate_card_engraving.csv
│   ├── 03b_rate_card_servicing.csv
│   ├── 04_faq_document.pdf
│   ├── 05a_SOP.pdf
│   └── 05b_product_reference.pdf
└── screenshots/                  ← n8n canvas, Supabase, demo UI (for repo)
```

---

## 15. Critical Constraints (DO NOT)

| ❌ Don't | ✅ Do instead |
|---|---|
| Auto-send any email to a customer | Always create a Gmail draft; human clicks Send |
| Use SOP for pricing | Use rate cards (Tier 1) exclusively for pricing |
| Hallucinate an answer when KB has no match | Set answerable: false; return gap_summary |
| Attempt to answer order status queries from KB | Immediately flag and route to CS with Shopify link |
| Use a fixed/hardcoded system prompt | Assemble dynamically from kb_chunks so new entries are immediately live |
| Quote a single "full service" price | Quote both tiers: Standard SGD 160 / Premium SGD 220 |
| Assume leather straps are hypoallergenic | They are BPA-free but NOT hypoallergenic — state this clearly |
| Quote engraving max as 40 characters | Max is 60 characters (40 at flat rate, 41–60 at SGD 1.50/char) |
| Recommend Mesh Bracelet for Expedition | Mesh bracelet is Journey ONLY |
| Recommend Titanium Bracelet for Journey | Titanium bracelet is Expedition ONLY |

---

## 16. Build Sequence for Claude Code

Execute in this order. Each step depends on the previous.

```
Step 1: Run supabase/schema.sql in Supabase SQL editor
Step 2: Set environment variables (SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY)
Step 3: Run scripts/build_kb.py — verify kb_preview.txt looks correct
Step 4: Run scripts/seed_demo_tickets.py — load sample data for demo
Step 5: Import n8n/workflow_1_email.json into n8n — configure Gmail OAuth2 credential
Step 6: Test Workflow 1 with Scenario A (BPA question) — confirm Supabase log + Gmail draft
Step 7: Test Workflow 1 with Scenario B (false gap) — confirm AI catches it
Step 8: Test Workflow 1 with Scenario C (true gap) — confirm Slack alert fires
Step 9: Test Workflow 1 with Scenario D (order status) — confirm Shopify escalation
Step 10: Import and configure Workflow 2 (gap resolver webhook)
Step 11: End-to-end test: submit gap answer → confirm KB entry appears in kb_chunks
Step 12: Import Workflows 3 and 4 (scheduled — test with manual trigger first)
Step 13: Build demo/index.html UI for competition presentation
Step 14: Add /screenshots to repo
Step 15: Activate all workflows in n8n (Published state)
```

---

*Document version: 1.0 | Generated: 17 May 2026 | Based on files: 03a, 03b, 04, 05a, 05b, 01_customer_tickets*
*Next update: after Workflow 1 testing (update with confirmed webhook URLs and Supabase project ID)*
