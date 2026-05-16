#!/usr/bin/env python3
"""
build_kb.py — Boldr Customer Intelligence Engine
KB Initialisation Script

Reads all source documents, formats them into structured text chunks,
and inserts into Supabase kb_chunks table.

Run once on first deploy, then re-run whenever source documents are updated.

Usage:
    pip install pandas pypdf supabase python-dotenv
    python build_kb.py

    # Dry run (writes kb_preview.txt, does NOT write to Supabase):
    python build_kb.py --dry-run

    # Preview only, no Supabase write:
    python build_kb.py --preview

Environment variables (set in .env or shell):
    SUPABASE_URL=https://your-project.supabase.co
    SUPABASE_SERVICE_KEY=your-service-role-key

Source files expected in ./uploads/ (adjust SOURCE_DIR if different):
    03a_rate_card_engraving.csv
    03b_rate_card_servicing.csv
    04_faq_document.pdf
    05b_product_reference.pdf
    05a_SOP.pdf
"""

import os
import sys
import json
import argparse
import textwrap
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SOURCE_DIR = Path("./uploads")           # where source documents live
OUTPUT_PREVIEW = Path("./scripts/kb_preview.txt")  # human-readable preview

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: RATE CARDS (authoritative pricing)
# ─────────────────────────────────────────────────────────────────────────────

def build_engraving_chunk() -> dict:
    """
    Reads 03a_rate_card_engraving.csv and formats as an authoritative pricing block.
    Returns a kb_chunks row dict.
    """
    path = SOURCE_DIR / "03a_rate_card_engraving.csv"
    df = pd.read_csv(path)

    lines = [
        "[ENGRAVING RATE CARD — AUTHORITATIVE — use for ALL engraving price and character limit queries]",
        "Source: 03a_rate_card_engraving.csv | Last verified: Jan 2026",
        "",
    ]

    for _, row in df.iterrows():
        price = row["price_sgd"]
        # Format price: if 0, show "Free (conditions apply)"
        if float(price) == 0:
            price_str = "Free (conditions apply)"
        elif float(price) == int(float(price)):
            price_str = f"SGD {int(float(price))}"
        else:
            price_str = f"SGD {float(price)}"

        lines.append(f"• {row['service']}: {price_str} — {row['notes']}")

    lines += [
        "",
        "KEY RULES (for reply drafting):",
        "• Max characters on caseback: 60 total (not 40 — SOP is wrong on this)",
        "• Engraving correction: Free within 1 hour of order; SGD 15 after 1 hour",
        "• Logo/artwork: customer must supply vector file; flag for team review before confirming",
        "• After production starts: NO changes possible",
        "• Engraved items: NON-RETURNABLE unless manufacturing defect",
    ]

    return {
        "chunk_id": "KB-ENG-001",
        "source": "rate_card_engraving",
        "category": "engraving",
        "content": "\n".join(lines),
        "priority_rank": 1,
        "approved_by": "system_init",
        "approved_at": datetime.utcnow().isoformat(),
    }


