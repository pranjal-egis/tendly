


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║            TENDLY  v5.7  ·  Egis AI Tender Intelligence Platform          ║
# ║            Internal Operations Tool                                       ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║  Model      : OPENROUTER_MODEL env var (free-tier default + fallbacks)    ║
# ║  PDF Engine : pdfplumber — semantic page chunking + table extraction      ║
# ║  Analysis   : Section-priority smart context window, JSON auto-repair     ║
# ║  Chat       : Retrieval-augmented Q&A (most-relevant pages surfaced)      ║
# ╚══════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv
import pdfplumber
import requests
import streamlit as st

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG  (must be the first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Tendly · AI Tender Intelligence",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tendly")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    """Read from environment first, then Streamlit secrets (for Cloud deploys)."""
    val = os.getenv(name, "")
    if val:
        return val
    try:
        return str(st.secrets.get(name, default))
    except Exception:  # no secrets.toml present
        return default


class Config:
    OPENROUTER_API_KEY: str = _secret("OPENROUTER_API_KEY")
    # Free-tier model IDs rotate on OpenRouter — override via env without a code change.
    OPENROUTER_MODEL: str = _secret(
        "OPENROUTER_MODEL", "google/gemma-4-31b-it:free"
    )
    # Automatic fallbacks if the primary model is overloaded / rate-limited.
    FALLBACK_MODELS: list[str] = [
        m.strip()
        for m in _secret(
            "OPENROUTER_FALLBACKS",
            "meta-llama/llama-3.3-70b-instruct:free,google/gemma-3-27b-it:free",
        ).split(",")
        if m.strip()
    ]
    API_BASE_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    API_TIMEOUT: int = 150  # free models can be slow on long prompts
    API_MAX_RETRIES: int = 3
    API_RETRY_DELAY: float = 3.0

    # PDF extraction tuning
    PDF_MIN_PAGE_TEXT: int = 40        # chars below which a page is image-only
    PDF_ANALYSIS_CHAR_BUDGET: int = 55_000  # total chars fed to AI for analysis
    PDF_HEAD_CHARS: int = 22_000       # first N chars (cover + instructions)
    PDF_TAIL_CHARS: int = 10_000       # last N chars (checklists, T&Cs)
    PDF_MIN_READABLE_WORDS: int = 50   # below this, analysis is blocked

    # Chat / Q&A
    CHAT_SNIPPET_CHARS: int = 4_000    # chars per retrieved snippet
    CHAT_MAX_SNIPPETS: int = 5         # max snippets retrieved per question
    CHAT_HISTORY_TURNS: int = 8        # conversation turns to include

    # App
    HISTORY_MAX: int = 5
    RAW_TEXT_VIEW_CAP: int = 120_000   # chars shown in the raw-text viewer
    APP_VERSION: str = "5.7"


CFG = Config()
HAS_KEY = bool(CFG.OPENROUTER_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# STYLES  —  Egis brand: Midnight #08212C · Green #ABC022 · Azure #0099A5
#            Typography: Urbanist (display) · Segoe UI (body/data)
# ─────────────────────────────────────────────────────────────────────────────
STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Urbanist:wght@300;400;500;600;700;800;900&family=Poppins:wght@500;600;700&family=Barlow:wght@400;500;600&display=swap');

/* ── CSS Custom Properties ─────────────────────── */
:root {
  --midnight:   #08212C;
  --midnight-2: #0C2A38;
  --midnight-3: #0F3040;
  --green:      #ABC022;
  --green-dim:  #8FA01A;
  --green-glow: rgba(171,192,34,0.12);
  --teal:       #0099A5;
  --teal-dim:   #007A84;
  --teal-glow:  rgba(0,153,165,0.10);
  --duck:       #00617E;
  --border:     #163545;
  --border-2:   #1C4055;
  --text-bright:#F0F6F8;
  --text-main:  #C8DDE2;
  --text-muted: #6B8F96;
  --text-dim:   #2E5A68;
  --red:        #E05252;
  --orange:     #E09A3A;
  --lime:       #D5F311;
  --steel:      #5D848A;
  --surface-1:  #0C2A38;
  --surface-2:  #0F3040;
  --radius-sm:  6px;     /* Egis DS: buttons, inputs   */
  --radius-md:  12px;    /* Egis DS: cards, panels     */
  --radius-lg:  15px;    /* Egis DS: feature cards     */
  --radius-pill:999px;   /* Egis DS: badges, pills     */
}

/* ── Streamlit Cloud table border reset ──────── */
.stMarkdown table, .stMarkdown table td, .stMarkdown table th,
[data-testid="stMarkdownContainer"] table,
[data-testid="stMarkdownContainer"] table td,
[data-testid="stMarkdownContainer"] table th {
  border: none !important;
  border-collapse: collapse !important;
  background: transparent !important;
}

/* ── Base ─────────────────────────────────────── */
html, body, [class*="css"] {
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.stApp {
  background:
    radial-gradient(900px 480px at 85% -10%, rgba(0,153,165,0.05), transparent 60%),
    radial-gradient(720px 420px at -10% 12%, rgba(171,192,34,0.03), transparent 55%),
    var(--midnight);
  color: var(--text-main);
}

/* ── Motion ─────────────────────────────────────── */
@keyframes fadeUp  { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: none; } }
@keyframes sweep   { 0% { transform: translateX(-100%); } 55%, 100% { transform: translateX(120%); } }
@keyframes glowPulse { 0%,100% { opacity: 0.55; } 50% { opacity: 1; } }
.card, .hero-card, .verdict, .stat-box, .ui-alert, .bubble-user, .bubble-ai {
  animation: fadeUp 0.35s ease both;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}

/* ══════════════ TOP BAR — Brand Header ══════════════ */
.egis-topbar {
  background: transparent;
  border-bottom: none;
  padding: 0.4rem 0.25rem 1.05rem 0;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  position: relative;
}
/* Single branded hairline: lime → teal → fades out. One line, no overlap. */
.egis-topbar::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg,
    rgba(213,243,17,0.75) 0%, rgba(171,192,34,0.6) 12%,
    rgba(0,153,165,0.45) 38%, rgba(22,53,69,0.9) 68%, transparent 100%);
}
.egis-wordmark {
  font-family: 'Urbanist', 'Segoe UI', sans-serif;
  font-size: 1.95rem;
  font-weight: 800;
  color: #fff;
  letter-spacing: -0.5px;
  line-height: 1;
  text-transform: uppercase;
  display: flex;
  align-items: baseline;
}
.egis-e { color: var(--green); }
/* Egis signature: short lime underscore beneath the wordmark */
.egis-underscore {
  width: 34px; height: 3px;
  background: var(--lime);
  border-radius: var(--radius-pill);
  margin: 7px 0 9px;
  box-shadow: 0 0 10px rgba(213,243,17,0.45);
}
.egis-separator {
  font-family: 'Urbanist', sans-serif;
  font-weight: 200;
  font-size: 1.4rem;
  color: var(--border-2);
  margin: 0 0.65rem;
}
.egis-tendly {
  font-family: 'Urbanist', sans-serif;
  font-weight: 300;
  font-size: 1.55rem;
  color: var(--teal);
  letter-spacing: 4px;
  text-shadow: 0 0 18px rgba(0,153,165,0.35);
}
/* One meta line: product · context, with clear hierarchy */
.egis-product {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--teal);
}
.egis-product .dim {
  color: var(--text-dim);
  font-weight: 600;
  letter-spacing: 2px;
}
.egis-motto-block { text-align: right; padding-bottom: 2px; }
.egis-motto-line {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--text-dim);
  line-height: 1.8;
}
.egis-motto-line .highlight { color: var(--green); }
.egis-motto-tag {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.5rem;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--text-dim);
  opacity: 0.7;
  margin-top: 2px;
}

/* Pull the page up — kill Streamlit's huge default top padding */
.block-container, [data-testid="stMainBlockContainer"] {
  padding-top: 1.6rem !important;
}

/* ══════════════ DIVIDERS ══════════════ */
.divider-main {
  height: 1px;
  background: linear-gradient(90deg, var(--green) 0%, var(--teal) 40%, transparent 100%);
  margin: 1.4rem 0;
  opacity: 0.6;
}
.divider-thin {
  height: 1px;
  background: linear-gradient(90deg, var(--border) 0%, transparent 100%);
  margin: 0.9rem 0;
}

/* ══════════════ CARDS ══════════════ */
.card {
  background: linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0) 45%), rgba(12,42,56,0.62);
  border: 1px solid rgba(28,64,85,0.85);
  border-radius: var(--radius-md);
  padding: 1.2rem 1.4rem;
  margin-bottom: 0.85rem;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 2px 12px rgba(0,0,0,0.18);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
.card:hover {
  border-color: rgba(0,153,165,0.45);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 10px 32px rgba(0,0,0,0.35), 0 0 24px rgba(0,153,165,0.08);
  transform: translateY(-1px);
}
.card--teal-top   { border-top: 2px solid var(--teal)  !important; }
.card--green-top  { border-top: 2px solid var(--green) !important; }
.card--teal-left  { border-left: 3px solid var(--teal)  !important; }
.card--green-left { border-left: 3px solid var(--green) !important; }
.card--red-left   { border-left: 3px solid var(--red)   !important; }
.card--orange-left{ border-left: 3px solid var(--orange)!important; }

.card-label {
  font-family: 'Urbanist', 'Segoe UI', sans-serif;
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 3px;
  text-transform: uppercase;
  color: var(--teal);
  margin-bottom: 0.55rem;
  display: flex;
  align-items: center;
  gap: 7px;
}
.card-label::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border), transparent);
}
.card-body { font-size: 0.875rem; color: var(--text-main); line-height: 1.8; }

.hero-card {
  background: linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 40%),
              linear-gradient(135deg, rgba(15,48,64,0.85) 0%, rgba(8,33,44,0.9) 100%);
  border: 1px solid var(--border-2);
  border-top: 2px solid var(--green);
  border-radius: var(--radius-md);
  padding: 1.1rem 1.4rem;
  margin-bottom: 0.85rem;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.07), 0 4px 18px rgba(0,0,0,0.25);
}
.hero-card::before {
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 80px; height: 80px;
  background: radial-gradient(circle at top right, var(--green-glow), transparent 70%);
  pointer-events: none;
}
.hero-label {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.55rem;
  letter-spacing: 3.5px;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 5px;
}
.hero-value {
  font-family: 'Urbanist', sans-serif;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-bright);
  line-height: 1.35;
}

/* ══════════════ STAT BOXES ══════════════ */
.stat-row { display: flex; gap: 8px; margin-bottom: 1.3rem; flex-wrap: wrap; }
.stat-box {
  flex: 1;
  min-width: 90px;
  background: linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 50%), rgba(12,42,56,0.6);
  border: 1px solid rgba(28,64,85,0.85);
  border-top: 2px solid var(--teal);
  border-radius: var(--radius-md);
  padding: 0.9rem 0.75rem 0.8rem;
  text-align: center;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 2px 10px rgba(0,0,0,0.18);
  transition: transform 0.15s ease, box-shadow 0.2s ease;
}
.stat-box:hover { transform: translateY(-2px); box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 8px 24px rgba(0,0,0,0.3); }
.stat-box.warn  { border-top-color: var(--orange) !important; }
.stat-box.crit  { border-top-color: var(--red)    !important; }
.stat-box.good  { border-top-color: var(--green)  !important; }
.stat-value {
  font-family: 'Urbanist', sans-serif;
  font-size: 1.65rem;
  font-weight: 200;
  color: var(--green);
  line-height: 1;
  display: block;
  letter-spacing: -0.5px;
}
.stat-value.warn { color: var(--orange) !important; }
.stat-value.crit { color: var(--red)    !important; }
.stat-label {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.55rem;
  text-transform: uppercase;
  letter-spacing: 2.5px;
  color: var(--text-dim);
  margin-top: 5px;
  display: block;
}

/* ══════════════ BADGES ══════════════ */
.badge {
  display: inline-block;
  padding: 3px 11px;
  border-radius: var(--radius-pill);
  background-image: linear-gradient(180deg, rgba(255,255,255,0.07), rgba(255,255,255,0) 55%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
  font-family: 'Urbanist', sans-serif;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  white-space: nowrap;
}
.badge-high { color: var(--red);    background: rgba(224,82,82,0.08);  border: 1px solid rgba(224,82,82,0.25); }
.badge-med  { color: var(--orange); background: rgba(224,154,58,0.08); border: 1px solid rgba(224,154,58,0.25); }
.badge-low  { color: var(--green);  background: var(--green-glow);     border: 1px solid rgba(171,192,34,0.3); }
.badge-info { color: var(--teal);   background: var(--teal-glow);      border: 1px solid rgba(0,153,165,0.3); }

/* ══════════════ VERDICT BANNER ══════════════ */
.verdict {
  border-radius: var(--radius-lg);
  padding: 1.4rem 2rem;
  text-align: center;
  margin-bottom: 1.3rem;
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.07), 0 8px 32px rgba(0,0,0,0.3);
}
.verdict::before {
  content: '';
  position: absolute;
  top: -60%; left: 50%;
  width: 70%; height: 120%;
  transform: translateX(-50%);
  background: radial-gradient(ellipse at top, rgba(255,255,255,0.06), transparent 65%);
  pointer-events: none;
}
.verdict--go          { background: rgba(171,192,34,0.06); border: 1px solid rgba(171,192,34,0.4); border-top: 3px solid var(--green); }
.verdict--conditional { background: rgba(224,154,58,0.06); border: 1px solid rgba(224,154,58,0.4); border-top: 3px solid var(--orange); }
.verdict--nogo        { background: rgba(224,82,82,0.06);  border: 1px solid rgba(224,82,82,0.4);  border-top: 3px solid var(--red); }
.verdict-eyebrow {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.58rem;
  letter-spacing: 4px;
  text-transform: uppercase;
  color: var(--text-dim);
}
.verdict-word {
  font-family: 'Urbanist', 'Segoe UI', sans-serif;
  font-size: 2.1rem;
  font-weight: 900;
  letter-spacing: 4px;
  margin: 0.25rem 0 0.1rem;
  text-transform: uppercase;
  text-shadow: 0 0 26px currentColor;
}
.verdict-score    { font-size: 1rem; font-weight: 300; color: var(--text-muted); }
.verdict-rationale{ font-size: 0.84rem; color: var(--text-main); line-height: 1.7; margin-top: 0.6rem; }

