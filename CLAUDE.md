# CLAUDE.md — Boldr Customer Intelligence Engine
## Instructions for Claude Code

> Read PRODUCT.md first. This file tells you HOW to build; PRODUCT.md tells you WHAT to build.
> When these files conflict, PRODUCT.md wins.

---

## Project Context

You are building the Boldr Customer Intelligence Engine for Abel Choy's Echelon 2026 competition entry.
Deadline: Sunday 17 May 2026, 3pm SGT. Every decision should optimise for a working, demonstrable system.

The full specification is in PRODUCT.md. The knowledge base builder is in scripts/build_kb.py.

---

## Environment Setup

### Required tools
```bash
# Python dependencies
pip install pandas pypdf supabase python-dotenv

# Node (for n8n local testing if needed)
node --version  # should be >= 18
```

### Environment variables
Create a `.env` file in the project root:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
ANTHROPIC_API_KEY=your-anthropic-api-key
N8N_WEBHOOK_BASE=https://abelchoy-n8n.duckdns.org
```

---

## Step-by-Step Build Order

Follow these steps in sequence. Do not skip ahead.

### Step 1 — Database setup
```bash
# Copy the SQL schema from PRODUCT.md Section 5 into Supabase SQL editor
# Or run it via the Supabase CLI:
supabase db push  # if you have the schema in supabase/schema.sql
```

Verify by checking that these tables exist in Supabase:
- `kb_chunks`
- `tickets`
- `knowledge_gaps`
- `theme_clusters`
- `marketing_briefs`

### Step 2 — Build and load the knowledge base
```bash
# First: dry run to inspect output
python scripts/build_kb.py --dry-run

# Read scripts/kb_preview.txt carefully — verify:
# 1. All engraving prices match the rate card (not the SOP)
# 2. Full service shows SGD 160 (Standard) and SGD 220 (Premium)
# 3. Regulation service shows SGD 85 (not SGD 60)
# 4. Max engraving characters shown as 60 (not 40)
# 5. Mesh bracelet marked JOURNEY ONLY
# 6. Titanium bracelet marked EXPEDITION ONLY

# Once verified:
python scripts/build_kb.py
```

Verify in Supabase: `SELECT chunk_id, source, priority_rank FROM kb_chunks ORDER BY priority_rank;`
You should see 9 rows (2 rate cards + 1 product ref + 5 FAQ sections + 1 SOP).

### Step 3 — Build n8n Workflow 1 (email processing)

Import `n8n/workflow_1_email.json` into n8n, OR build manually with these nodes:

**Node 1: Gmail Trigger**
- Type: Gmail Trigger
- Event: Message Received
- Filters: Label = cs-inbox (or inbox), unread only
- Poll every: 1 minute

**Node 2: Build KB Context (Code node)**
```javascript
// Fetch all KB chunks from Supabase and assemble system prompt
const supabaseUrl = $env.SUPABASE_URL;
const supabaseKey = $env.SUPABASE_SERVICE_KEY;

const response = await fetch(
  `${supabaseUrl}/rest/v1/kb_chunks?select=content,priority_rank,source&order=priority_rank.asc`,
  {
    headers: {
      'apikey': supabaseKey,
      'Authorization': `Bearer ${supabaseKey}`
    }
  }
);
const chunks = await response.json();

// Separate by tier
const tier1 = chunks.filter(c => c.priority_rank === 1);
const tier2 = chunks.filter(c => c.priority_rank === 2 && c.source !== 'gap_resolution');
const tier3 = chunks.filter(c => c.priority_rank === 3);
const gaps  = chunks.filter(c => c.source === 'gap_resolution');

const sep = '═'.repeat(60);

let systemPrompt = `You are the AI customer service assistant for Boldr Supply Co., a premium Singapore-based titanium watch micro-brand.

YOUR TASK: Analyse the customer email and return a single JSON object (no other text, no markdown).

RULES:
1. PRICING: Always use Tier 1 (Rate Cards) for all prices and turnaround times. Never use the SOP for pricing — it is outdated.
2. HONESTY: If the answer is not in the knowledge base, set answerable: false. Do NOT guess or hallucinate. Return gap_summary instead.
3. ORDER QUERIES: If the email is about an order (tracking, refund, cancellation, wrong item, address change), set question_type: "order_status" immediately. Set answerable: false and draft_reply: null.
4. DRAFT REPLIES: Write in Boldr's brand voice — friendly, direct, premium. Opening: "Hi [Name], thanks for reaching out!"
5. PERSONA: Tag using both raw_persona_tag (7-category) and competition_persona_tag (5-category).

${sep}
TIER 1 — RATE CARDS — AUTHORITATIVE PRICING
${sep}
${tier1.map(c => c.content).join('\\n\\n')}

${sep}
TIER 2 — FAQ AND PRODUCT REFERENCE
${sep}
${tier2.map(c => c.content).join('\\n\\n')}

${sep}
TIER 3 — BRAND VOICE AND PROCESS (no prices)
${sep}
${tier3.map(c => c.content).join('\\n\\n')}

${gaps.length > 0 ? `${sep}
APPROVED KB ENTRIES FROM GAP RESOLUTION (treat as Tier 2)
${sep}
${gaps.map(c => c.content).join('\\n\\n')}` : ''}

RETURN THIS JSON SCHEMA EXACTLY (no other text):
{
  "question_type": "engraving|servicing|materials_safety|strap_compatibility|product_general|order_status|knowledge_gap",
  "intent_summary": "one sentence",
  "answerable": true,
  "confidence": "high|medium|low",
  "raw_persona_tag": "health_conscious|gifter|enthusiast|niche_buyer|prospect|owner_aftercare|transactional",
  "competition_persona_tag": "Health-Conscious Buyer|Gifter|Enthusiast/Collector|Active/Outdoor Buyer|Sustainability Advocate|null",
  "theme": "materials|sustainability|sizing|gifting|servicing|order|product_specs|other",
  "marketing_signal": false,
  "marketing_signal_reason": null,
  "kb_sources_used": [],
  "requires_escalation": false,
  "escalation_reason": null,
  "draft_reply": "Hi [Name], thanks for reaching out! ...",
  "gap_summary": null
}`;