def build_servicing_chunk() -> dict:
    """
    Reads 03b_rate_card_servicing.csv and formats as an authoritative pricing block.
    Returns a kb_chunks row dict.
    """
    path = SOURCE_DIR / "03b_rate_card_servicing.csv"
    df = pd.read_csv(path)

    lines = [
        "[SERVICING RATE CARD — AUTHORITATIVE — use for ALL servicing price and turnaround queries]",
        "Source: 03b_rate_card_servicing.csv | Last verified: Jan 2026",
        "",
    ]

    for _, row in df.iterrows():
        price = int(row["price_sgd"])
        turnaround = str(row["turnaround_days"]).strip()
        includes = str(row["includes"]).strip() if pd.notna(row["includes"]) else ""
        notes = str(row["notes"]).strip() if pd.notna(row["notes"]) else ""

        lines.append(f"• {row['service_tier']}: SGD {price} | Turnaround: {turnaround} days")
        if includes:
            lines.append(f"  Includes: {includes}")
        if notes:
            lines.append(f"  Notes: {notes}")

    lines += [
        "",
        "KEY RULES (for reply drafting):",
        "• Full Service has TWO tiers: Standard (SGD 160) and Premium (SGD 220) — always mention both",
        "• Premium Full Service INCLUDES 12-month service warranty",
        "• Service Warranty Extension (SGD 30) must be purchased at time of service",
        "• International customers pay inbound shipping; Boldr covers insured return (SGD 25 surcharge)",
        "• Older/discontinued models: check with team before confirming — parts may not be available",
        "• Regulation Service is for automatic movements ONLY (not quartz/battery)",
    ]

    return {
        "chunk_id": "KB-SVC-001",
        "source": "rate_card_servicing",
        "category": "servicing",
        "content": "\n".join(lines),
        "priority_rank": 1,
        "approved_by": "system_init",
        "approved_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: PRODUCT REFERENCE
# ─────────────────────────────────────────────────────────────────────────────

def build_product_specs_chunk() -> dict:
    """
    Builds the product reference chunk from 05b_product_reference.pdf.

    NOTE FOR CLAUDE CODE:
    This function uses hardcoded content extracted from the PDF during analysis.
    If the product reference PDF changes, re-extract with:
        from pypdf import PdfReader
        r = PdfReader("uploads/05b_product_reference.pdf")
        text = "\n".join(p.extract_text() for p in r.pages)
        print(text)
    Then update the content strings below.
    """
    content = textwrap.dedent("""
    [PRODUCT REFERENCE — BOLDR CURRENT MODELS — Jan 2026]
    Source: 05b_product_reference.pdf

    ═══════════════════════════════════
    EXPEDITION TITANIUM | SGD 485 | SKU: BLD-EXP-TI-40
    ═══════════════════════════════════
    Case: 40mm diameter, 11.5mm thick, Grade 5 Titanium (Ti-6Al-4V), brushed + polished finish
    Crystal: Sapphire with anti-reflective coating
    Movement: Miyota 9015 automatic, 42-hour power reserve, +/-10 seconds/day
    Water resistance: 100m (10ATM) — safe for swimming; NOT for diving
    Lume: Super-LumiNova C3 — non-radioactive, ISO 3157 compliant
    Weight: 68g (no strap)
    Lug width: 20mm — fits ALL standard 20mm third-party straps
    Included strap: 20mm FKM rubber (black)
    Strap options: FKM rubber, Nylon NATO, Titanium bracelet, Leather
    Dial colours: Slate Grey, Forest Green, Midnight Blue, Sandstone
    Safety: BPA-free: YES | Nickel-free: YES | Hypoallergenic: YES | EU REACH: YES
    Warranty: 2 years on movement
    Availability: IN STOCK

    ═══════════════════════════════════
    JOURNEY TITANIUM | SGD 395 | SKU: BLD-JRN-TI-38
    ═══════════════════════════════════
    Case: 38mm diameter, 10.8mm thick, Grade 2 Titanium (commercially pure), full brushed
    Crystal: Sapphire with anti-reflective coating
    Movement: Miyota 6T33 automatic, 40-hour power reserve, +/-15 seconds/day
    Water resistance: 50m (5ATM) — SPLASH RESISTANT ONLY; NOT safe for swimming
    Lume: Super-LumiNova BGW9 — non-radioactive, ISO 3157 compliant
    Weight: 58g (no strap)
    Lug width: 20mm — fits ALL standard 20mm third-party straps
    Included strap: 20mm Nylon NATO (olive)
    Strap options: Nylon NATO, FKM rubber, Leather, Mesh bracelet
    Dial colours: Ivory White, Charcoal, Terracotta, Ocean Blue
    Safety: BPA-free: YES | Nickel-free: YES | Hypoallergenic: YES | EU REACH: YES
    Warranty: 2 years on movement
    Availability: IN STOCK

    ═══════════════════════════════════
    EXPEDITION EMBER LIMITED EDITION | SGD 595 | SKU: BLD-EXP-TI-40-LE
    ═══════════════════════════════════
    Case: 40mm, Grade 5 Titanium, PVD bronze coating, brushed
    Movement: Miyota 9015 automatic, 42-hour power reserve
    Dial: Burnt Orange only
    Included strap: 20mm leather strap (cognac)
    Safety: BPA-free: YES | Nickel-free: YES | Hypoallergenic: NO (leather strap not hypoallergenic)
    ⚠️ AVAILABILITY: SOLD OUT — direct to waitlist: boldr.co/waitlist
    ⚠️ Do NOT promise a restock date. Do NOT suggest it will be back in stock.

    ═══════════════════════════════════
    STRAP CATALOGUE — ALL MODELS (20mm lug width)
    ═══════════════════════════════════
    FKM Rubber (Black):  SGD 35 | BPA-free: YES | Nickel-free: YES | All models
    FKM Rubber (Navy):   SGD 35 | BPA-free: YES | Nickel-free: YES | All models
    FKM Rubber (Olive):  SGD 35 | BPA-free: YES | Nickel-free: YES | All models
    FKM Rubber (Red):    SGD 35 | BPA-free: YES | Nickel-free: YES | All models
    Nylon NATO (Olive):  SGD 25 | BPA-free: YES | All models
    Nylon NATO (Black):  SGD 25 | BPA-free: YES | All models
    Nylon NATO (Tan):    SGD 25 | BPA-free: YES | All models
    Leather (Brown):     SGD 55 | BPA-free: YES | Hypoallergenic: NO | All models
    Leather (Black):     SGD 55 | BPA-free: YES | Hypoallergenic: NO | All models
    Mesh Bracelet (Silver): SGD 75  | BPA-free: YES | JOURNEY ONLY ⚠️
    Titanium Bracelet:   SGD 145 | BPA-free: YES | EXPEDITION ONLY ⚠️

    ⚠️ STRAP SAFETY SUMMARY:
    - FKM rubber + Nylon NATO: fully BPA-free AND nickel-free — safe for sensitive skin
    - Leather straps: BPA-free BUT NOT hypoallergenic — some customers with sensitivities may react
    - Mesh bracelet: 316L stainless steel — trace nickel content present; NOT recommended for severe nickel allergy

    ═══════════════════════════════════
    QUICK ANSWER REFERENCE
    ═══════════════════════════════════
    "Is the strap BPA-free?" → Yes for all FKM rubber and nylon. Leather is BPA-free but not hypoallergenic.
    "Is it hypoallergenic?" → Yes for titanium case + FKM/nylon straps. Leather: NO.
    "What lug width?" → 20mm — fits all standard 20mm third-party straps.
    "Can I swim with it?" → Expedition YES (100m). Journey: splash resistant ONLY, not for swimming.
    "Is the lume safe?" → Yes — Super-LumiNova, non-radioactive, ISO 3157 compliant.
    "What is the warranty?" → 2 years on movement. Does NOT cover physical damage, water damage, strap wear.
    "Is the Ember available?" → No — sold out. Direct to waitlist: boldr.co/waitlist.
    "Expedition vs Journey?" → Expedition: 40mm, rugged, 100m WR, Grade 5 Ti. Journey: 38mm, slim, everyday, 50m, Grade 2 Ti.
    "Mesh bracelet on Expedition?" → NOT compatible. Mesh bracelet is JOURNEY ONLY.
    "Titanium bracelet on Journey?" → NOT compatible. Titanium bracelet is EXPEDITION ONLY.
    """).strip()

    return {
        "chunk_id": "KB-PRD-001",
        "source": "product_reference",
        "category": "product_specs",
        "content": content,
        "priority_rank": 2,
        "approved_by": "system_init",
        "approved_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: FAQ
# ─────────────────────────────────────────────────────────────────────────────

def build_faq_chunks() -> list[dict]:
    """
    Builds FAQ chunks from 04_faq_document.pdf.
    Each thematic section becomes one chunk for clean categorisation.

    NOTE FOR CLAUDE CODE:
    The FAQ content below was extracted from the PDF during analysis.
    To re-extract if the PDF changes:
        from pypdf import PdfReader
        r = PdfReader("uploads/04_faq_document.pdf")
        for i, page in enumerate(r.pages):
            print(f"--- PAGE {i+1} ---")
            print(page.extract_text())
    """

    faq_sections = [
        {
            "chunk_id": "KB-FAQ-001",
            "category": "materials_safety",
            "title": "FAQ — Materials & Safety",
            "content": textwrap.dedent("""
            [FAQ — MATERIALS & SAFETY]

            Q: Are Boldr watch straps BPA-free?
            A: Yes. All Boldr FKM rubber and silicone straps are 100% BPA-free. This applies to all current strap SKUs. The leather and nylon NATO straps do not contain BPA by composition.

            Q: What grade of titanium is used in the Expedition case?
            A: The Expedition uses Grade 5 Titanium (Ti-6Al-4V) — the aerospace-grade alloy, approximately 45% lighter than stainless steel and significantly more corrosion-resistant. The Journey uses Grade 2 (commercially pure titanium), slightly softer but very durable.

            Q: Is the watch safe for children?
            A: The Expedition and Journey are designed for adults. However, all materials are EU REACH and RoHS compliant (European safety standards for hazardous substances). The rubber straps are BPA-free and non-toxic. We recommend adult supervision for children wearing any watch.

            Q: Do the straps contain nickel?
            A: FKM rubber and nylon NATO straps are nickel-free. The metal buckle on leather straps is Grade 5 titanium (also nickel-free). The mesh bracelet uses 316L stainless steel — trace nickel is present (as with all stainless steel). If you have a severe nickel allergy, we recommend the rubber or NATO strap options.

            Q: Is the luminous material on the dial safe?
            A: Yes. Boldr uses Super-LumiNova (BGW9 or C3 grade depending on model) — a non-radioactive photoluminescent pigment compliant with ISO 3157. Completely safe for everyday wear.

            Q: Does the watch meet EU safety standards?
            A: Yes. All Boldr watches are EU REACH compliant and RoHS compliant. Documentation available upon request.
            """).strip(),
        },
        {
            "chunk_id": "KB-FAQ-002",
            "category": "engraving",
            "title": "FAQ — Engraving",
            "content": textwrap.dedent("""
            [FAQ — ENGRAVING]
            NOTE: For all prices and character limits, refer to the Engraving Rate Card (Tier 1). FAQ prices below are informational.

            Q: Can I get the caseback engraved?
            A: Yes. We offer caseback engraving in Roman/Latin script, Chinese/Japanese/Korean characters, and Arabic script.

            Q: How many characters can I engrave?
            A: Up to 60 characters maximum on the caseback. Latin script: up to 20 characters at SGD 25, 21–40 at SGD 40, then SGD 1.50 per additional character. CJK or Arabic: SGD 3.00 per character, up to 15 characters.

            Q: Can I engrave a logo or image?
            A: Yes, for an additional SGD 60. You must supply a vector file (.ai or .svg). Our team will review the design for feasibility before confirming.

            Q: How long does engraving take?
            A: Standard engraving adds 2–3 business days to processing time. Rush same-day engraving (SGD 20 surcharge) available for orders placed before 12pm SGT, subject to availability.

            Q: Can I change the engraving text after ordering?
            A: If you contact us within 1 hour of placing the order, we can amend at no charge. After 1 hour, a SGD 15 correction fee applies. Once engraving has begun, changes are not possible.

            Q: Can the strap buckle be engraved?
            A: Yes, for metal buckles only (not rubber or NATO straps). Up to 10 characters for SGD 15.

            Q: Can you engrave in Chinese, Japanese, or Korean?
            A: Yes. CJK character engraving: SGD 3.00 per character, up to 15 characters maximum.

            Q: Can you engrave in Arabic?
            A: Yes. Arabic script engraving: SGD 3.00 per character, up to 15 characters maximum.

            Q: Is multi-line engraving possible?
            A: Yes. Two-line engraving is available for SGD 35, covering up to 30 characters total across both lines.
            """).strip(),
        },
        {
            "chunk_id": "KB-FAQ-003",
            "category": "strap_compatibility",
            "title": "FAQ — Strap Compatibility",
            "content": textwrap.dedent("""
            [FAQ — STRAP COMPATIBILITY]

            Q: What lug width do Boldr watches use?
            A: All current Boldr models (Expedition and Journey) use a 20mm lug width — a standard size compatible with most third-party straps.

            Q: Are the straps quick-release?
            A: Yes. All Boldr straps use a quick-release spring bar mechanism — no tools required to swap straps.

            Q: Can I use a NATO strap on the Expedition?
            A: Yes. Any standard 20mm NATO strap is compatible with both the Expedition and Journey.

            Q: Can I swap straps between the Expedition and Journey?
            A: Yes. Both models share the same 20mm lug width, so all Boldr straps are interchangeable between the two.

            Q: What strap do you recommend for swimming?
            A: The FKM rubber strap is the best choice for water activities — waterproof, quick-drying, and salt-resistant. The nylon NATO strap is also water-resistant but takes longer to dry. Do not use the leather strap for regular water exposure.

            Q: How do I care for the leather strap?
            A: Keep away from prolonged water exposure. Apply leather conditioner every 3–6 months. Avoid direct sunlight for extended periods.

            Q: Is the mesh bracelet compatible with the Expedition?
            A: No. The Mesh Bracelet (Silver, SGD 75) is compatible with the Journey model only.

            Q: Is the Titanium bracelet compatible with the Journey?
            A: No. The Titanium Bracelet (SGD 145) is compatible with the Expedition model only.

            Q: Which straps are best for sensitive skin?
            A: FKM rubber straps are the best choice for sensitive skin — BPA-free, nickel-free, and hypoallergenic. Nylon NATO straps are also suitable. Avoid leather straps if you have skin sensitivities.
            """).strip(),
        },
        {
            "chunk_id": "KB-FAQ-004",
            "category": "servicing",
            "title": "FAQ — Watch Servicing",
            "content": textwrap.dedent("""
            [FAQ — WATCH SERVICING]
            NOTE: For all prices and turnaround times, refer to the Servicing Rate Card (Tier 1). FAQ prices below are informational.

            Q: How much does a battery replacement cost?
            A: SGD 35, with a 3–5 business day turnaround. Includes a basic water resistance test and function check. For quartz movements only — the Boldr Expedition and Journey use automatic movements and do not have batteries.

            Q: What is included in a Full Service?
            A: The Full Service — Standard (SGD 160) includes full movement disassembly, ultrasonic cleaning, lubrication, regulation to +/-5s/day, water resistance test, case light polish, and new gaskets. The Premium tier (SGD 220) adds deep case polish, crystal replacement if scratched, and a 12-month service warranty.

            Q: My watch is losing time. What service do I need?
            A: If your watch is losing or gaining more than 15 seconds per day, a Regulation Service (SGD 85) is recommended. This includes movement cleaning and regulation to +/-5s/day with a timing machine report.

            Q: How often should I service my watch?
            A: We recommend a Full Service every 3–5 years for automatic movements, or when you notice significant timekeeping deviation.

            Q: How do I send my watch in for servicing?
            A: Pack your watch securely and ship to our Singapore service centre (address at checkout). We recommend insured shipping. For international customers, a SGD 25 surcharge covers insured return shipping.

            Q: Is there a warranty on servicing?
            A: The Premium Full Service includes a 12-month service warranty. A 12-month warranty extension can be added to any service for SGD 30 (must be purchased at time of service).

            Q: Can you polish the case during a service?
            A: Yes. Case & Bracelet Polish (SGD 45) can be added to any service tier as an add-on.
            """).strip(),
        },
        {
            "chunk_id": "KB-FAQ-005",
            "category": "product_general",
            "title": "FAQ — Orders, Shipping, Returns, General",
            "content": textwrap.dedent("""
            [FAQ — ORDERS, SHIPPING, RETURNS, GENERAL]
            NOTE: All order status questions (tracking, refund status, specific order issues) require Shopify access.
            Do not attempt to answer these from KB — route to CS team.

            Q: How long does shipping take?
            A: Standard shipping within Singapore: 3–5 business days. International: 7–14 business days. Express shipping available at checkout.

            Q: Do you ship internationally?
            A: Yes, worldwide. Customers are responsible for applicable customs duties and import taxes in their country.

            Q: What is your return policy?
            A: Returns accepted within 14 days of delivery for unworn, unmodified items in original packaging. Engraved items are non-returnable unless there is a manufacturing defect.

            Q: What is the warranty on Boldr watches?
            A: 2-year manufacturer's warranty covering movement defects. Does NOT cover physical damage, water damage beyond rated depth, or normal wear and tear.

            Q: Do you offer gift wrapping?
            A: Yes. Select the gift wrapping option at checkout (SGD 8). Includes premium gift box, ribbon, and personalised gift card.

            Q: What is the difference between the Expedition and Journey?
            A: Expedition (40mm, Grade 5 Ti): larger, heavier-duty, 100m water resistance — suited for active use. Journey (38mm, Grade 2 Ti): slimmer, lighter, everyday wear, 50m water resistance. Both use automatic movements.

            Q: Do you offer bulk/corporate pricing?
            A: Yes. For orders of 10 or more watches, contact corporate@boldr.co for a custom quote. For 5+ units, CS team handles the enquiry.

            Q: What personalisation options are available for gifting?
            A: Caseback engraving (from SGD 25), gift wrapping (SGD 8), and personalised gift card. All can be combined.
            """).strip(),
        },
    ]

    chunks = []
    for section in faq_sections:
        chunks.append({
            "chunk_id": section["chunk_id"],
            "source": "faq",
            "category": section["category"],
            "content": section["content"],
            "priority_rank": 2,
            "approved_by": "system_init",
            "approved_at": datetime.utcnow().isoformat(),
        })
    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: SOP — TONE AND PROCESS ONLY
# ─────────────────────────────────────────────────────────────────────────────

def build_sop_chunk() -> dict:
    """
    Extracts ONLY brand voice and process guidance from 05a_SOP.pdf.
    All pricing information is stripped — the SOP has known pricing errors.

    ⚠️ CRITICAL: Do NOT include any prices from the SOP in this chunk.
    The SOP shows incorrect figures for regulation (SGD 60 vs correct SGD 85),
    full service (SGD 180-250 vs correct SGD 160-220), and others.
    This chunk is for tone and escalation rules ONLY.
    """
    content = textwrap.dedent("""
    [BRAND VOICE & PROCESS — SOP EXTRACT — DO NOT USE FOR PRICING]
    Source: 05a_SOP.pdf | Tone and process guidance only — prices in Tier 1 Rate Cards

    ═══════════════════════════════════
    BRAND VOICE
    ═══════════════════════════════════
    • Friendly but not overly casual — Boldr is a premium brand
    • Direct — answer the question clearly, do not pad with filler
    • Helpful — if we cannot help directly, point them somewhere useful
    • Never promise what you are not sure about — check first, or flag as gap
    • Good opening: "Hi [Name], thanks for reaching out! Happy to help with that."
    • Avoid: Starting every reply with "Great question!"
    • Avoid: Overly formal language ("Dear Sir/Madam")
    • Avoid: Making promises about timelines you cannot confirm from the rate card

    ═══════════════════════════════════
    ESCALATION RULES — FLAG THESE, DO NOT ANSWER INDEPENDENTLY
    ═══════════════════════════════════
    • MRI / magnetic field resistance claims → check with supplier before confirming
    • Shock resistance ratings (trail running, extreme sports) → check with team
    • Older or discontinued model servicing → parts availability must be confirmed first
    • Corporate or bulk orders (5+ units) → direct to corporate@boldr.co
    • Angry customers or chargeback threats → escalate to cs@boldr.co
    • Media or press enquiries → forward to marketing@boldr.co
    • Logo or custom artwork engraving → flag for team review; ask customer to send vector file
    • Any warranty claim involving significant damage → flag for team immediately

    ═══════════════════════════════════
    CONTACT ROUTING
    ═══════════════════════════════════
    CS Team Lead:    cs@boldr.co           (escalations, difficult cases)
    Service Centre:  service@boldr.co      (servicing, warranty claims, repairs)
    Corporate Sales: corporate@boldr.co    (bulk orders 5+, B2B enquiries)
    Marketing:       marketing@boldr.co    (media, press, influencer enquiries)
    Shopify Admin:   admin.shopify.com     (order lookups, cancellations, refunds)

    ═══════════════════════════════════
    COMMON REPLY PATTERNS
    ═══════════════════════════════════
    Materials/safety question: check product reference for specific model first.
    Engraving: always confirm spelling reminder + non-returnable policy.
    Servicing: always mention both Standard and Premium Full Service tiers.
    Order status: ALWAYS check Shopify first — never guess order status.
    """).strip()

    return {
        "chunk_id": "KB-SOP-001",
        "source": "sop_process",
        "category": "process",
        "content": content,
        "priority_rank": 3,
        "approved_by": "system_init",
        "approved_at": datetime.utcnow().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ASSEMBLE ALL CHUNKS
# ─────────────────────────────────────────────────────────────────────────────

def build_all_chunks() -> list[dict]:
    """Returns all kb_chunks rows in priority order."""
    chunks = []

    print("Building Tier 1 chunks (rate cards)...")
    chunks.append(build_engraving_chunk())
    chunks.append(build_servicing_chunk())

    print("Building Tier 2 chunks (product reference)...")
    chunks.append(build_product_specs_chunk())

    print("Building Tier 2 chunks (FAQ sections)...")
    chunks.extend(build_faq_chunks())

    print("Building Tier 3 chunks (SOP — process only)...")
    chunks.append(build_sop_chunk())

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT ASSEMBLER
# ─────────────────────────────────────────────────────────────────────────────

def assemble_system_prompt(chunks: list[dict]) -> str:
    """
    Assembles all chunks into the formatted system prompt block.
    This is what gets injected into every Claude API call.

    In n8n: the Code node before the HTTP Request node runs the equivalent of
    this function by querying Supabase for all kb_chunks.
    """
    tier1 = [c for c in chunks if c["priority_rank"] == 1]
    tier2 = [c for c in chunks if c["priority_rank"] == 2 and c["source"] != "gap_resolution"]
    tier3 = [c for c in chunks if c["priority_rank"] == 3]
    gaps  = [c for c in chunks if c["source"] == "gap_resolution"]

    lines = []

    lines.append("═" * 60)
    lines.append("TIER 1 — RATE CARDS — AUTHORITATIVE PRICING")
    lines.append("Use these for ALL price and turnaround queries. Overrides FAQ and SOP.")
    lines.append("═" * 60)
    for c in tier1:
        lines.append(c["content"])
        lines.append("")

    lines.append("═" * 60)
    lines.append("TIER 2 — PRODUCT REFERENCE AND FAQ")
    lines.append("Use for specifications, materials, compatibility, Q&A.")
    lines.append("═" * 60)
    for c in tier2:
        lines.append(c["content"])
        lines.append("")

    lines.append("═" * 60)
    lines.append("TIER 3 — BRAND VOICE AND PROCESS (no prices)")
    lines.append("═" * 60)
    for c in tier3:
        lines.append(c["content"])
        lines.append("")

    if gaps:
        lines.append("═" * 60)
        lines.append("APPROVED KB ENTRIES FROM GAP RESOLUTION (treat as Tier 2)")
        lines.append("═" * 60)
        for c in gaps:
            lines.append(f"[Approved by {c['approved_by']} on {c['approved_at']}]")
            lines.append(c["content"])
            lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE WRITE
# ─────────────────────────────────────────────────────────────────────────────

def write_to_supabase(chunks: list[dict], replace: bool = True) -> None:
    """
    Inserts all chunks into Supabase kb_chunks table.

    Args:
        chunks: list of row dicts from build_all_chunks()
        replace: if True, DELETE existing rows before inserting (full refresh)
    """
    try:
        from supabase import create_client, Client
    except ImportError:
        print("ERROR: supabase package not installed.")
        print("Run: pip install supabase")
        sys.exit(1)

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
        print("Set them in .env or as environment variables.")
        sys.exit(1)

    print(f"Connecting to Supabase: {SUPABASE_URL}")
    client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    if replace:
        print("Deleting existing non-gap-resolution rows from kb_chunks...")
        # Keep gap_resolution rows (those were human-approved); replace source docs only
        client.table("kb_chunks").delete().neq("source", "gap_resolution").execute()

    print(f"Inserting {len(chunks)} chunks into kb_chunks...")
    for chunk in chunks:
        result = client.table("kb_chunks").upsert(chunk).execute()
        print(f"  ✓ {chunk['chunk_id']} ({chunk['source']}, priority {chunk['priority_rank']})")

    print(f"\nDone. {len(chunks)} chunks written to Supabase.")
    print("Gap resolution entries (if any) were preserved.")


# ─────────────────────────────────────────────────────────────────────────────
# PREVIEW WRITER
# ─────────────────────────────────────────────────────────────────────────────

def write_preview(chunks: list[dict], system_prompt: str) -> None:
    """
    Writes kb_preview.txt so you can inspect the full formatted KB
    before it goes into production. Review this carefully.
    """
    OUTPUT_PREVIEW.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PREVIEW, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("KB PREVIEW — Generated by build_kb.py\n")
        f.write(f"Generated: {datetime.utcnow().isoformat()}Z\n")
        f.write(f"Total chunks: {len(chunks)}\n")
        f.write("=" * 70 + "\n\n")

        f.write("CHUNK SUMMARY:\n")
        for c in chunks:
            f.write(f"  {c['chunk_id']:20s} | priority {c['priority_rank']} | {c['source']} | {c['category']}\n")
        f.write(f"\nTotal characters in KB: {sum(len(c['content']) for c in chunks):,}\n")
        f.write(f"Estimated tokens:        ~{sum(len(c['content']) for c in chunks) // 4:,}\n\n")

        f.write("=" * 70 + "\n")
        f.write("FULL SYSTEM PROMPT BLOCK (as injected into Claude API)\n")
        f.write("=" * 70 + "\n\n")
        f.write(system_prompt)

    print(f"\nPreview written to: {OUTPUT_PREVIEW}")
    print("Review this file before deploying to Supabase.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build Boldr KB and load into Supabase kb_chunks table."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build chunks and write preview, but do NOT write to Supabase.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Same as --dry-run. Write kb_preview.txt only.",
    )
    args = parser.parse_args()

    dry_run = args.dry_run or args.preview

    print("=" * 60)
    print("Boldr KB Builder")
    print("=" * 60)
    print(f"Source directory: {SOURCE_DIR.resolve()}")
    print(f"Mode: {'DRY RUN (no Supabase write)' if dry_run else 'LIVE (writing to Supabase)'}")
    print()

    # Build all chunks
    chunks = build_all_chunks()
    system_prompt = assemble_system_prompt(chunks)

    # Always write preview
    write_preview(chunks, system_prompt)

    # Token summary
    total_chars = sum(len(c["content"]) for c in chunks)
    total_tokens = total_chars // 4
    print(f"\nKB summary:")
    print(f"  Chunks: {len(chunks)}")
    print(f"  Total chars: {total_chars:,}")
    print(f"  Estimated tokens: ~{total_tokens:,}")
    print(f"  % of Claude 200K context: {total_tokens/200_000*100:.1f}%")
    print(f"  Cost per ticket (input only): ~USD ${(total_tokens + 3000)/1_000_000 * 3:.4f}")

    if dry_run:
        print("\nDry run complete. To write to Supabase, run without --dry-run.")
        return

    # Write to Supabase
    write_to_supabase(chunks, replace=True)
    print("\nKB build complete. n8n workflows can now read from kb_chunks.")


if __name__ == "__main__":
    main()