/* ══════════════ SECTION HEADINGS ══════════════ */
.sec-head {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.6rem;
  font-weight: 800;
  letter-spacing: 3.5px;
  text-transform: uppercase;
  color: var(--text-dim);
  margin: 1.4rem 0 0.8rem;
  display: flex;
  align-items: center;
  gap: 10px;
}
.sec-head::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, var(--border) 0%, transparent 100%);
}

/* ══════════════ KV TABLE ══════════════ */
.kv-table { width: 100%; border-collapse: collapse; }
.kv-table tr { border-bottom: 1px solid rgba(22,53,69,0.8); }
.kv-table tr:last-child { border-bottom: none; }
.kv-table td { padding: 0.55rem 0.1rem; vertical-align: top; }
.kv-key {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  color: var(--text-dim);
  width: 40%;
  padding-right: 0.8rem;
}
.kv-val { font-size: 0.85rem; color: var(--text-main); }

/* ══════════════ TIMELINE / DATES ══════════════ */
.tl-date { font-size: 0.92rem; font-weight: 500; color: var(--text-main); }
.tl-date.crit { color: var(--red); }
.tl-date.warn { color: var(--orange); }
.tl-date.ok   { color: var(--green); }
.tl-pill {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.57rem;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  margin-left: 8px;
  white-space: nowrap;
}
.tl-pill.crit { background: rgba(224,82,82,0.12);  color: var(--red);    border: 1px solid rgba(224,82,82,0.3); }
.tl-pill.warn { background: rgba(224,154,58,0.12); color: var(--orange); border: 1px solid rgba(224,154,58,0.3); }
.tl-pill.ok   { background: var(--green-glow);     color: var(--green);  border: 1px solid rgba(171,192,34,0.3); }

/* ══════════════ PROGRESS BARS ══════════════ */
.prog-wrap   { margin-bottom: 1rem; }
.prog-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.79rem;
  color: var(--text-main);
  margin-bottom: 6px;
}
.prog-track  { background: rgba(22,53,69,0.9); border-radius: var(--radius-pill); height: 6px; box-shadow: inset 0 1px 2px rgba(0,0,0,0.35); }
.prog-fill   { height: 6px; border-radius: var(--radius-pill); transition: width 0.5s ease;
               background-image: linear-gradient(180deg, rgba(255,255,255,0.3), rgba(255,255,255,0) 60%) !important; }

.score-track {
  background: rgba(22,53,69,0.9);
  border-radius: var(--radius-pill);
  height: 12px;
  position: relative;
  overflow: hidden;
  box-shadow: inset 0 1px 3px rgba(0,0,0,0.4);
}
.score-fill  { height: 12px; border-radius: var(--radius-pill);
               background-image: linear-gradient(180deg, rgba(255,255,255,0.3), rgba(255,255,255,0) 60%) !important;
               box-shadow: 0 0 12px rgba(255,255,255,0.08);
               position: relative; overflow: hidden;
               transition: width 0.7s cubic-bezier(0.22, 1, 0.36, 1); }
.score-fill::after {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(100deg, transparent 25%, rgba(255,255,255,0.35) 50%, transparent 75%);
  animation: sweep 2.8s ease-in-out infinite;
}
.score-zones {
  display: flex;
  justify-content: space-between;
  font-size: 0.56rem;
  color: var(--text-dim);
  margin-top: 4px;
  letter-spacing: 0.5px;
}

/* ══════════════ CHAT BUBBLES ══════════════ */
.bubble-user {
  background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0) 50%), rgba(12,42,56,0.65);
  border: 1px solid var(--border);
  border-right: 3px solid var(--teal);
  border-radius: var(--radius-md) var(--radius-md) 4px var(--radius-md);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  font-size: 0.875rem;
  color: var(--text-bright);
  text-align: right;
}
.bubble-ai {
  background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0) 50%), rgba(8,33,44,0.6);
  border: 1px solid var(--border);
  border-left: 3px solid var(--green);
  border-radius: var(--radius-md) var(--radius-md) var(--radius-md) 4px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  font-size: 0.875rem;
  color: var(--text-main);
  line-height: 1.8;
  white-space: pre-wrap;
}
.bubble-ts {
  font-size: 0.58rem;
  color: var(--text-dim);
  text-align: right;
  margin-bottom: 0.8rem;
  margin-top: -0.3rem;
}

/* ══════════════ QUALITY BAR (PDF stats) ══════════════ */
.quality-bar { display: flex; gap: 3px; margin-top: 7px; }
.quality-seg { flex: 1; height: 3px; border-radius: var(--radius-pill); background: var(--border); }
.quality-seg.g { background: var(--green);  box-shadow: 0 0 6px rgba(171,192,34,0.5); }
.quality-seg.w { background: var(--orange); box-shadow: 0 0 6px rgba(224,154,58,0.5); }
.quality-seg.b { background: var(--red);    box-shadow: 0 0 6px rgba(224,82,82,0.5); }

/* ══════════════ SIDEBAR ══════════════ */
section[data-testid="stSidebar"] {
  background: rgba(6,20,28,0.85) !important;
  backdrop-filter: blur(18px) !important;
  -webkit-backdrop-filter: blur(18px) !important;
  min-width: 260px !important;
}
section[data-testid="stSidebar"]::before {
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 1px; height: 100%;
  background: linear-gradient(180deg, var(--green) 0%, var(--teal) 40%, transparent 100%);
}
/* Sidebar open/close toggles — cover legacy and current Streamlit testids.
   Best practice: never hide the native svg / control; only restyle it. */
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="stExpandSidebarButton"] {
  background: rgba(12,42,56,0.9) !important;
  border: 1px solid var(--border-2) !important;
  border-radius: var(--radius-pill) !important;
  color: var(--teal) !important;
  opacity: 1 !important;
  visibility: visible !important;
  display: flex !important;
  z-index: 9999 !important;
  box-shadow: 0 2px 10px rgba(0,0,0,0.35);
  transition: border-color 0.15s ease, color 0.15s ease;
}
[data-testid="collapsedControl"]:hover,
[data-testid="stSidebarCollapsedControl"]:hover,
[data-testid="stExpandSidebarButton"]:hover {
  border-color: var(--green) !important;
  color: var(--green) !important;
}
[data-testid="collapsedControl"] svg,
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stSidebarCollapseButton"] svg { fill: currentColor !important; }
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="stExpandSidebarButton"] button,
[data-testid="stSidebarCollapseButton"] button {
  background: transparent !important;
  border: none !important;
  color: var(--teal) !important;
}
[data-testid="stSidebarCollapseButton"] button:hover { color: var(--green) !important; box-shadow: none !important; }

.sb-card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-left: 2px solid transparent;
  border-radius: var(--radius-sm);
  padding: 0.8rem 0.9rem;
  margin-bottom: 0.45rem;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.sb-card:hover { border-left-color: var(--green); background: var(--surface-2); }
.sb-card--current { border-left-color: var(--green); }
.sb-title { font-size: 0.78rem; color: var(--text-bright); font-weight: 600; line-height: 1.35; }
.sb-meta  { font-size: 0.6rem; color: var(--text-dim); letter-spacing: 0.5px; margin-top: 3px; }

/* ══════════════ STREAMLIT COMPONENT OVERRIDES ══════════════ */
/* File uploader — clean white card (matches the uploaded-file pill) */
.stFileUploader > div,
[data-testid="stFileUploaderDropzone"] {
  background: #F4F6F8 !important;
  border: 1px dashed #B9C6CC !important;
  border-radius: var(--radius-md) !important;
  color: var(--midnight) !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stFileUploader > div:hover,
[data-testid="stFileUploaderDropzone"]:hover {
  border-color: var(--teal) !important;
  box-shadow: 0 4px 18px rgba(0,0,0,0.25) !important;
}

/* Dropzone instruction text + icons — dark on white */
[data-testid="stFileUploaderDropzone"] span,
[data-testid="stFileUploaderDropzone"] div,
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] * {
  color: var(--midnight) !important;
  fill: var(--midnight) !important;
}
[data-testid="stFileUploaderDropzone"] small {
  color: var(--steel) !important;
}

/* "Browse files" / "Upload" button inside the dropzone */
[data-testid="stFileUploaderDropzone"] button {
  background: #fff !important;
  border: 1px solid var(--teal-dim) !important;
  border-radius: var(--radius-sm) !important;
  font-family: 'Poppins', 'Urbanist', sans-serif !important;
  font-weight: 600 !important;
  transition: all 0.18s ease !important;
}
[data-testid="stFileUploaderDropzone"] button,
[data-testid="stFileUploaderDropzone"] button * { color: var(--teal-dim) !important; }
[data-testid="stFileUploaderDropzone"] button:hover {
  border-color: var(--green-dim) !important;
  background: rgba(171,192,34,0.12) !important;
}
[data-testid="stFileUploaderDropzone"] button:hover * { color: var(--green-dim) !important; }

/* Uploaded file pill (name, size, delete) — native white, dark text */
[data-testid="stFileUploaderFile"],
[data-testid="stFileUploaderFileName"],
[data-testid="stFileUploaderFile"] * {
  color: var(--midnight) !important;
  fill: var(--steel) !important;
}
[data-testid="stFileUploaderDeleteBtn"] button {
  border: none !important;
  background: transparent !important;
  color: var(--steel) !important;
}
[data-testid="stFileUploaderDeleteBtn"] button:hover { color: var(--red) !important; box-shadow: none !important; }

.stButton > button, .stFormSubmitButton > button {
  background: linear-gradient(180deg, rgba(255,255,255,0.14) 0%, rgba(255,255,255,0) 50%), var(--teal) !important;
  color: #fff !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  font-family: 'Poppins', 'Urbanist', 'Segoe UI', sans-serif !important;
  font-weight: 600 !important;
  letter-spacing: 0.8px !important;
  text-transform: uppercase !important;
  font-size: 0.72rem !important;
  border-radius: var(--radius-sm) !important;
  padding: 0.6rem 1.3rem !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.18), 0 2px 8px rgba(0,0,0,0.25) !important;
  position: relative !important;
  overflow: hidden !important;
  transition: all 0.18s ease !important;
}
.stButton > button::after, .stFormSubmitButton > button::after {
  content: '';
  position: absolute;
  top: 0; left: -80%;
  width: 50%; height: 100%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,0.22), transparent);
  transform: skewX(-20deg);
  transition: left 0.45s ease;
  pointer-events: none;
}
.stButton > button:hover::after, .stFormSubmitButton > button:hover::after { left: 130%; }
.stButton > button:hover, .stFormSubmitButton > button:hover {
  background: linear-gradient(180deg, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0) 50%), var(--teal) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.22), 0 6px 20px rgba(0,153,165,0.4) !important;
  transform: translateY(-1px) !important;
}
.stButton > button:active, .stFormSubmitButton > button:active {
  transform: translateY(0) scale(0.99) !important;
  box-shadow: none !important;
}
.stButton > button:focus-visible, .stFormSubmitButton > button:focus-visible,
.stDownloadButton > button:focus-visible {
  outline: none !important;
  box-shadow: 0 0 0 3px rgba(171,192,34,0.35) !important;
}
.stButton > button:disabled, .stFormSubmitButton > button:disabled {
  background: var(--surface-2) !important;
  color: var(--text-dim) !important;
  box-shadow: none !important;
  transform: none !important;
  cursor: not-allowed !important;
}
/* Primary CTA — Egis Green, glossy */
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: linear-gradient(180deg, rgba(255,255,255,0.28) 0%, rgba(255,255,255,0) 52%), var(--green) !important;
  color: var(--midnight) !important;
  font-weight: 700 !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 3px 14px rgba(171,192,34,0.3) !important;
}
.stButton > button[kind="primary"]:hover:not(:disabled),
.stFormSubmitButton > button[kind="primary"]:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(255,255,255,0.32) 0%, rgba(255,255,255,0) 52%), var(--lime) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.4), 0 8px 26px rgba(213,243,17,0.32) !important;
}
.stButton > button:disabled, .stFormSubmitButton > button:disabled,
.stButton > button[kind="primary"]:disabled, .stFormSubmitButton > button[kind="primary"]:disabled {
  background: var(--surface-2) !important;
  color: var(--text-dim) !important;
  box-shadow: none !important;
  transform: none !important;
}
.stButton > button:disabled::after, .stFormSubmitButton > button:disabled::after { display: none; }