return { json: { system_prompt: systemPrompt, chunk_count: chunks.length } };
```

**Node 3: Claude API (HTTP Request)**
- Method: POST
- URL: `https://api.anthropic.com/v1/messages`
- Headers:
  - `Content-Type: application/json`
  - `x-api-key: {{ $env.ANTHROPIC_API_KEY }}`
  - `anthropic-version: 2023-06-01`
- Body (JSON):
```json
{
  "model": "claude-sonnet-4-6",
  "max_tokens": 1000,
  "system": "{{ $('Build KB Context').item.json.system_prompt }}",
  "messages": [
    {
      "role": "user",
      "content": "Process this customer enquiry and return JSON only.\n\nCustomer name: {{ $('Gmail Trigger').item.json.from.name }}\nCustomer email: {{ $('Gmail Trigger').item.json.from.email }}\nSubject: {{ $('Gmail Trigger').item.json.subject }}\nMessage:\n{{ $('Gmail Trigger').item.json.text }}"
    }
  ]
}
```

**Node 4: Parse Claude Response (Code node)**
```javascript
const response = $input.item.json;
const rawText = response.content[0].text;

let parsed;
try {
  const clean = rawText.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
  parsed = JSON.parse(clean);
} catch (e) {
  parsed = {
    question_type: 'knowledge_gap',
    answerable: false,
    confidence: 'low',
    raw_persona_tag: 'niche_buyer',
    competition_persona_tag: null,
    theme: 'other',
    marketing_signal: false,
    marketing_signal_reason: null,
    kb_sources_used: [],
    requires_escalation: true,
    escalation_reason: 'Claude response parse error — manual review required',
    draft_reply: null,
    gap_summary: `Parse error. Raw response: ${rawText.substring(0, 300)}`
  };
}

// Add metadata from Gmail trigger
const gmail = $('Gmail Trigger').item.json;
parsed.customer_email = gmail.from?.email || '';
parsed.customer_name  = gmail.from?.name  || 'Customer';
parsed.email_subject  = gmail.subject || '';
parsed.received_at    = new Date().toISOString();
parsed.ticket_id      = `TKT-${Date.now()}`;

return { json: parsed };
```

**Node 5: Route (Switch node)**
- Routing mode: Rules
- Rule 1: `{{ $json.question_type }}` equals `order_status` → branch: Order Escalation
- Rule 2: `{{ $json.answerable }}` equals `true` → branch: Draft Reply
- Rule 3: (fallback) → branch: Knowledge Gap

**Node 6a: Create Gmail Draft (Gmail node — Draft Reply branch)**
- Operation: Create Draft
- To: `{{ $json.customer_email }}`
- Subject: `Re: {{ $json.email_subject }}`
- Body: `{{ $json.draft_reply }}`

**Node 6b: Log to Supabase tickets (all branches)**
- Operation: Insert
- Table: tickets
- Columns: map all fields from parsed Claude response

**Node 6c: Log to Supabase knowledge_gaps (Gap branch only)**
- Operation: Insert
- Table: knowledge_gaps
- gap_id: `GAP-{{ Date.now() }}`
- ticket_id: `{{ $json.ticket_id }}`
- question_summary: `{{ $json.gap_summary }}`
- theme: `{{ $json.theme }}`
- persona_tag: `{{ $json.raw_persona_tag }}`
- marketing_signal: `{{ $json.marketing_signal }}`

**Node 7: Slack Alert (Gap and Order branches)**
- Operation: Post Message
- Channel: #cs-team
- Message (Gap): `🔍 KNOWLEDGE GAP — {{ $json.raw_persona_tag }} | Theme: {{ $json.theme }}\nCustomer: {{ $json.customer_name }} ({{ $json.customer_email }})\nQuestion: {{ $json.gap_summary }}\nMarketing signal: {{ $json.marketing_signal }}\n→ Submit answer: {{ $env.N8N_WEBHOOK_BASE }}/webhook/gap-resolve-form`
- Message (Order): `🛍️ ORDER QUERY — {{ $json.customer_name }} ({{ $json.customer_email }})\nSubject: {{ $json.email_subject }}\nIntent: {{ $json.intent_summary }}\n→ Shopify: https://admin.shopify.com`