.stDownloadButton > button {
  background: transparent !important;
  color: var(--green) !important;
  border: 1px solid rgba(171,192,34,0.45) !important;
  font-family: 'Poppins', 'Urbanist', sans-serif !important;
  font-weight: 600 !important;
  letter-spacing: 0.8px !important;
  text-transform: uppercase !important;
  font-size: 0.7rem !important;
  border-radius: var(--radius-pill) !important;
  transition: all 0.18s ease !important;
}
.stDownloadButton > button:hover {
  background: var(--green-glow) !important;
  border-color: var(--green) !important;
  box-shadow: 0 4px 14px rgba(171,192,34,0.18) !important;
  transform: translateY(-1px) !important;
}

.stTextArea textarea, .stTextInput input {
  background: var(--surface-1) !important;
  border: 1.5px solid var(--border) !important;
  color: var(--text-bright) !important;
  border-radius: var(--radius-sm) !important;
  font-size: 0.875rem !important;
  transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: var(--green) !important;
  box-shadow: 0 0 0 3px rgba(171,192,34,0.15) !important;
}

[data-testid="stForm"] {
  border: none !important;
  padding: 0 !important;
}

.stTabs [data-baseweb="tab-list"] {
  background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0)), rgba(12,42,56,0.45);
  border: 1px solid rgba(28,64,85,0.7);
  border-radius: var(--radius-pill);
  padding: 4px !important;
  gap: 2px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  color: var(--text-dim) !important;
  font-family: 'Urbanist', 'Segoe UI', sans-serif !important;
  font-size: 0.7rem !important;
  font-weight: 700 !important;
  letter-spacing: 1.2px !important;
  text-transform: uppercase !important;
  padding: 0.55rem 1rem !important;
  border-radius: var(--radius-pill) !important;
  border-bottom: none !important;
  transition: all 0.18s ease !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text-main) !important;
  background: rgba(255,255,255,0.04) !important;
}
.stTabs [aria-selected="true"] {
  color: var(--midnight) !important;
  background: linear-gradient(180deg, rgba(255,255,255,0.28), rgba(255,255,255,0) 55%), var(--green) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 2px 12px rgba(171,192,34,0.3) !important;
}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none !important; }

.stSpinner > div { border-top-color: var(--green) !important; }

.streamlit-expanderHeader {
  background: var(--surface-1) !important;
  color: var(--text-muted) !important;
  font-size: 0.82rem !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-sm) !important;
}
.streamlit-expanderContent {
  background: rgba(8,33,44,0.5) !important;
  border: 1px solid var(--border) !important;
  border-top: none !important;
  border-radius: 0 0 var(--radius-sm) var(--radius-sm) !important;
}

div[data-testid="stCheckbox"] {
  margin-bottom: 0;
  padding: 0.38rem 0.6rem;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: all 0.12s ease;
}
div[data-testid="stCheckbox"]:hover {
  background: var(--surface-1);
  border-color: var(--border);
}
div[data-testid="stCheckbox"] label { font-size: 0.875rem !important; cursor: pointer; }
div[data-testid="stCheckbox"] label p { color: var(--text-bright) !important; }
div[data-testid="stCheckbox"] input[type="checkbox"]:checked ~ div label p {
  color: var(--green) !important;
  text-decoration: line-through;
  text-decoration-color: rgba(171,192,34,0.4);
}

/* Fallback styling for any native st.* alert (exceptions etc.) */
.stAlert {
  background: var(--surface-1) !important;
  border: 1px solid var(--border-2) !important;
  border-radius: var(--radius-sm) !important;
}

/* ── Branded alert component (ui_alert) ─────────── */
.ui-alert {
  display: flex;
  gap: 0.85rem;
  align-items: flex-start;
  border: 1px solid;
  border-radius: var(--radius-md);
  padding: 0.9rem 1.1rem;
  margin: 0.6rem 0 1rem;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 4px 16px rgba(0,0,0,0.2);
}
.ui-alert-icon {
  width: 26px; height: 26px; min-width: 26px;
  border: 1px solid; border-radius: var(--radius-pill);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.78rem; font-weight: 700; margin-top: 1px;
}
.ui-alert-title {
  font-family: 'Urbanist', sans-serif;
  font-weight: 700; font-size: 0.78rem;
  letter-spacing: 0.8px; text-transform: uppercase;
}
.ui-alert-body { font-size: 0.82rem; color: var(--text-main); line-height: 1.65; margin-top: 3px; }

/* ── Sidebar history "Open" buttons (keyed hist_*) ── */
div[class*="st-key-hist_"] button,
div[class*="st-key-chkall_"] button, div[class*="st-key-chkrst_"] button {
  background: transparent !important;
  border: 1px solid var(--border-2) !important;
  color: var(--teal) !important;
  font-size: 0.6rem !important;
  letter-spacing: 1.2px !important;
  padding: 0.28rem 0.7rem !important;
  min-height: 0 !important;
  margin: -0.15rem 0 0.7rem !important;
  width: 100% !important;
}
div[class*="st-key-hist_"] button:hover,
div[class*="st-key-chkall_"] button:hover, div[class*="st-key-chkrst_"] button:hover {
  border-color: var(--green) !important;
  color: var(--green) !important;
  background: var(--green-glow) !important;
  box-shadow: none !important;
}

/* ── Quick Question buttons (keyed qq_*) — equal height, wrapped text ──
   Streamlit ≥1.39 puts class "st-key-<key>" on each element container,
   so this targets ONLY the quick-question buttons (not exports/forms). */
div[class*="st-key-qq_"] button {
  min-height: 96px !important;
  height: 100% !important;
  white-space: normal !important;
  word-break: break-word !important;
  text-align: center !important;
  line-height: 1.5 !important;
  padding: 0.65rem 0.9rem !important;
  font-size: 0.68rem !important;
  letter-spacing: 0.5px !important;
  text-transform: none !important;
  font-weight: 600 !important;
  background: var(--surface-2) !important;
  border: 1px solid var(--border) !important;
  border-top: 2px solid var(--teal) !important;
  border-radius: var(--radius-md) !important;
  color: var(--text-main) !important;
}
div[class*="st-key-qq_"] button:hover {
  background: var(--midnight-3) !important;
  border-top-color: var(--green) !important;
  color: var(--text-bright) !important;
}
.qq-label {
  font-size: 0.58rem;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  color: #2a5060;
  margin-bottom: 0.6rem;
}

/* ── Landing hero ─────────────────────────────── */
.hero-wrap { text-align: center; padding: 2.4rem 0 1.2rem; }
.hero-note { text-align: center; font-size: 0.62rem; color: var(--text-dim);
             letter-spacing: 0.5px; margin-top: 0.5rem; }

/* ── Landing feature grid ─────────────────────── */
.feat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
  margin: 1.8rem 0 0.8rem;
}
.feat-card {
  background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0) 50%), rgba(12,42,56,0.55);
  border: 1px solid rgba(28,64,85,0.85);
  border-radius: var(--radius-md);
  padding: 1.05rem 1.1rem 1rem;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.feat-card:hover {
  transform: translateY(-3px);
  border-color: rgba(171,192,34,0.45);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.07), 0 10px 28px rgba(0,0,0,0.35), 0 0 22px rgba(171,192,34,0.07);
}
.feat-icon {
  width: 34px; height: 34px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.95rem;
  background: linear-gradient(150deg, rgba(171,192,34,0.16), rgba(0,153,165,0.14));
  border: 1px solid rgba(0,153,165,0.3);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.1);
  margin-bottom: 0.7rem;
}
.feat-title {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.68rem; font-weight: 800; letter-spacing: 1.6px; text-transform: uppercase;
  color: var(--text-bright); margin-bottom: 0.35rem;
}
.feat-desc { font-size: 0.74rem; color: var(--text-muted); line-height: 1.6; }

.landing-foot {
  text-align: center;
  font-family: 'Urbanist', sans-serif;
  font-size: 0.52rem; letter-spacing: 3px; text-transform: uppercase;
  color: var(--text-dim); margin-top: 1.6rem;
}
.landing-foot .highlight { color: var(--green); }

/* ── Empty chat state ─────────────────────────── */
.chat-empty {
  text-align: center;
  padding: 1.6rem 1rem 1.8rem;
  border: 1px dashed rgba(28,64,85,0.9);
  border-radius: var(--radius-md);
  background: rgba(12,42,56,0.35);
  margin-bottom: 1rem;
}
.chat-empty-icon { font-size: 1.4rem; opacity: 0.85; animation: glowPulse 3s ease-in-out infinite; }
.chat-empty-title { font-family: 'Urbanist', sans-serif; font-size: 0.78rem; font-weight: 700;
                    letter-spacing: 1.5px; text-transform: uppercase; color: var(--text-muted); margin-top: 6px; }
.chat-empty-sub { font-size: 0.72rem; color: var(--text-dim); margin-top: 4px; line-height: 1.6; }

/* ── st.status / st.expander glass ────────────── */
div[data-testid="stExpander"] details {
  background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0) 50%), rgba(12,42,56,0.55) !important;
  border: 1px solid rgba(28,64,85,0.85) !important;
  border-radius: var(--radius-md) !important;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}
div[data-testid="stExpander"] summary { color: var(--text-main) !important; }
div[data-testid="stExpander"] summary:hover { color: var(--text-bright) !important; }

/* Scrollbars */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--midnight); }
::-webkit-scrollbar-thumb { background: var(--border-2); border-radius: var(--radius-pill); }
::-webkit-scrollbar-thumb:hover { background: var(--duck); }

/* Hide Streamlit chrome — minimal and safe: never touch the header/toolbar
   region, because the sidebar expand control lives there. */
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] {
  background: transparent !important;
  box-shadow: none !important;
}
</style>
"""

st.markdown(STYLES, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# Note: per the Egis design system, never reconstruct the logo graphic in
# SVG/code — this header is a typographic product wordmark, not the logo.
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="egis-topbar">
  <div>
    <div class="egis-wordmark">
      <span class="egis-e">E</span><span style="color:#fff;">GIS</span>
      <span class="egis-separator">·</span>
      <span class="egis-tendly">TENDLY</span>
    </div>
    <div class="egis-underscore"></div>
    <div class="egis-product">
      AI Tender Intelligence Platform
      <span class="dim">&nbsp;&nbsp;·&nbsp;&nbsp;Internal Operations Tool</span>
    </div>
  </div>
  <div class="egis-motto-block">
    <div class="egis-motto-line">IMAGINE &nbsp;·&nbsp; CREATE &nbsp;·&nbsp; <span class="highlight">ACHIEVE</span></div>
    <div class="egis-motto-tag">Egis Group</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "analysis":        None,
    "pages":           [],
    "full_text":       "",
    "structured_text": "",
    "filename":        "",
    "doc_id":          "",
    "pdf_stats":       {},
    "chat_history":    [],
    "checklist_state": {},      # {item_index(int): bool}
    "tender_history":  [],
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def esc(v: Any) -> str:
    """HTML-escape any value before it is interpolated into unsafe_allow_html
    markup. PDF text and model output routinely contain < > & characters that
    would otherwise break the layout or inject markup."""
    return html.escape(str(v), quote=False)


_ALERT_KINDS = {
    "error":   ("✕", "var(--red)",    "rgba(224,82,82,0.07)",  "rgba(224,82,82,0.3)"),
    "warning": ("!", "var(--orange)", "rgba(224,154,58,0.07)", "rgba(224,154,58,0.3)"),
    "success": ("✓", "var(--green)",  "rgba(171,192,34,0.07)", "rgba(171,192,34,0.3)"),
    "info":    ("i", "var(--teal)",   "rgba(0,153,165,0.07)",  "rgba(0,153,165,0.3)"),
}


def ui_alert(kind: str, title: str, body: str = "") -> None:
    """Branded, severity-aware alert (replaces the one-colour st.* defaults).
    `title` and `body` may contain trusted inline markup; escape any user/PDF
    text with esc() before passing it in."""
    icon, col, bg, bd = _ALERT_KINDS.get(kind, _ALERT_KINDS["info"])
    body_html = f'<div class="ui-alert-body">{body}</div>' if body else ""
    st.markdown(f"""
    <div class="ui-alert" style="background:{bg};border-color:{bd};">
      <span class="ui-alert-icon" style="color:{col};border-color:{bd};">{icon}</span>
      <div>
        <div class="ui-alert-title" style="color:{col};">{title}</div>
        {body_html}
      </div>
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# PDF EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
_SECTION_MARKERS: dict[str, str] = {
    "[SECTION: SCOPE OF WORK]":      r'\bscope\s+of\s+(work|services|supply|services?\s+and\s+supply)\b',
    "[SECTION: DELIVERABLES]":       r'\bdeliverables?\b',
    "[SECTION: ELIGIBILITY]":        r'\b(eligibility|qualification\s+criteria|prequalification|minimum\s+requirements?)\b',
    "[SECTION: SUBMISSION]":         r'\bsubmission\s+(requirements?|instructions?|procedure|checklist|format)\b',
    "[SECTION: DATES & DEADLINES]":  r'\b(important\s+dates|key\s+dates|tender\s+schedule|timeline|bid\s+schedule)\b',
    "[SECTION: EVALUATION]":         r'\b(evaluation\s+criteria|scoring|award\s+criteria|selection\s+criteria|technical\s+score)\b',
    "[SECTION: COMMERCIAL TERMS]":   r'\b(commercial\s+terms|payment\s+terms|bid\s+security|performance\s+bond|liquidated\s+damages)\b',
    "[SECTION: CHECKLIST]":          r'\b(checklist|list\s+of\s+(required\s+)?documents?|documents?\s+required)\b',
    "[SECTION: RISK]":               r'\b(risk\s+register|risk\s+allocation|risk\s+matrix)\b',
    "[SECTION: INSURANCE]":          r'\binsurance\s+requirements?\b',
    "[SECTION: GENERAL CONDITIONS]": r'\b(general\s+conditions?|special\s+conditions?|conditions?\s+of\s+contract)\b',
    "[SECTION: JV & CONSORTIUM]":    r'\b(joint\s+venture|consortium|teaming\s+arrangement)\b',
}