### Step 4 — Test Workflow 1 with four scenarios

Before activating, test each scenario manually using the webhook or Gmail:

```bash
# Test scenarios are in demo/personas/
# Each is a JSON payload mimicking what Claude returns for that ticket type

# Scenario A — BPA question (should: draft reply, gmail draft created)
# Ticket: "Is the watch strap BPA-free? Buying for my young daughter."
# Expected: answerable: true, persona: health_conscious, draft created

# Scenario B — False gap caught (Arabic engraving — answerable from rate card)
# Ticket: "Can you engrave in Arabic? I want my father's name in Arabic."
# Expected: answerable: true, KB source: KB-ENG-001, draft created
# Note: sample data tagged this as a gap — AI should catch it

# Scenario C — True gap (MRI magnetic resistance)
# Ticket: "Is the movement resistant to magnetic fields? I work near MRI equipment."
# Expected: answerable: false, gap_summary set, Slack alert fires

# Scenario D — Order status (auto-escalate)
# Ticket: "My tracking number hasn't updated in 5 days."
# Expected: question_type: order_status, no KB search, Shopify Slack alert
```

### Step 5 — Build n8n Workflow 2 (gap resolver)

Webhook URL: `POST /webhook/gap-resolve`
Expected payload: `{ "gap_id": "GAP-xxx", "human_answer": "...", "cs_name": "..." }`

Claude prompt for KB entry drafting:
```
You are drafting a Knowledge Base entry for Boldr Supply Co.

A customer asked: {question_summary}
The CS team's verified answer: {human_answer}

Draft a concise FAQ entry in this exact format:
Q: [rephrase the customer question clearly]
A: [the verified answer, in Boldr's brand voice — friendly, direct, factual]

Return ONLY the formatted Q&A entry. No preamble, no explanation.
```

### Step 6 — Build n8n Workflows 3 and 4 (scheduled)

Both use schedule triggers. Test by manually executing the nodes first.

Workflow 3 (weekly): Pull last 7 days tickets + gaps → Claude clustering → INSERT theme_clusters → Slack digest.
Workflow 4 (monthly): Pull 4 weeks theme_clusters → Claude brief with web_search → email/store brief.

---

## Common Errors and Fixes

| Error | Cause | Fix |
|---|---|---|
| Claude returns non-JSON | Model added preamble | The parse node strips ` ```json ` fences — check regex |
| `answerable: true` but draft is null | Schema mismatch | Verify Claude output schema matches exactly |
| SOP prices appearing in draft | KB assembly wrong | Check priority_rank ordering; Tier 1 must appear first |
| Mesh bracelet suggested for Expedition | KB chunk not loaded | Run `python scripts/build_kb.py` and verify KB-PRD-001 in Supabase |
| Engraving quoted as SGD 35 for 21-40 chars | SOP loaded as Tier 1 | SOP must have priority_rank 3, not 1 |
| All tickets going to gap branch | Parse error in Node 4 | Log rawText before parse; check Claude API response structure |
| Supabase connection fails | Wrong key type | Use service_role key, not anon key, for server-side writes |

---

## Testing the Self-Improving Loop (Scenario C end-to-end)

1. Submit the MRI question ticket → verify Slack alert fires + knowledge_gaps row created
2. POST to `/webhook/gap-resolve`:
   ```json
   {
     "gap_id": "GAP-xxx",
     "human_answer": "The Miyota movements used in Boldr watches are not ISO 764 certified for magnetic resistance. We recommend keeping the watch away from strong magnetic fields. If you work near MRI equipment, we suggest consulting with your workplace safety officer.",
     "cs_name": "CS Team"
   }
   ```
3. Verify Slack receives the KB draft for approval
4. Simulate approval (POST to `/webhook/gap-approve` with gap_id)
5. Check Supabase kb_chunks: new row with source = gap_resolution should appear
6. Submit the MRI question again → Claude should now answer it correctly from KB

---

## File Locations Reference

| File | Purpose |
|---|---|
| `PRODUCT.md` | Full product specification |
| `CLAUDE.md` | This file — Claude Code instructions |
| `scripts/build_kb.py` | KB initialisation (run first) |
| `scripts/kb_preview.txt` | Generated preview of formatted KB |
| `supabase/schema.sql` | All CREATE TABLE statements |
| `n8n/workflow_1_email.json` | Main workflow (import into n8n) |
| `n8n/workflow_2_gap_resolve.json` | Gap resolution webhook workflow |
| `n8n/workflow_3_weekly_cluster.json` | Weekly theme clustering |
| `n8n/workflow_4_monthly_brief.json` | Monthly marketing brief |
| `demo/index.html` | Demo UI for competition |
| `uploads/` | Original source documents (read-only) |

---

*Last updated: 17 May 2026 | For the Echelon 2026 Boldr Challenge*