_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "deadline":    ["deadline", "submission", "closing date", "due date", "query deadline", "bid closing"],
    "scope":       ["scope of work", "scope of services", "deliverables", "works", "services"],
    "eligibility": ["eligibility", "qualification", "minimum requirement", "experience", "turnover", "years"],
    "checklist":   ["checklist", "required documents", "document list", "submission checklist"],
    "commercial":  ["payment", "invoice", "retention", "advance", "milestone", "bid security", "bond", "liquidated damages", "ld clause"],
    "evaluation":  ["evaluation", "scoring", "technical score", "financial score", "criteria", "weight"],
    "risk":        ["risk", "red flag", "concern", "liability", "penalty"],
    "jv":          ["jv", "joint venture", "consortium", "teaming", "lead partner", "subcontract"],
    "insurance":   ["insurance", "indemnity", "public liability", "professional indemnity"],
    "dates":       ["date", "deadline", "timeline", "schedule", "validity", "pre-bid"],
    "legal":       ["governing law", "jurisdiction", "dispute", "arbitration", "court"],
}


def _clean(raw: str) -> str:
    """Remove PDF extraction artefacts while preserving structure."""
    raw = re.sub(r'[ \t]{3,}', '  ', raw)
    raw = re.sub(r'\n{4,}', '\n\n\n', raw)
    lines = []
    for ln in raw.splitlines():
        stripped = ln.strip()
        # Drop lines that are pure page-number artefacts (e.g. "3", "  - 14 -  ")
        if re.fullmatch(r'[-–—\s\d]{1,6}', stripped):
            continue
        lines.append(ln)
    return '\n'.join(lines).strip()


def _table_to_text(page) -> str:
    """Extract tables from a pdfplumber page as pipe-delimited text."""
    out = ""
    try:
        for tbl in (page.extract_tables() or []):
            rows = []
            for row in tbl:
                cells = [(c or "").strip() for c in row]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                out += "\n[TABLE]\n" + "\n".join(rows) + "\n[/TABLE]\n"
    except Exception:
        pass
    return out


def _annotate_sections(text: str) -> str:
    """Inject [SECTION: …] markers before lines that match tender headings,
    guiding the LLM to the right part of the document for each field."""
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if 3 < len(stripped) < 120:  # headings are short-ish lines
            for marker, pat in _SECTION_MARKERS.items():
                if re.search(pat, stripped, re.IGNORECASE):
                    out_lines.append(f"\n{marker}")
                    break
        out_lines.append(line)
    return "\n".join(out_lines)


def extract_pdf(file) -> tuple[list[dict], str, str, dict]:
    """Full PDF extraction pipeline.

    Returns:
        pages           — list of page dicts for retrieval-augmented chat
        full_text       — clean concatenated text for display
        structured_text — section-annotated text for AI analysis
        stats           — document quality metrics
    """
    pages: list[dict] = []
    image_pages = 0

    with pdfplumber.open(file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            raw_text   = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            table_text = _table_to_text(page)

            is_image = len(raw_text.strip()) < CFG.PDF_MIN_PAGE_TEXT
            if is_image:
                image_pages += 1
                page_text = f"\n\n━━ PAGE {i + 1} [IMAGE / SCANNED — no text] ━━\n"
            else:
                page_text = f"\n\n━━ PAGE {i + 1} ━━\n{_clean(raw_text + table_text)}"

            pages.append({"num": i + 1, "text": page_text, "is_image": is_image})

    full_text       = "".join(p["text"] for p in pages)
    structured_text = _annotate_sections(full_text)

    text_pages  = total_pages - image_pages
    words       = len(full_text.split())
    quality_pct = round((text_pages / max(total_pages, 1)) * 100)

    stats = {
        "pages":       total_pages,
        "words":       words,
        "chars":       len(full_text),
        "text_pages":  text_pages,
        "image_pages": image_pages,
        "quality_pct": quality_pct,
    }
    log.info("PDF extracted — %d pages (%d text, %d image), %d words, quality %d%%",
             total_pages, text_pages, image_pages, words, quality_pct)
    return pages, full_text, structured_text, stats


def build_analysis_context(structured_text: str) -> str:
    """Build an intelligently-windowed context string for the analysis call.

    Always includes the document head (cover, instructions) and tail
    (checklists, T&Cs), and fills the remaining budget from the middle third
    (scope, eligibility, evaluation). Avoids naïve first-N-chars truncation.
    """
    budget = CFG.PDF_ANALYSIS_CHAR_BUDGET
    n      = len(structured_text)
    if n <= budget:
        return structured_text

    head = structured_text[:CFG.PDF_HEAD_CHARS]
    tail = structured_text[max(0, n - CFG.PDF_TAIL_CHARS):]

    mid_budget = budget - len(head) - len(tail)
    if mid_budget > 2_000:
        mid_start = max(CFG.PDF_HEAD_CHARS, n // 3)
        mid_end   = min(n - CFG.PDF_TAIL_CHARS, 2 * n // 3)
        mid_slice = structured_text[mid_start: min(mid_start + mid_budget, mid_end)]
        mid_block = (f"\n\n[… MID-DOCUMENT EXTRACT "
                     f"(chars {mid_start}–{mid_start + len(mid_slice)}) …]\n\n{mid_slice}")
    else:
        mid_block = ""

    context = (head + mid_block
               + f"\n\n[… END SECTION (last {CFG.PDF_TAIL_CHARS // 1000}k chars) …]\n\n"
               + tail)
    log.info("Analysis context: %d chars (budget %d, doc %d)", len(context), budget, n)
    return context


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL ENGINE  (for Q&A)
# ─────────────────────────────────────────────────────────────────────────────
def _score_page(page_text: str, query: str) -> float:
    """Score a page's relevance to a query using TF-style keyword matching
    weighted by topic groups. Runs in-process — no embedding model needed."""
    q_lower = query.lower()
    p_lower = page_text.lower()
    score   = 0.0

    # 1. Direct word overlap between query tokens and page text
    for tok in set(re.findall(r'\b\w{4,}\b', q_lower)):
        score += min(p_lower.count(tok), 5) * 1.0

    # 2. Topic-group bonus: if the query mentions a topic, boost matching pages
    for kws in _TOPIC_KEYWORDS.values():
        if any(kw in q_lower for kw in kws):
            score += sum(1 for kw in kws if kw in p_lower) * 2.0

    # 3. Section marker / table bonuses (tables hold dates, scores, checklists)
    if "[SECTION:" in page_text:
        score += 3.0
    if "[TABLE]" in page_text:
        score += 2.0
    return score


def retrieve_relevant_context(
    pages: list[dict],
    query: str,
    max_snippets: int = CFG.CHAT_MAX_SNIPPETS,
    snippet_chars: int = CFG.CHAT_SNIPPET_CHARS,
) -> tuple[str, list[int]]:
    """Return a focused context string built from the most relevant pages,
    plus the page numbers used (shown to the user as sources)."""
    if not pages:
        return "", []

    scored = [(p["num"], _score_page(p["text"], query), p["text"])
              for p in pages if not p.get("is_image")]
    scored.sort(key=lambda x: x[1], reverse=True)
    top_pages = scored[:max_snippets]

    snippets, used, budget = [], 0, max_snippets * snippet_chars
    for num, _, text in top_pages:
        if used >= budget:
            break
        chunk = text[:snippet_chars]
        snippets.append(f"[PAGE {num}]\n{chunk}")
        used += len(chunk)

    page_nums_used = sorted(num for num, _, _ in top_pages)
    log.info("RAG retrieval: query=%r → pages %s", query[:60], page_nums_used)
    return "\n\n---\n\n".join(snippets), page_nums_used


# ─────────────────────────────────────────────────────────────────────────────
# AI ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def _call_api(messages: list[dict], max_tokens: int) -> str:
    """OpenRouter chat-completion call with model fallbacks and exponential
    backoff. Raises RuntimeError with a user-readable message on failure."""
    if not CFG.OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file or "
            "Streamlit secrets, then reload the app."
        )

    headers = {
        "Authorization": f"Bearer {CFG.OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://egis.com/tendly",
        "X-Title":       "Tendly · Egis AI Tender Intelligence",
    }
    payload: dict[str, Any] = {
        "model":       CFG.OPENROUTER_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": 0.05,
    }
    if CFG.FALLBACK_MODELS:
        # OpenRouter tries these in order if the primary model fails/overloads.
        payload["models"] = [CFG.OPENROUTER_MODEL] + CFG.FALLBACK_MODELS

    last_err: Exception | None = None
    for attempt in range(CFG.API_MAX_RETRIES):
        try:
            resp = requests.post(CFG.API_BASE_URL, headers=headers,
                                 json=payload, timeout=CFG.API_TIMEOUT)

            if resp.status_code == 401:
                raise RuntimeError("OpenRouter rejected the API key (401). "
                                   "Check OPENROUTER_API_KEY.")
            if resp.status_code == 402:
                raise RuntimeError("OpenRouter account has no credit (402). "
                                   "Free models still require a valid account.")
            if resp.status_code == 404:
                raise RuntimeError(
                    f"Model '{CFG.OPENROUTER_MODEL}' was not found (404). Free model "
                    "IDs rotate — set OPENROUTER_MODEL to a current free model."
                )
            if resp.status_code in (408, 429, 500, 502, 503, 524):
                raise requests.ConnectionError(f"HTTP {resp.status_code} (retryable)")
            resp.raise_for_status()

            data = resp.json()
            if "choices" not in data:
                err = data.get("error", {})
                raise RuntimeError(f"API error [{err.get('code', '?')}]: "
                                   f"{err.get('message', data)}")

            content = (data["choices"][0]["message"].get("content") or "").strip()
            if not content:
                # Free models occasionally return empty completions under load.
                raise requests.ConnectionError("Empty model response (retryable)")

            usage = data.get("usage", {})
            log.info("API OK — model=%s tokens in=%s out=%s attempt=%d",
                     data.get("model", "?"),
                     usage.get("prompt_tokens", "?"),
                     usage.get("completion_tokens", "?"), attempt + 1)
            return content

        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            wait = CFG.API_RETRY_DELAY * (2 ** attempt)
            log.warning("API attempt %d failed (%s) — retrying in %.1fs",
                        attempt + 1, e, wait)
            time.sleep(wait)
        except requests.HTTPError as e:
            raise RuntimeError(f"HTTP {resp.status_code}: {e}") from e

    raise RuntimeError(
        "The AI service did not respond after "
        f"{CFG.API_MAX_RETRIES} attempts (free models are shared and can be "
        f"busy — try again in a minute). Last error: {last_err}"
    )


def _parse_json(raw: str) -> dict:
    """Robustly parse JSON from a model response: strips markdown fences,
    preamble text and trailing commas."""
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*\n?', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\n?```\s*$', '', raw).strip()
    start, end = raw.find('{'), raw.rfind('}')
    if start != -1 and end > start:
        raw = raw[start:end + 1]
    raw = re.sub(r',\s*([}\]])', r'\1', raw)  # trailing commas
    return json.loads(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Analysis prompt
# ─────────────────────────────────────────────────────────────────────────────
_ANALYSIS_SYSTEM = """You are a Principal Tender Analyst with 25 years of experience in infrastructure, engineering, and professional services procurement across the GCC, Asia-Pacific, and Europe.

Your task: Analyse the supplied tender / RFP document extract and return a SINGLE, COMPLETE JSON object.

STRICT OUTPUT RULES:
1. Output ONLY raw JSON — no markdown fences, no preamble text, no commentary outside the JSON.
2. Use JSON null for any field genuinely absent from the document. NEVER fabricate, guess, or infer values that are not written in the document.
3. Extract EXACT text for dates, amounts, reference numbers — do not paraphrase or reformat them.
4. For array fields, extract ALL items found — never truncate.
5. go_no_go_score must be an integer 0–100.
6. The document may be a partial extract; base the analysis only on what is present.

JSON SCHEMA (return all keys):

{
  "project_name":         "Full project name as written",
  "project_location":     "City, Region, Country",
  "issuer":               "Full organisation name",
  "issuer_department":    "Department or division, if stated",
  "tender_reference":     "Tender / RFP / ITB reference number",
  "sector":               "e.g. Transport, Water, Energy, Buildings, ICT, Consultancy",
  "sub_sector":           "More specific e.g. Highway Design, Wastewater Treatment",
  "contract_type":        "e.g. Lump Sum / BOQ Re-measurable / EPC Turnkey / Design & Build / Consultancy / Framework",
  "tender_value":         "Stated budget or 'Not disclosed'",
  "currency":             "ISO code e.g. AED, USD, EUR, SAR, INR",
  "project_duration":     "Contract duration as stated",
  "summary":              "3–4 sentence executive summary: what is procured, who is the client, where, scale.",
  "scope": ["Specific scope item as written", "..."],
  "eligibility": ["Exact eligibility requirement with thresholds", "..."],
  "submission_deadline":       "Full date, time, timezone as written",
  "query_submission_deadline": "Clarification query deadline",
  "tender_validity_days":      "Number e.g. 90 or string e.g. '120 days from submission'",
  "bid_opening_date":          "Date and time of public bid opening",
  "pre_bid_meeting":           "Date, time, venue",
  "award_expected":            "Expected award date or period",
  "important_dates": [
    {"label": "Milestone name e.g. Pre-Bid Meeting", "date": "exact date as written"}
  ],
  "submission_checklist": ["Exact document / item required as listed in RFP", "..."],
  "submission_requirements": ["Format, copies, binding, delivery method requirements", "..."],
  "bid_security":       "Type, amount or %, validity period",
  "performance_bond":   "% of contract value, form, timing",
  "retention":          "Retention % and release conditions",
  "liquidated_damages": "Rate, cap, conditions",
  "advance_payment":    "Advance % and conditions",
  "payment_terms":      "Milestone / monthly progress / final payment; retainage",
  "insurance_requirements": ["Insurance type: minimum coverage and conditions", "..."],
  "jv_consortium_rules":    "Whether permitted, lead partner requirements, equity limits",
  "subcontracting_rules":   "Permission, % limit, notification requirements",
  "evaluation_criteria": ["Criterion with score/weight if stated", "..."],
  "technical_weight":   "e.g. 70% or 70 points",
  "financial_weight":   "e.g. 30% or 30 points",
  "evaluation_method":  "e.g. LPTA / Best Value / QCBS",
  "language_requirement":  "Submission language(s)",
  "governing_law":         "Governing law / jurisdiction",
  "dispute_resolution":    "Arbitration body, seat, court",
  "risks": [
    {"description": "Specific actionable risk", "level": "High|Medium|Low", "category": "Commercial|Technical|Legal|Schedule|Compliance|Financial"}
  ],
  "red_flags": ["Specific concern requiring escalation before bidding", "..."],
  "go_no_go_score":    0,
  "go_no_go_rationale": "2–3 sentences explaining score based on value, fit, risk, competition.",
  "recommendation":    "GO | CONDITIONAL GO | NO-GO — followed by 2–3 sentences of clear reasoning.",
  "win_themes": ["Specific differentiator Egis could leverage", "..."],
  "key_questions": ["High-value clarification question for pre-bid or RFI", "..."],
  "watch_items": ["Item to monitor during bid prep", "..."]
}

important_dates rules: include ONLY milestones that actually appear in the document, with their exact wording. Do not output placeholder rows or invented dates; if no dates are found, return an empty array.

go_no_go_score guidance:
  ≥70 → GO        (strong fit, manageable risk, clear opportunity)
  40–69 → CONDITIONAL GO  (proceed with conditions or further review)
  <40 → NO-GO     (poor fit, high risk, or disqualifying factor)

Fill every field that has evidence in the document."""


def run_analysis(structured_text: str) -> dict:
    """Run AI extraction on the structured tender document, with one automatic
    repair retry if the model returns malformed JSON."""
    context = build_analysis_context(structured_text)
    messages = [
        {"role": "system", "content": _ANALYSIS_SYSTEM},
        {"role": "user", "content": (
            "Analyse this tender document extract and return the complete JSON.\n\n"
            f"{'═' * 60}\n{context}\n{'═' * 60}"
        )},
    ]
    raw = _call_api(messages, max_tokens=6000)
    try:
        result = _parse_json(raw)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse failed (%s) — requesting a corrected response", exc)
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                "Your previous response was not valid JSON "
                f"(parser error: {exc}). Resend the COMPLETE corrected JSON "
                "object only — no fences, no commentary, no truncation."
            )},
        ]
        raw = _call_api(messages, max_tokens=6000)
        result = _parse_json(raw)

    filled = sum(1 for v in result.values() if v not in (None, [], ""))
    log.info("Analysis complete — %d/%d fields populated", filled, len(result))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Chat / Q&A
# ─────────────────────────────────────────────────────────────────────────────
_CHAT_SYSTEM_TEMPLATE = """You are a senior bid manager and tender analyst with deep expertise in infrastructure and professional services procurement.

Today's date is {today}.

You are answering a question about the tender document below. Answer with precision and practical insight — as if briefing your bid team before a submission.

Guidelines:
- Be direct and specific. Reference exact clauses, dates, amounts, and page numbers where available.
- Write in plain text. Use simple "-" bullets for lists; do NOT use markdown bold, headers, or tables.
- Flag any compliance traps, risks, or missing information the team should know.
- If the answer is not clearly stated in the provided pages, say so explicitly — do not guess.
- Keep responses concise but complete.

TENDER DOCUMENT — MOST RELEVANT PAGES:
{context}"""


def ask_followup(
    question: str,
    pages: list[dict],
    history: list[dict],
    analysis: dict | None = None,
) -> tuple[str, list[int]]:
    """Answer a question about the tender using retrieval-augmented context.
    Returns (answer text, page numbers used as sources)."""
    context, page_nums = retrieve_relevant_context(pages, question)

    analysis_summary = ""
    if analysis:
        def _s(k: str) -> str:
            v = analysis.get(k)
            return str(v) if v and str(v).lower() not in ("null", "none") else "not stated"

        analysis_summary = (
            "\n\nSTRUCTURED ANALYSIS SUMMARY (use as grounding — verify against pages above):\n"
            f"Project: {_s('project_name')} | Location: {_s('project_location')}\n"
            f"Submission Deadline: {_s('submission_deadline')}\n"
            f"Query Deadline: {_s('query_submission_deadline')}\n"
            f"Tender Validity: {_s('tender_validity_days')}\n"
            f"Bid Security: {_s('bid_security')} | Performance Bond: {_s('performance_bond')}\n"
            f"LDs: {_s('liquidated_damages')} | Payment: {_s('payment_terms')}\n"
        )

    system_msg = _CHAT_SYSTEM_TEMPLATE.format(
        today=date.today().strftime("%d %B %Y"),
        context=context + analysis_summary,
    )

    messages = [{"role": "system", "content": system_msg}]
    for turn in history[-CFG.CHAT_HISTORY_TURNS:]:
        messages.append({"role": "user",      "content": turn["q"]})
        messages.append({"role": "assistant", "content": turn["a"]})
    messages.append({"role": "user", "content": question})

    answer = _call_api(messages, max_tokens=1200)
    return answer, page_nums


def _run_question(question: str) -> None:
    """Shared handler for quick-question buttons and the chat form."""
    with st.spinner("Finding relevant pages and answering…"):
        try:
            ans, pgs = ask_followup(
                question,
                st.session_state.pages,
                st.session_state.chat_history,
                st.session_state.analysis,
            )
            st.session_state.chat_history.append({
                "q": question, "a": ans,
                "ts": datetime.now().strftime("%H:%M"),
                "sources": pgs,
            })
            st.rerun()
        except RuntimeError as exc:
            ui_alert("error", "Could not answer", esc(str(exc)))
        except Exception as exc:
            ui_alert("error", "Unexpected error", esc(str(exc)))
            log.exception("Chat error")


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────
def file_md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


_DATE_FMTS = [
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d %B, %Y",
    "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d %B %Y, %H:%M", "%d %b %Y, %H:%M",
    "%d %B %Y %H:%M", "%d %b %Y %H:%M",
    "%Y/%m/%d", "%d.%m.%Y",
]

_NULL_VALS = {"null", "none", "not specified", "not disclosed", "not stated",
              "tbc", "tbd", "n/a", "-", "—", ""}


def is_null(v: Any) -> bool:
    return v is None or str(v).strip().lower() in _NULL_VALS


def days_until(date_str: str | None) -> int | None:
    if is_null(date_str):
        return None
    clean = re.sub(r'\s+', ' ', str(date_str).strip())
    clean = re.sub(r'(\d{1,2})(st|nd|rd|th)\b', r'\1', clean, flags=re.IGNORECASE)
    candidates = [clean, clean.split(" at ")[0].strip(),
                  clean.split(",")[0].strip(), clean.split("(")[0].strip()]
    for cand in candidates:
        for fmt in _DATE_FMTS:
            try:
                return (datetime.strptime(cand, fmt).date() - date.today()).days
            except ValueError:
                continue
    return None


def deadline_display(days: int | None) -> tuple[str, str]:
    """(css_class, pill_text)"""
    if days is None:
        return "", ""
    if days < 0:   return "crit", "PASSED"
    if days == 0:  return "crit", "TODAY ⚠"
    if days <= 3:  return "crit", f"{days}d ⚠"
    if days <= 10: return "warn", f"{days}d left"
    return "ok", f"{days}d"


def score_color(s: int) -> str:
    return "#abc022" if s >= 70 else ("#e09a3a" if s >= 40 else "#e05c5c")


def verdict_info(s: int) -> tuple[str, str, str]:
    """(css_modifier, label, color)"""
    if s >= 70: return "go",          "GO",             "#abc022"
    if s >= 40: return "conditional", "CONDITIONAL GO", "#e09a3a"
    return "nogo", "NO-GO", "#e05c5c"


def pct_int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r'(\d+)', str(s))
    return int(m.group(1)) if m else None


def null_disp(v: Any) -> str:
    """Display-safe (escaped) string, or a styled 'Not stated'."""
    if is_null(v):
        return "<span style='color:#2a5060;font-style:italic;'>Not stated</span>"
    return esc(v)


def li_html(items: list[str], color: str = "#97b8bb") -> str:
    if not items:
        return "<li style='color:#2a5060;font-style:italic;'>Not specified in document</li>"
    return "".join(
        f"<li style='margin-bottom:7px;color:{color};'>{esc(i)}</li>" for i in items
    )


def kv_html(pairs: list[tuple[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td class='kv-key'>{k}</td><td class='kv-val'>{null_disp(v)}</td></tr>"
        for k, v in pairs
    )
    return f"<table class='kv-table'>{rows}</table>"


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────
def build_markdown_report(a: dict, filename: str) -> str:
    now   = datetime.now().strftime("%d %b %Y, %H:%M")
    score = int(a.get("go_no_go_score") or 0)
    _, vtxt, _ = verdict_info(score)

    def s(k: str) -> str:
        v = a.get(k)
        return str(v) if not is_null(v) else "N/A"

    def bl(k: str) -> str:
        items = a.get(k) or []
        return "\n".join(f"- {i}" for i in items) if items else "- Not specified"

    def risk_md() -> str:
        risks = sorted(a.get("risks") or [],
                       key=lambda x: {"High": 0, "Medium": 1, "Low": 2}.get(x.get("level", "Low"), 1))
        return "\n".join(
            f"- **[{r.get('level', '?')} · {r.get('category', '')}]** {r.get('description', '')}"
            for r in risks
        ) or "- None identified"

    def dates_md() -> str:
        rows = [f"| {d.get('label', '')} | {d.get('date', '')} |"
                for d in (a.get("important_dates") or []) if not is_null(d.get("date"))]
        return ("| Milestone | Date |\n|---|---|\n" + "\n".join(rows)) if rows else "No dates extracted."

    def cl_md() -> str:
        return "\n".join(f"- [ ] {i}" for i in (a.get("submission_checklist") or [])) or "- Not specified"

    return f"""# TENDLY AI TENDER ANALYSIS REPORT
**Generated:** {now}  
**Document:** {filename}  
**AI Model:** {CFG.OPENROUTER_MODEL}  
**Tendly Version:** {CFG.APP_VERSION}

---

## 🎯 GO / NO-GO VERDICT: {vtxt}
**Score:** {score} / 100

{s("go_no_go_rationale")}

**Recommendation:** {s("recommendation")}

---

## 🔵 PROJECT OVERVIEW

| Field | Detail |
|---|---|
| **Project Name** | {s("project_name")} |
| **Location** | {s("project_location")} |
| **Issuing Body** | {s("issuer")} |
| **Department** | {s("issuer_department")} |
| **Reference** | {s("tender_reference")} |
| **Sector** | {s("sector")} — {s("sub_sector")} |
| **Contract Type** | {s("contract_type")} |
| **Tender Value** | {s("tender_value")} {s("currency")} |
| **Duration** | {s("project_duration")} |
| **Language** | {s("language_requirement")} |
| **Governing Law** | {s("governing_law")} |

### Executive Summary
{s("summary")}

---

## 📅 TENDER TIMELINE

{dates_md()}

| | |
|---|---|
| **Submission Deadline** | {s("submission_deadline")} |
| **Query Deadline** | {s("query_submission_deadline")} |
| **Tender Validity** | {s("tender_validity_days")} |

---

## 📐 SCOPE OF WORK

{bl("scope")}

---

## ✅ SUBMISSION CHECKLIST

{cl_md()}

---

## 📋 ELIGIBILITY CRITERIA

{bl("eligibility")}

---

## 📦 SUBMISSION REQUIREMENTS

{bl("submission_requirements")}

---

## 💼 COMMERCIAL TERMS

| Term | Detail |
|---|---|
| Bid Security / EMD | {s("bid_security")} |
| Performance Bond | {s("performance_bond")} |
| Retention | {s("retention")} |
| Liquidated Damages | {s("liquidated_damages")} |
| Advance Payment | {s("advance_payment")} |
| Payment Terms | {s("payment_terms")} |
| JV / Consortium | {s("jv_consortium_rules")} |
| Subcontracting | {s("subcontracting_rules")} |
| Dispute Resolution | {s("dispute_resolution")} |

### Insurance Requirements
{bl("insurance_requirements")}

---

## ⚖️ EVALUATION CRITERIA

**Method:** {s("evaluation_method")}  
**Technical Weight:** {s("technical_weight")} | **Financial Weight:** {s("financial_weight")}

{bl("evaluation_criteria")}

---

## ⚠️ RISK REGISTER

{risk_md()}

### 🚩 Red Flags
{chr(10).join("- 🚩 " + f for f in (a.get("red_flags") or [])) or "- None identified"}

---

## 🏆 WIN THEMES

{bl("win_themes")}

---

## ❓ KEY CLARIFICATION QUESTIONS

{bl("key_questions")}

---

## 👁 WATCH ITEMS

{bl("watch_items")}

---

*Report generated by **Tendly v{CFG.APP_VERSION}** · Egis AI Tender Intelligence · {now}.
AI-extracted content — always verify critical details against the original RFP.*
"""


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:0.5rem 0 0.9rem;">
      <div style="font-family:'Urbanist','Segoe UI',sans-serif;font-size:0.92rem;font-weight:800;
                  letter-spacing:-0.2px;color:#fff;text-transform:uppercase;line-height:1;">
        <span style="color:#ABC022;">T</span>ENDLY
      </div>
      <div style="font-family:'Urbanist',sans-serif;font-size:0.52rem;font-weight:700;
                  letter-spacing:3px;text-transform:uppercase;color:#0099A5;margin-top:4px;">
        Session History
      </div>
      <div style="height:1px;background:linear-gradient(90deg,rgba(0,153,165,0.4),transparent);
                  margin-top:0.75rem;"></div>
    </div>
    """, unsafe_allow_html=True)

    hist = st.session_state.tender_history
    if not hist:
        st.markdown("""
        <div style="padding:0.6rem 0.1rem;border-left:2px solid #163545;padding-left:0.75rem;
                    margin:0.2rem 0 1rem;">
          <div style="font-size:0.74rem;color:#2a5060;line-height:1.6;">
            No analyses this session.
          </div>
          <div style="font-size:0.64rem;color:#163545;margin-top:3px;">
            Upload a tender PDF to begin.
          </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for i, h in enumerate(reversed(hist[-CFG.HISTORY_MAX:])):
            ah   = h["analysis"]
            proj = ah.get("project_name") or h["filename"]
            loc  = ah.get("project_location") or "—"
            sc   = int(ah.get("go_no_go_score") or 0)
            _, vt, vc = verdict_info(sc)
            is_current = bool(h.get("doc_id")) and h.get("doc_id") == st.session_state.doc_id
            cur_tag = ('<span style="font-size:0.52rem;color:#ABC022;letter-spacing:1.5px;'
                       'text-transform:uppercase;">● Open now</span>') if is_current else ""
            st.markdown(f"""
            <div class="sb-card{' sb-card--current' if is_current else ''}">
              <div class="sb-title">{esc(str(proj)[:42])}</div>
              <div class="sb-meta">📍 {esc(str(loc)[:34])}</div>
              <div class="sb-meta" style="color:{vc};margin-top:4px;">● {vt} &nbsp;·&nbsp; {sc}/100</div>
              <div class="sb-meta">🕐 {h["ts"]} &nbsp;{cur_tag}</div>
            </div>
            """, unsafe_allow_html=True)
            if not is_current and h.get("pages"):
                if st.button("Open analysis", key=f"hist_{i}_{str(h.get('doc_id'))[:8]}",
                             use_container_width=True,
                             help="Restore this document and its analysis."):
                    st.session_state.pages           = h["pages"]
                    st.session_state.full_text       = h["full_text"]
                    st.session_state.structured_text = h["structured_text"]
                    st.session_state.pdf_stats       = h["stats"]
                    st.session_state.filename        = h["filename"]
                    st.session_state.doc_id          = h["doc_id"]
                    st.session_state.analysis        = h["analysis"]
                    st.session_state.chat_history    = []
                    st.session_state.checklist_state = {
                        j: False
                        for j in range(len(h["analysis"].get("submission_checklist") or []))
                    }
                    st.session_state.pop("uploader", None)  # else the stale upload re-extracts
                    st.rerun()

    if st.session_state.doc_id:
        if st.button("⟲  Clear Workspace", use_container_width=True,
                     help="Clear the current document, analysis and chat. "
                          "Session history is kept."):
            for k in ("analysis", "pages", "full_text", "structured_text",
                      "filename", "doc_id", "pdf_stats", "chat_history",
                      "checklist_state"):
                st.session_state[k] = _DEFAULTS[k]
            st.session_state.pop("uploader", None)  # reset the file widget
            st.rerun()

    st.markdown('<div class="divider-thin"></div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="padding:0.4rem 0 0.6rem;">
      <div style="display:flex;align-items:baseline;gap:0.6rem;padding:0.22rem 0;">
        <span style="font-size:0.54rem;color:#1C4055;letter-spacing:0.8px;text-transform:uppercase;
                     white-space:nowrap;min-width:38%;">Model</span>
        <span style="font-size:0.6rem;color:#1C4055;line-height:1.4;word-break:break-all;">
          {esc(CFG.OPENROUTER_MODEL)}
        </span>
      </div>
      <div style="display:flex;align-items:baseline;gap:0.6rem;padding:0.22rem 0;">
        <span style="font-size:0.54rem;color:#1C4055;letter-spacing:0.8px;text-transform:uppercase;
                     white-space:nowrap;min-width:38%;">Context</span>
        <span style="font-size:0.6rem;color:#1C4055;line-height:1.4;">
          {CFG.PDF_ANALYSIS_CHAR_BUDGET // 1000}k chars
        </span>
      </div>
      <div style="display:flex;align-items:baseline;gap:0.6rem;padding:0.22rem 0;">
        <span style="font-size:0.54rem;color:#1C4055;letter-spacing:0.8px;text-transform:uppercase;
                     white-space:nowrap;min-width:38%;">Retrieval</span>
        <span style="font-size:0.6rem;color:#1C4055;line-height:1.4;">
          top-{CFG.CHAT_MAX_SNIPPETS} × {CFG.CHAT_SNIPPET_CHARS // 1000}k chars
        </span>
      </div>
      <div style="font-size:0.48rem;color:#163545;letter-spacing:0.8px;margin-top:0.5rem;">
        v{CFG.APP_VERSION} &nbsp;·&nbsp; Egis Tendly
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG GUARD — surface a missing key before the user wastes time
# ─────────────────────────────────────────────────────────────────────────────
if not HAS_KEY:
    ui_alert(
        "error",
        "AI engine not configured",
        "<b>OPENROUTER_API_KEY</b> is not set. Add it to a local <code>.env</code> "
        "file or your Streamlit Cloud secrets, then reload. You can still upload "
        "and inspect PDFs — AI analysis and Q&amp;A are disabled until a key is set.",
    )

# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT ROUTING — landing vs working view.
# The uploader is rendered in BOTH branches with the same key so Streamlit's
# widget tree stays consistent across reruns.
# ─────────────────────────────────────────────────────────────────────────────
_has_doc = bool(st.session_state.pages)

if _has_doc:
    # ── WORKING STATE: compact uploader bar at top ──────────────────────────
    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:0.3rem;">
      <span style="font-family:'Urbanist',sans-serif;font-size:0.54rem;font-weight:700;
                   letter-spacing:2.5px;text-transform:uppercase;color:#2E5A68;">
        Current Document &nbsp;·&nbsp; <span style="color:#6B8F96;">{esc(st.session_state.filename)}</span>
      </span>
      <span style="font-size:0.54rem;letter-spacing:1px;text-transform:uppercase;color:#163545;">
        Drop a new PDF below to replace it
      </span>
    </div>
    """, unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Upload Tender Document",
        type=["pdf"],
        key="uploader",
        label_visibility="collapsed",
        help="Upload a different tender to replace the current analysis.",
    )
else:
    # ── LANDING STATE: centered hero + upload + feature grid ────────────────
    st.markdown("""
    <div class="hero-wrap">
      <div style="font-family:'Urbanist',sans-serif;font-size:1.45rem;font-weight:800;
                  color:#F0F6F8;letter-spacing:-0.5px;line-height:1.3;">
        Upload a tender PDF to extract every critical detail<br>
        <span style="color:#0099A5;font-weight:300;">instantly, accurately, intelligently.</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    _u1, _u2, _u3 = st.columns([1, 2, 1])
    with _u2:
        uploaded_file = st.file_uploader(
            "Upload Tender Document",
            type=["pdf"],
            key="uploader",
            label_visibility="collapsed",
            help="Text-based PDFs only. Scanned / image-only PDFs require OCR pre-processing.",
        )
        st.markdown("""
        <div class="hero-note">
          PDF · text-based · up to 200 MB &nbsp;·&nbsp; scanned files need OCR
          &nbsp;·&nbsp; processed in memory, never stored
        </div>
        """, unsafe_allow_html=True)

    FEATURES = [
        ("📋", "Overview",            "Project, issuer, contract type, sector & governing law at a glance."),
        ("📐", "Scope & Eligibility", "Work scope and minimum qualification criteria, extracted verbatim."),
        ("📅", "Dates & Deadlines",   "Submission, pre-bid and query deadlines with live countdowns."),
        ("✅", "Smart Checklist",     "Interactive submission tracker with a readiness meter."),
        ("💼", "Commercial Terms",    "Bid bond, LDs, retention and payment milestones, decoded."),
        ("⚠️", "Risks & Red Flags",   "Categorised risk register with escalation-worthy red flags."),
        ("🎯", "Go / No-Go Verdict",  "0–100 score with rationale, win themes and key questions."),
        ("💬", "Ask Tendly",          "Full-document Q&A — every answer cites its source pages."),
    ]
    _cells = "".join(
        f'<div class="feat-card"><div class="feat-icon">{ic}</div>'
        f'<div class="feat-title">{t}</div><div class="feat-desc">{d}</div></div>'
        for ic, t, d in FEATURES
    )
    st.markdown(f'<div class="feat-grid">{_cells}</div>', unsafe_allow_html=True)

    st.markdown("""
    <div class="landing-foot">
      Imagine &nbsp;·&nbsp; Create &nbsp;·&nbsp; <span class="highlight">Achieve</span>
      &nbsp;&nbsp;—&nbsp;&nbsp; Egis Group
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD + EXTRACTION
# A stable per-upload identity (file_id, md5 fallback) detects new files
# without re-hashing the whole file on every rerun.
# ─────────────────────────────────────────────────────────────────────────────
if uploaded_file is not None:
    doc_id = getattr(uploaded_file, "file_id", None) or file_md5(uploaded_file.getvalue())

    if st.session_state.doc_id != doc_id:
        with st.spinner("Reading PDF — extracting text and tables…"):
            try:
                uploaded_file.seek(0)
                pages, full_text, structured_text, stats = extract_pdf(uploaded_file)
                st.session_state.pages           = pages
                st.session_state.full_text       = full_text
                st.session_state.structured_text = structured_text
                st.session_state.pdf_stats       = stats
                st.session_state.filename        = uploaded_file.name
                st.session_state.doc_id          = doc_id
                st.session_state.analysis        = None
                st.session_state.chat_history    = []
                st.session_state.checklist_state = {}
                st.rerun()  # switch to the working layout immediately
            except Exception as exc:
                ui_alert(
                    "error",
                    "Could not read this PDF",
                    f"{esc(exc)}<br>The file may be corrupted, "
                    "password-protected, or not a valid PDF.",
                )
                log.exception("PDF extraction error")
                st.stop()


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT WORKSPACE — driven by session state, so results survive
# uploader changes and widget reruns.
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.pages:
    stats     = st.session_state.pdf_stats
    full_text = st.session_state.full_text
    pages     = st.session_state.pages

    st.markdown('<div class="divider-main"></div>', unsafe_allow_html=True)

    # ── Stats bar ───────────────────────────────────────────────────────────
    q_pct   = stats.get("quality_pct", 100)
    q_class = "good" if q_pct >= 80 else ("warn" if q_pct >= 50 else "crit")

    segs = ""
    for i in range(5):
        filled  = q_pct >= (i + 1) * 20
        seg_cls = ("g" if q_pct >= 80 else ("w" if q_pct >= 50 else "b")) if filled else ""
        segs += f'<div class="quality-seg {seg_cls}"></div>'

    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-box {q_class}">
        <span class="stat-value">{stats.get('pages', '—')}</span>
        <span class="stat-label">Pages</span>
        <div class="quality-bar">{segs}</div>
      </div>
      <div class="stat-box">
        <span class="stat-value">{stats.get('words', 0):,}</span>
        <span class="stat-label">Words</span>
      </div>
      <div class="stat-box">
        <span class="stat-value">{stats.get('chars', 0) // 1000}k</span>
        <span class="stat-label">Characters</span>
      </div>
      <div class="stat-box {q_class}">
        <span class="stat-value">{q_pct}%</span>
        <span class="stat-label">Text Quality</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    if stats.get("image_pages", 0) > 0:
        ui_alert(
            "warning",
            f"{stats['image_pages']} image-only page(s) detected",
            "These pages contain no selectable text and cannot be analysed. "
            "For complete results, use a text-based PDF or pre-process the "
            "document with an OCR tool.",
        )

    # ── Analyse button ──────────────────────────────────────────────────────
    no_text = stats.get("words", 0) < CFG.PDF_MIN_READABLE_WORDS
    if no_text:
        ui_alert(
            "error",
            "Document is not machine-readable",
            "This PDF contains almost no extractable text, so analysis would be "
            "unreliable. Run it through an OCR tool first, then re-upload.",
        )

    # Button is shown only while there is no analysis yet — once results are
    # displayed it disappears (uploading a new PDF resets and brings it back).
    do_analyse = False
    if st.session_state.analysis is None:
        btn_col, _sp = st.columns([1, 3])
        with btn_col:
            do_analyse = st.button(
                "⚡  Analyse Tender",
                type="primary",
                use_container_width=True,
                disabled=no_text or not HAS_KEY,
                help=None if HAS_KEY else "Set OPENROUTER_API_KEY to enable analysis.",
            )

    if do_analyse:
        try:
            with st.spinner("Analysing tender…"):
                result = run_analysis(st.session_state.structured_text)
            st.session_state.analysis        = result
            st.session_state.chat_history    = []
            st.session_state.checklist_state = {
                i: False for i in range(len(result.get("submission_checklist") or []))
            }
            # Snapshot the full document state so the session-history panel
            # can restore this analysis later (re-analysing replaces entry).
            st.session_state.tender_history = [
                h for h in st.session_state.tender_history
                if h.get("doc_id") != st.session_state.doc_id
            ]
            st.session_state.tender_history.append({
                "doc_id":          st.session_state.doc_id,
                "filename":        st.session_state.filename,
                "analysis":        result,
                "pages":           st.session_state.pages,
                "full_text":       st.session_state.full_text,
                "structured_text": st.session_state.structured_text,
                "stats":           st.session_state.pdf_stats,
                "ts":              datetime.now().strftime("%d %b %Y %H:%M"),
            })
            if len(st.session_state.tender_history) > CFG.HISTORY_MAX:
                st.session_state.tender_history.pop(0)
            st.session_state["_flash"] = True
            st.rerun()
        except json.JSONDecodeError:
            ui_alert(
                "error",
                "Analysis failed — malformed AI response",
                "The AI returned an invalid response twice in a row. This "
                "occasionally happens on busy free models — please try again.",
            )
        except RuntimeError as exc:
            ui_alert("error", "Analysis failed", esc(str(exc)))
        except Exception as exc:
            ui_alert("error", "Unexpected error", esc(str(exc)))
            log.exception("Analysis error")

    # ────────────────────────────────────────────────────────────────────────
    # RESULTS
    # ────────────────────────────────────────────────────────────────────────
    if st.session_state.analysis:
        a = st.session_state.analysis

        if st.session_state.pop("_flash", None):
            st.toast("Analysis complete — verdict ready below.", icon="✅")

        st.markdown('<div class="divider-main"></div>', unsafe_allow_html=True)

        # ── Verdict banner ──────────────────────────────────────────────────
        score = int(a.get("go_no_go_score") or 0)
        v_mod, v_label, v_color = verdict_info(score)

        st.markdown(f"""
        <div class="verdict verdict--{v_mod}">
          <div class="verdict-eyebrow">Tendly Go / No-Go Assessment</div>
          <div class="verdict-word" style="color:{v_color};">{v_label}</div>
          <div class="verdict-score">{score} / 100</div>
          <div class="verdict-rationale">{esc(a.get('go_no_go_rationale') or '')}</div>
        </div>
        """, unsafe_allow_html=True)

        tabs = st.tabs([
            "📋  Overview",
            "📐  Scope & Eligibility",
            "📅  Dates & Deadlines",
            "✅  Submission Checklist",
            "💼  Commercial",
            "⚠️  Risks & Flags",
            "🎯  Assessment",
            "💬  Ask Tendly",
        ])

        # ════════════════════ TAB 1 — OVERVIEW ════════════════════
        with tabs[0]:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"""
                <div class="hero-card">
                  <div class="hero-label">Project Name</div>
                  <div class="hero-value">{esc(a.get('project_name') or 'Not extracted')}</div>
                </div>""", unsafe_allow_html=True)
            with c2:
                st.markdown(f"""
                <div class="hero-card">
                  <div class="hero-label">📍 Location</div>
                  <div class="hero-value">{esc(a.get('project_location') or 'Not extracted')}</div>
                </div>""", unsafe_allow_html=True)

            st.markdown(f"""
            <div class="card card--teal-left">
              <div class="card-label">Executive Summary</div>
              <div class="card-body">{esc(a.get('summary') or 'Not extracted')}</div>
            </div>""", unsafe_allow_html=True)

            oc1, oc2, oc3 = st.columns(3)
            with oc1:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">Client & Reference</div>
                  {kv_html([
                      ("Issuing Body", a.get("issuer")),
                      ("Department", a.get("issuer_department")),
                      ("Reference No.", a.get("tender_reference")),
                  ])}
                </div>""", unsafe_allow_html=True)
            with oc2:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">Tender Details</div>
                  {kv_html([
                      ("Sector", f"{a.get('sector') or '—'} · {a.get('sub_sector') or '—'}"),
                      ("Contract Type", a.get("contract_type")),
                      ("Value", f"{a.get('tender_value') or '—'} {a.get('currency') or ''}".strip()),
                      ("Duration", a.get("project_duration")),
                  ])}
                </div>""", unsafe_allow_html=True)
            with oc3:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">Conditions</div>
                  {kv_html([
                      ("Language", a.get("language_requirement")),
                      ("Governing Law", a.get("governing_law")),
                      ("Dispute Resolution", a.get("dispute_resolution")),
                  ])}
                </div>""", unsafe_allow_html=True)

        # ════════════════════ TAB 2 — SCOPE & ELIGIBILITY ════════════════════
        with tabs[1]:
            sc1, sc2 = st.columns(2)
            with sc1:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">📐 Scope of Work</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">
                    {li_html(a.get('scope') or [])}
                  </ul>
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div class="card-label">⚖️ Evaluation Criteria</div>
                  <div style="display:flex;gap:1.2rem;margin-bottom:0.7rem;flex-wrap:wrap;">
                    <span style="font-size:0.74rem;color:#009aa6;">Technical: <b>{esc(a.get('technical_weight') or 'N/A')}</b></span>
                    <span style="font-size:0.74rem;color:#abc022;">Financial: <b>{esc(a.get('financial_weight') or 'N/A')}</b></span>
                    <span style="font-size:0.74rem;color:#5d858b;">Method: {esc(a.get('evaluation_method') or 'N/A')}</span>
                  </div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">
                    {li_html(a.get("evaluation_criteria") or [])}
                  </ul>
                </div>""", unsafe_allow_html=True)

            with sc2:
                st.markdown(f"""
                <div class="card card--green-top">
                  <div class="card-label">✅ Eligibility Criteria</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">
                    {li_html(a.get('eligibility') or [])}
                  </ul>
                </div>""", unsafe_allow_html=True)

                kq = a.get("key_questions") or []
                if kq:
                    st.markdown(f"""
                    <div class="card card--teal-left">
                      <div class="card-label">❓ Key Clarification Questions</div>
                      <ul class="card-body" style="padding-left:1.1rem;margin:0">
                        {li_html(kq, "#009aa6")}
                      </ul>
                    </div>""", unsafe_allow_html=True)

        # ════════════════════ TAB 3 — DATES & DEADLINES ════════════════════
        with tabs[2]:
            dc1, dc2 = st.columns(2)

            with dc1:
                spotlight = [
                    ("📬 Submission Deadline",       "submission_deadline"),
                    ("❓ Query Submission Deadline",  "query_submission_deadline"),
                    ("🗓️ Pre-Bid Meeting",            "pre_bid_meeting"),
                    ("📂 Bid Opening Date",           "bid_opening_date"),
                    ("🏆 Award Expected",             "award_expected"),
                ]
                for lbl, key in spotlight:
                    val  = a.get(key)
                    days = days_until(val)
                    cls, pill = deadline_display(days)
                    pill_html = f"<span class='tl-pill {cls}'>{pill}</span>" if pill else ""
                    st.markdown(f"""
                    <div class="card" style="padding:0.9rem 1.2rem;margin-bottom:0.55rem;">
                      <div style="font-size:0.6rem;letter-spacing:2.5px;text-transform:uppercase;color:#5d858b;margin-bottom:4px;">{lbl}</div>
                      <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span class="tl-date {cls}">{null_disp(val)}</span>
                        {pill_html}
                      </div>
                    </div>""", unsafe_allow_html=True)

                tv = a.get("tender_validity_days")
                tv_display = f"{tv} days" if tv and str(tv).isdigit() else null_disp(tv)
                st.markdown(f"""
                <div class="card" style="padding:0.9rem 1.2rem;margin-bottom:0.55rem;">
                  <div style="font-size:0.6rem;letter-spacing:2.5px;text-transform:uppercase;color:#5d858b;margin-bottom:4px;">⏳ Tender Validity</div>
                  <span class="tl-date">{tv_display}</span>
                </div>""", unsafe_allow_html=True)

            with dc2:
                all_dates = [d for d in (a.get("important_dates") or [])
                             if not is_null(d.get("date"))]
                if all_dates:
                    st.markdown("""
                    <div class="card card--teal-top" style="padding-bottom:0.4rem;margin-bottom:0;">
                      <div class="card-label">📅 Full Tender Timeline</div>
                    </div>""", unsafe_allow_html=True)
                    for d in all_dates:
                        lbl2 = d.get("label", "")
                        dt   = d.get("date", "")
                        d2   = days_until(dt)
                        cls2, pill2 = deadline_display(d2)
                        pill_h = f"<span class='tl-pill {cls2}'>{pill2}</span>" if pill2 else ""
                        dt_color = '#e05c5c' if cls2 == 'crit' else ('#e09a3a' if cls2 == 'warn' else '#abc022')
                        st.markdown(f"""
                        <div style="display:flex;justify-content:space-between;align-items:center;
                                    padding:0.55rem 1.2rem;border-bottom:1px solid #102030;
                                    background:#0d2d3a;">
                          <span style="font-size:0.83rem;color:#7a9ea3;">{esc(lbl2)}</span>
                          <span style="display:flex;align-items:center;gap:6px;">
                            <span style="font-size:0.87rem;font-weight:500;color:{dt_color};">{esc(dt)}</span>
                            {pill_h}
                          </span>
                        </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card" style="margin-top:0.9rem;">
                  <div class="card-label">📦 Submission Requirements</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">
                    {li_html(a.get("submission_requirements") or [])}
                  </ul>
                </div>""", unsafe_allow_html=True)

        # ════════════════════ TAB 4 — SUBMISSION CHECKLIST ════════════════════
        with tabs[3]:
            checklist = a.get("submission_checklist") or []
            if not checklist:
                st.markdown("""
                <div class="card card--orange-left" style="padding:1.2rem 1.4rem;">
                  <div class="card-label">No Items Found</div>
                  <div class="card-body">
                  No checklist items were extracted from this document.<br><br>
                  Try asking in the <b style="color:#ABC022;">Ask Tendly</b> tab:
                  <span style="color:#0099A5;font-style:italic;">"List all documents required for submission."</span>
                  </div>
                </div>""", unsafe_allow_html=True)
            else:
                done_n  = sum(1 for v in st.session_state.checklist_state.values() if v)
                total_n = len(checklist)
                pct     = int((done_n / total_n) * 100) if total_n else 0
                bar_c   = "#ABC022" if pct == 100 else ("#E09A3A" if pct >= 50 else "#0099A5")
                icon    = "🎉" if pct == 100 else ("✅" if pct >= 50 else "📋")

                st.markdown(f"""
                <div style="margin-bottom:1.4rem;background:var(--surface-1,#0C2A38);
                            border:1px solid var(--border,#163545);border-radius:2px;
                            padding:1rem 1.2rem;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <span style="font-family:'Urbanist','Segoe UI',sans-serif;font-size:0.62rem;
                                 font-weight:800;letter-spacing:3px;text-transform:uppercase;
                                 color:var(--text-dim,#2E5A68);">{icon} Submission Readiness</span>
                    <span style="font-family:'Urbanist',sans-serif;font-size:1rem;font-weight:700;
                                 color:{bar_c};">{done_n}/{total_n}
                      <span style="font-size:0.7rem;font-weight:400;color:var(--text-muted,#6B8F96);">
                        &nbsp;({pct}% complete)
                      </span>
                    </span>
                  </div>
                  <div style="background:var(--border,#163545);border-radius:1px;height:8px;overflow:hidden;">
                    <div style="background:linear-gradient(90deg,{bar_c},{bar_c}cc);width:{pct}%;
                                height:8px;border-radius:1px;transition:width 0.4s ease;"></div>
                  </div>
                </div>""", unsafe_allow_html=True)

                _doc8 = st.session_state.doc_id[:8]
                ba, bb, _bsp = st.columns([1, 1, 4])
                with ba:
                    if st.button("Mark all", key="chkall_btn", use_container_width=True):
                        for j in range(total_n):
                            st.session_state.checklist_state[j] = True
                            st.session_state[f"chk_{_doc8}_{j}"] = True
                        st.rerun()
                with bb:
                    if st.button("Reset", key="chkrst_btn", use_container_width=True):
                        for j in range(total_n):
                            st.session_state.checklist_state[j] = False
                            st.session_state[f"chk_{_doc8}_{j}"] = False
                        st.rerun()

                # Index-based keys: stable across reruns, safe with duplicate
                # item text, and scoped to the current document.
                for idx, item in enumerate(checklist):
                    checked = st.checkbox(
                        item,
                        value=st.session_state.checklist_state.get(idx, False),
                        key=f"chk_{_doc8}_{idx}",
                    )
                    st.session_state.checklist_state[idx] = checked

                st.markdown('<div class="divider-thin"></div>', unsafe_allow_html=True)
                st.caption(
                    "⚠️ This checklist is AI-extracted from the tender document. "
                    "Always verify against the original RFP. Your internal bid process may require additional documents."
                )

        # ════════════════════ TAB 5 — COMMERCIAL ════════════════════
        with tabs[4]:
            cc1, cc2 = st.columns(2)

            with cc1:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">💰 Financial Terms</div>
                  {kv_html([
                      ("Bid Security / EMD", a.get("bid_security")),
                      ("Performance Bond",   a.get("performance_bond")),
                      ("Retention",          a.get("retention")),
                      ("Advance Payment",    a.get("advance_payment")),
                      ("Liquidated Damages", a.get("liquidated_damages")),
                      ("Payment Terms",      a.get("payment_terms")),
                  ])}
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div class="card-label">🛡️ Insurance Requirements</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">{li_html(a.get("insurance_requirements") or [])}</ul>
                </div>""", unsafe_allow_html=True)

            with cc2:
                tw_i = pct_int(a.get("technical_weight"))
                fw_i = pct_int(a.get("financial_weight"))
                if tw_i or fw_i:
                    tw_i = tw_i or (100 - (fw_i or 0))
                    fw_i = fw_i or (100 - tw_i)
                    st.markdown(f"""
                    <div class="card card--green-top">
                      <div class="card-label">📊 Scoring Weights</div>
                      <div class="prog-wrap">
                        <div class="prog-header"><span>Technical</span><span style="color:#009aa6">{tw_i}%</span></div>
                        <div class="prog-track"><div class="prog-fill" style="background:#009aa6;width:{min(tw_i, 100)}%"></div></div>
                      </div>
                      <div class="prog-wrap">
                        <div class="prog-header"><span>Financial</span><span style="color:#abc022">{fw_i}%</span></div>
                        <div class="prog-track"><div class="prog-fill" style="background:#abc022;width:{min(fw_i, 100)}%"></div></div>
                      </div>
                      <div style="font-size:0.73rem;color:#5d858b;margin-top:0.2rem;">
                        Method: <span style="color:#97b8bb">{esc(a.get('evaluation_method') or 'Not specified')}</span>
                      </div>
                    </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div class="card-label">🤝 JV, Consortium & Subcontracting</div>
                  {kv_html([
                      ("JV / Consortium", a.get("jv_consortium_rules")),
                      ("Subcontracting",  a.get("subcontracting_rules")),
                  ])}
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div class="card-label">⚙️ Legal & Governance</div>
                  {kv_html([
                      ("Governing Law",      a.get("governing_law")),
                      ("Dispute Resolution", a.get("dispute_resolution")),
                      ("Language",           a.get("language_requirement")),
                  ])}
                </div>""", unsafe_allow_html=True)

        # ════════════════════ TAB 6 — RISKS & FLAGS ════════════════════
        with tabs[5]:
            risks = sorted(
                a.get("risks") or [],
                key=lambda x: {"High": 0, "Medium": 1, "Low": 2}.get(x.get("level", "Low"), 1),
            )
            if risks:
                st.markdown('<div class="sec-head">⚠️ Risk Register</div>', unsafe_allow_html=True)
                for r in risks:
                    lvl  = r.get("level", "Medium")
                    cat  = r.get("category", "General")
                    desc = r.get("description", "")
                    badge_cls = {"High": "badge-high", "Medium": "badge-med", "Low": "badge-low"}.get(lvl, "badge-med")
                    st.markdown(f"""
                    <div class="card" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;padding:0.82rem 1.2rem;">
                      <div style="flex:1">
                        <span style="font-size:0.6rem;letter-spacing:1px;color:#5d858b;text-transform:uppercase;">{esc(cat)}</span>
                        <div class="card-body" style="margin-top:4px;">{esc(desc)}</div>
                      </div>
                      <span class="badge {badge_cls}" style="margin-top:2px;">{esc(lvl)}</span>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown('<div class="card"><div class="card-body">No risks identified in this document.</div></div>',
                            unsafe_allow_html=True)

            red_flags = a.get("red_flags") or []
            if red_flags:
                st.markdown('<div class="sec-head" style="color:#e05c5c;">🚩 Red Flags — Escalate Before Bidding</div>',
                            unsafe_allow_html=True)
                for f in red_flags:
                    st.markdown(f"""
                    <div class="card card--red-left" style="padding:0.82rem 1.2rem;">
                      <div class="card-body">⚠ {esc(f)}</div>
                    </div>""", unsafe_allow_html=True)

        # ════════════════════ TAB 7 — ASSESSMENT ════════════════════
        with tabs[6]:
            ac1, ac2 = st.columns([3, 2])

            with ac1:
                sc_col = score_color(score)
                st.markdown(f"""
                <div class="card">
                  <div class="card-label">Go / No-Go Score</div>
                  <div class="score-track" style="margin:0.65rem 0 0.3rem;">
                    <div class="score-fill" style="background:{sc_col};width:{score}%;"></div>
                  </div>
                  <div class="score-zones">
                    <span>0 — NO-GO</span>
                    <span style="padding-left:30%">40 — CONDITIONAL</span>
                    <span>70 — GO</span>
                  </div>
                  <div style="margin-top:1rem;display:flex;align-items:baseline;gap:0.5rem;">
                    <span style="font-size:2.4rem;font-weight:800;color:{sc_col};">{score}</span>
                    <span style="font-size:1rem;color:#5d858b;">/ 100</span>
                    <span class="badge {'badge-low' if score >= 70 else ('badge-med' if score >= 40 else 'badge-high')}"
                          style="font-size:0.82rem;padding:3px 12px;margin-left:0.3rem;">
                      {v_label}
                    </span>
                  </div>
                  <div class="card-body" style="margin-top:0.9rem;">{esc(a.get('go_no_go_rationale') or '')}</div>
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card card--green-left">
                  <div class="card-label">📋 Recommendation</div>
                  <div class="card-body">{esc(a.get('recommendation') or '')}</div>
                </div>""", unsafe_allow_html=True)

                st.caption(
                    "This score is an AI-generated screening aid based on the document "
                    "text only — it is not a bid decision. Validate with your bid committee."
                )

            with ac2:
                st.markdown(f"""
                <div class="card card--green-left">
                  <div class="card-label">🏆 Win Themes</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">{li_html(a.get("win_themes") or [], "#abc022")}</ul>
                </div>""", unsafe_allow_html=True)

                wi = a.get("watch_items") or []
                if wi:
                    st.markdown(f"""
                    <div class="card card--orange-left">
                      <div class="card-label">👁 Watch Items</div>
                      <ul class="card-body" style="padding-left:1.1rem;margin:0">{li_html(wi, "#e09a3a")}</ul>
                    </div>""", unsafe_allow_html=True)

        # ════════════════════ TAB 8 — ASK TENDLY ════════════════════
        with tabs[7]:
            st.markdown("""
            <div style="font-size:0.81rem;color:#5d858b;margin-bottom:1rem;line-height:1.72;">
            Ask anything about this tender. Answers are grounded in the most relevant pages of the
            document — sources are shown after each response.
            </div>
            """, unsafe_allow_html=True)

            QUICK_QS = [
                "List all documents required for submission",
                "What are the top 3 risks to flag to leadership?",
                "What experience and credentials must we demonstrate?",
                "Is JV or consortium allowed? What are the rules?",
                "What is the payment structure and retention policy?",
            ]
            st.markdown('<div class="qq-label">Quick Questions</div>', unsafe_allow_html=True)
            qq_cols = st.columns(len(QUICK_QS))
            for i, (col, q) in enumerate(zip(qq_cols, QUICK_QS)):
                with col:
                    if st.button(q, key=f"qq_{i}", use_container_width=True, disabled=not HAS_KEY):
                        _run_question(q)

            st.markdown('<div class="divider-thin"></div>', unsafe_allow_html=True)

            # Conversation history
            if not st.session_state.chat_history:
                st.markdown("""
                <div class="chat-empty">
                  <div class="chat-empty-icon">💬</div>
                  <div class="chat-empty-title">No questions yet</div>
                  <div class="chat-empty-sub">
                    Pick a quick question above, or type your own below.<br>
                    Every answer is grounded in the document — sources cited per response.
                  </div>
                </div>
                """, unsafe_allow_html=True)
            for turn in st.session_state.chat_history:
                st.markdown(f'<div class="bubble-user">{esc(turn["q"])}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="bubble-ai">{esc(turn["a"])}</div>', unsafe_allow_html=True)
                src = turn.get("sources")
                if src:
                    src_str = ", ".join(f"p.{p}" for p in src)
                    st.markdown(
                        f'<div class="bubble-ts">Sources: {src_str} &nbsp;·&nbsp; {turn.get("ts", "")}</div>',
                        unsafe_allow_html=True,
                    )

            # Input — a form so Enter submits and the box clears after sending.
            with st.form("ask_form", clear_on_submit=True):
                fc1, fc2 = st.columns([4, 1])
                with fc1:
                    user_q = st.text_input(
                        "Your question",
                        placeholder="e.g.  What are the LD caps?  /  Does this require FIDIC?  /  What is the bid bond amount?",
                        label_visibility="collapsed",
                    )
                with fc2:
                    submitted = st.form_submit_button(
                        "Ask Tendly  →", use_container_width=True, disabled=not HAS_KEY
                    )
            if submitted:
                if user_q.strip():
                    _run_question(user_q.strip())
                else:
                    st.toast("Type a question first.", icon="✍️")

            if st.session_state.chat_history:
                if st.button("Clear conversation"):
                    st.session_state.chat_history = []
                    st.rerun()

        # ── EXPORT BAR ──────────────────────────────────────────────────────
        st.markdown('<div class="divider-main"></div>', unsafe_allow_html=True)
        fname_base = re.sub(r'[^\w\-]+', '_', st.session_state.filename.rsplit(".pdf", 1)[0]).strip("_") or "tender"
        report_md  = build_markdown_report(a, st.session_state.filename)

        ec1, ec2, ec3, _sp2 = st.columns([1, 1, 1, 2])
        with ec1:
            st.download_button(
                "⬇  Report (.md)",
                data=report_md,
                file_name=f"tendly_{fname_base}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with ec2:
            st.download_button(
                "⬇  Raw JSON",
                data=json.dumps(a, indent=2, ensure_ascii=False),
                file_name=f"tendly_{fname_base}.json",
                mime="application/json",
                use_container_width=True,
            )
        with ec3:
            cl_items  = a.get("submission_checklist") or []
            cl_export = "\n".join(
                f"{'[x]' if st.session_state.checklist_state.get(i, False) else '[ ]'} {item}"
                for i, item in enumerate(cl_items)
            )
            st.download_button(
                "⬇  Checklist (.txt)",
                data=cl_export or "No checklist items extracted.",
                file_name=f"tendly_checklist_{fname_base}.txt",
                mime="text/plain",
                use_container_width=True,
            )

    # ── Raw text expander ───────────────────────────────────────────────────
    with st.expander("📄  View Extracted PDF Text"):
        st.markdown(f"""
        <div style="font-size:0.68rem;color:#5d858b;margin-bottom:0.5rem;">
        {stats.get('pages', '?')} pages &nbsp;·&nbsp; {stats.get('words', 0):,} words &nbsp;·&nbsp;
        {stats.get('text_pages', '?')} readable &nbsp;·&nbsp; {stats.get('image_pages', '?')} image-only &nbsp;·&nbsp;
        text quality {stats.get('quality_pct', '?')}%
        </div>
        """, unsafe_allow_html=True)
        shown = full_text[:CFG.RAW_TEXT_VIEW_CAP]
        if len(full_text) > CFG.RAW_TEXT_VIEW_CAP:
            shown += "\n\n[… truncated for display — download the report for full data …]"
        st.text_area("Extracted Content", shown, height=380, label_visibility="collapsed")




