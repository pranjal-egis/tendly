# ╔══════════════════════════════════════════════════════════════════════════╗
# ║            TENDLY  v5  ·  Egis AI Tender Intelligence Platform          ║
# ║            Internal Operations Tool  ·  Production Build                ║
# ╠══════════════════════════════════════════════════════════════════════════╣
# ║  Model      : moonshotai/kimi-k2.6:free  (OpenRouter)                  ║
# ║  PDF Engine : pdfplumber — semantic page chunking + table extraction    ║
# ║  Analysis   : Section-priority smart context window                     ║
# ║  Chat       : Retrieval-augmented Q&A (most-relevant pages surfaced)    ║
# ╚══════════════════════════════════════════════════════════════════════════╝
from __future__ import annotations

import hashlib
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

load_dotenv()  # ← loads your .env file before anything else runs

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
# PAGE CONFIG  (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Tendly· AI Tender Intelligence",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
class Config:
    OPENROUTER_API_KEY: str  = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str    = "google/gemma-4-31b-it:free"
    API_BASE_URL: str        = "https://openrouter.ai/api/v1/chat/completions"
    API_TIMEOUT: int         = 150          # kimi-k2 can be slow on long prompts
    API_MAX_RETRIES: int     = 3
    API_RETRY_DELAY: float   = 3.0

    # PDF extraction tuning
    PDF_MIN_PAGE_TEXT: int        = 40      # chars below which page is image-only
    PDF_ANALYSIS_CHAR_BUDGET: int = 55_000  # total chars fed to AI for analysis
    PDF_HEAD_CHARS: int           = 22_000  # first N chars always included (cover + instructions)
    PDF_TAIL_CHARS: int           = 10_000  # last N chars always included (checklists, T&Cs)
    PDF_MID_CHARS: int            = 18_000  # middle chars for scope, eligibility, eval

    # Chat / Q&A
    CHAT_CONTEXT_CHARS: int = 35_000   # total doc chars available for Q&A
    CHAT_SNIPPET_CHARS: int = 4_000    # chars per retrieved snippet
    CHAT_MAX_SNIPPETS: int  = 5        # max snippets retrieved per question
    CHAT_HISTORY_TURNS: int = 8        # conversation turns to include

    # App
    HISTORY_MAX: int    = 5
    APP_VERSION: str    = "5.1"


CFG = Config()

# ─────────────────────────────────────────────────────────────────────────────
# STYLES  —  Egis Brand: Midnight Blue #09212c · Teal #009aa6 · Green #abc022
# ─────────────────────────────────────────────────────────────────────────────
STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Urbanist:wght@300;400;500;600;700;800;900&display=swap');

/* ══════════════════════════════════════════════════════════════
   EGIS TENDLY — Brand-compliant Design System v2
   Palette: Midnight Blue #08212C · Green Egis #ABC022
            Azure Blue #0099A5  · Duck Blue #00617E
   Typography: Urbanist (display) · Segoe UI (body/data)
══════════════════════════════════════════════════════════════ */

/* ── CSS Custom Properties ─────────────────────── */
:root {
  --midnight:   #08212C;
  --midnight-2: #0C2A38;
  --midnight-3: #0F3040;
  --midnight-4: #122E3C;
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
  --surface-1:  #0C2A38;
  --surface-2:  #0F3040;
  --surface-3:  #122E3C;
}

/* ── Streamlit Cloud table border reset ──────── */
.stMarkdown table,
.stMarkdown table td,
.stMarkdown table th,
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
.stApp { background: var(--midnight); color: var(--text-main); }

/* ── Urbanist display font utility ───────────────*/
.ub { font-family: 'Urbanist', 'Segoe UI', sans-serif !important; }

/* ══════════════════════════════════════════════
   TOP BAR — Brand Header
══════════════════════════════════════════════ */
.egis-topbar {
  background: var(--midnight);
  border-bottom: 1px solid var(--border);
  padding: 1rem 0 0.85rem;
  margin-bottom: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  position: relative;
}
/* Signature green underline accent */
.egis-topbar::after {
  content: '';
  position: absolute;
  bottom: -1px; left: 0;
  width: 340px; height: 3px;
  background: linear-gradient(90deg, var(--green) 0%, var(--teal) 60%, transparent 100%);
}

/* Wordmark */
.egis-wordmark {
  font-family: 'Urbanist', 'Segoe UI', sans-serif;
  font-size: 1.95rem;
  font-weight: 800;
  color: #fff;
  letter-spacing: -0.5px;
  line-height: 1;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 0;
}
.egis-e { color: var(--green); }
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
}
.egis-product {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 3.5px;
  text-transform: uppercase;
  color: var(--teal);
  margin-top: 5px;
}
.egis-meta {
  font-size: 0.56rem;
  letter-spacing: 1.5px;
  color: var(--text-dim);
  text-transform: uppercase;
  margin-top: 3px;
}
/* Right-side motto block */
.egis-motto-block {
  text-align: right;
}
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
/* Live indicator dot */
.egis-live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--green);
  margin-top: 6px;
}
.egis-live::before {
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 0 3px var(--green-glow);
  animation: pulse-dot 2s ease-in-out infinite;
}
@keyframes pulse-dot {
  0%,100% { box-shadow: 0 0 0 2px var(--green-glow); }
  50%      { box-shadow: 0 0 0 5px rgba(171,192,34,0.05); }
}

/* ══════════════════════════════════════════════
   DIVIDERS
══════════════════════════════════════════════ */
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

/* ══════════════════════════════════════════════
   CARDS
══════════════════════════════════════════════ */
.card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 1.2rem 1.4rem;
  margin-bottom: 0.85rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.card:hover {
  border-color: var(--border-2);
  box-shadow: 0 4px 24px rgba(0,0,0,0.2);
}
/* Accent variants */
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

/* ── Hero cards ───────────────────────────────── */
.hero-card {
  background: linear-gradient(135deg, var(--midnight-3) 0%, var(--midnight) 100%);
  border: 1px solid var(--border-2);
  border-top: 2px solid var(--green);
  border-radius: 2px;
  padding: 1.1rem 1.4rem;
  margin-bottom: 0.85rem;
  position: relative;
  overflow: hidden;
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

/* ══════════════════════════════════════════════
   STAT BOXES
══════════════════════════════════════════════ */
.stat-row { display: flex; gap: 8px; margin-bottom: 1.3rem; flex-wrap: wrap; }
.stat-box {
  flex: 1;
  min-width: 90px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-top: 2px solid var(--teal);
  border-radius: 2px;
  padding: 0.9rem 0.75rem 0.8rem;
  text-align: center;
  position: relative;
  overflow: hidden;
  transition: transform 0.15s ease;
}
.stat-box::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--teal-glow), transparent);
}
.stat-box:hover { transform: translateY(-1px); }
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

/* ══════════════════════════════════════════════
   BADGES
══════════════════════════════════════════════ */
.badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 1px;
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

/* ══════════════════════════════════════════════
   VERDICT BANNER
══════════════════════════════════════════════ */
.verdict {
  border-radius: 2px;
  padding: 1.4rem 2rem;
  text-align: center;
  margin-bottom: 1.3rem;
  position: relative;
  overflow: hidden;
}
.verdict::before {
  content: '';
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 18px,
    rgba(255,255,255,0.008) 18px,
    rgba(255,255,255,0.008) 19px
  );
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
  font-family: 'Urbanist', sans-serif;
  font-size: 2.1rem;
  font-weight: 900;
  letter-spacing: 4px;
  margin: 0.25rem 0 0.1rem;
  text-transform: uppercase;
}
.verdict-score    { font-size: 1rem; font-weight: 300; color: var(--text-muted); }
.verdict-rationale{ font-size: 0.84rem; color: var(--text-main); line-height: 1.7; margin-top: 0.6rem; }

/* ══════════════════════════════════════════════
   SECTION HEADINGS
══════════════════════════════════════════════ */
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

/* ══════════════════════════════════════════════
   KV TABLE
══════════════════════════════════════════════ */
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

/* ══════════════════════════════════════════════
   TIMELINE / DATES
══════════════════════════════════════════════ */
.tl-pill {
  font-family: 'Urbanist', sans-serif;
  font-size: 0.57rem;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 1px;
  margin-left: 8px;
  white-space: nowrap;
}
.tl-pill.crit { background: rgba(224,82,82,0.12);  color: var(--red);    border: 1px solid rgba(224,82,82,0.3); }
.tl-pill.warn { background: rgba(224,154,58,0.12); color: var(--orange); border: 1px solid rgba(224,154,58,0.3); }
.tl-pill.ok   { background: var(--green-glow);     color: var(--green);  border: 1px solid rgba(171,192,34,0.3); }

/* ══════════════════════════════════════════════
   PROGRESS BARS
══════════════════════════════════════════════ */
.prog-wrap   { margin-bottom: 1rem; }
.prog-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.79rem;
  color: var(--text-main);
  margin-bottom: 6px;
}
.prog-track  { background: rgba(22,53,69,0.9); border-radius: 1px; height: 6px; }
.prog-fill   { height: 6px; border-radius: 1px; transition: width 0.5s ease; }

/* ── Score bar ────────────────────────────────── */
.score-track {
  background: rgba(22,53,69,0.9);
  border-radius: 2px;
  height: 12px;
  position: relative;
  overflow: hidden;
}
.score-fill  { height: 12px; border-radius: 2px; }
.score-zones {
  display: flex;
  justify-content: space-between;
  font-size: 0.56rem;
  color: var(--text-dim);
  margin-top: 4px;
  letter-spacing: 0.5px;
}

/* ══════════════════════════════════════════════
   CHAT BUBBLES
══════════════════════════════════════════════ */
.bubble-user {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-right: 3px solid var(--teal);
  border-radius: 2px;
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  font-size: 0.875rem;
  color: var(--text-bright);
  text-align: right;
}
.bubble-ai {
  background: rgba(8,33,44,0.7);
  border: 1px solid var(--border);
  border-left: 3px solid var(--green);
  border-radius: 2px;
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

/* ══════════════════════════════════════════════
   INFO PANEL (right-side upload tip)
══════════════════════════════════════════════ */
.info-panel {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-left: 3px solid var(--teal);
  border-radius: 2px;
  padding: 0.9rem 1.1rem;
  font-size: 0.8rem;
  color: var(--text-main);
  line-height: 1.9;
}
.info-panel strong {
  font-family: 'Urbanist', sans-serif;
  color: var(--green);
  display: block;
  font-size: 0.59rem;
  letter-spacing: 2.5px;
  text-transform: uppercase;
  margin-bottom: 6px;
}

/* ══════════════════════════════════════════════
   QUALITY BAR (PDF stats)
══════════════════════════════════════════════ */
.quality-bar { display: flex; gap: 3px; margin-top: 7px; }
.quality-seg { flex: 1; height: 3px; border-radius: 1px; background: var(--border); }
.quality-seg.g { background: var(--green); }
.quality-seg.w { background: var(--orange); }
.quality-seg.b { background: var(--red); }

/* ══════════════════════════════════════════════
   SIDEBAR
══════════════════════════════════════════════ */
section[data-testid="stSidebar"] {
  background: rgba(6,20,28,0.98) !important;
  min-width: 260px !important;
}
section[data-testid="stSidebar"]::before {
  content: '';
  position: absolute;
  top: 0; right: 0;
  width: 1px; height: 100%;
  background: linear-gradient(180deg, var(--green) 0%, var(--teal) 40%, transparent 100%);
}

/* ── Sidebar collapse / expand toggle button ── */
/* Collapsed state: slim teal-accented tab, no raw arrow box */
[data-testid="collapsedControl"] {
  background: transparent !important;
  border: none !important;
  border-left: 2px solid var(--teal) !important;
  border-radius: 0 !important;
  width: 28px !important;
  height: 80px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  opacity: 1 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  transition: border-color 0.2s ease, background 0.2s ease !important;
  cursor: pointer !important;
}
[data-testid="collapsedControl"]:hover {
  background: rgba(0,153,165,0.06) !important;
  border-left-color: var(--green) !important;
}
[data-testid="collapsedControl"] svg {
  display: none !important;
}
/* Inject a rotated "‹" via pseudo — CSS can't do ::before on non-pseudo-capable elements,
   so we target the button's span wrapper if present */
[data-testid="collapsedControl"]::after {
  content: '›';
  font-family: 'Urbanist', sans-serif;
  font-size: 1rem;
  font-weight: 300;
  color: var(--teal);
  letter-spacing: 0;
  line-height: 1;
}
[data-testid="collapsedControl"]:hover::after {
  color: var(--green);
}

/* When sidebar IS open, the close (chevron) button inside it */
section[data-testid="stSidebar"] button[data-testid="baseButton-headerNoPadding"] {
  color: var(--text-dim) !important;
  opacity: 0.45 !important;
  transition: opacity 0.15s ease !important;
}
section[data-testid="stSidebar"] button[data-testid="baseButton-headerNoPadding"]:hover {
  color: var(--teal) !important;
  opacity: 1 !important;
}

.sb-card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-left: 2px solid transparent;
  border-radius: 2px;
  padding: 0.8rem 0.9rem;
  margin-bottom: 0.6rem;
  transition: border-color 0.15s ease;
}
.sb-card:hover { border-left-color: var(--green); }
.sb-title { font-size: 0.78rem; color: var(--text-bright); font-weight: 600; line-height: 1.35; }
.sb-meta  { font-size: 0.6rem; color: var(--text-dim); letter-spacing: 0.5px; margin-top: 3px; }

/* ══════════════════════════════════════════════
   LANDING PAGE — Feature tiles
══════════════════════════════════════════════ */
.feature-tile {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 1.1rem 1.2rem;
  min-width: 140px;
  flex: 1;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}
.feature-tile:hover {
  border-color: var(--border-2);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.3);
}
.feature-tile::after {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
}

/* ══════════════════════════════════════════════
   STREAMLIT COMPONENT OVERRIDES
══════════════════════════════════════════════ */
/* File uploader */
.stFileUploader > div {
  border: 1px dashed var(--border-2) !important;
  border-radius: 2px !important;
  background: rgba(12,42,56,0.5) !important;
  transition: border-color 0.2s !important;
}
.stFileUploader > div:hover {
  border-color: var(--teal) !important;
}

/* Primary buttons */
.stButton > button {
  background: var(--teal) !important;
  color: #fff !important;
  border: none !important;
  font-family: 'Urbanist', 'Segoe UI', sans-serif !important;
  font-weight: 800 !important;
  letter-spacing: 2px !important;
  text-transform: uppercase !important;
  font-size: 0.72rem !important;
  border-radius: 1px !important;
  padding: 0.55rem 1.2rem !important;
  transition: all 0.15s ease !important;
  position: relative !important;
  overflow: hidden !important;
}
.stButton > button::after {
  content: '' !important;
  position: absolute !important;
  inset: 0 !important;
  background: linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 100%) !important;
  pointer-events: none !important;
}
.stButton > button:hover {
  background: var(--teal-dim) !important;
  box-shadow: 0 4px 16px rgba(0,153,165,0.25) !important;
  transform: translateY(-1px) !important;
}
.stButton > button:active {
  transform: translateY(0) !important;
}

/* Analyse button gets the green treatment */
.stButton > button[kind="primary"],
.stButton > button:first-child {
  background: linear-gradient(135deg, var(--teal) 0%, var(--duck) 100%) !important;
}

/* Download buttons */
.stDownloadButton > button {
  background: transparent !important;
  color: var(--green) !important;
  border: 1px solid rgba(171,192,34,0.4) !important;
  font-family: 'Urbanist', 'Segoe UI', sans-serif !important;
  font-weight: 700 !important;
  letter-spacing: 1.5px !important;
  text-transform: uppercase !important;
  font-size: 0.7rem !important;
  border-radius: 1px !important;
  transition: all 0.15s ease !important;
}
.stDownloadButton > button:hover {
  background: var(--green-glow) !important;
  border-color: var(--green) !important;
  box-shadow: 0 4px 12px rgba(171,192,34,0.15) !important;
}

/* Text inputs */
.stTextArea textarea, .stTextInput input {
  background: var(--surface-1) !important;
  border: 1px solid var(--border) !important;
  color: var(--text-bright) !important;
  border-radius: 2px !important;
  font-size: 0.875rem !important;
  transition: border-color 0.2s !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: var(--teal) !important;
  box-shadow: 0 0 0 2px rgba(0,153,165,0.12) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
  background: transparent;
  border-bottom: 1px solid var(--border);
  gap: 0;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  color: var(--text-dim) !important;
  font-family: 'Urbanist', 'Segoe UI', sans-serif !important;
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  letter-spacing: 1.5px !important;
  text-transform: uppercase !important;
  padding: 0.65rem 1.1rem !important;
  border-bottom: 2px solid transparent !important;
  transition: all 0.15s ease !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text-main) !important;
}
.stTabs [aria-selected="true"] {
  color: var(--text-bright) !important;
  border-bottom-color: var(--green) !important;
}

/* Spinner */
.stSpinner > div { border-top-color: var(--green) !important; }

/* Expander */
.streamlit-expanderHeader {
  background: var(--surface-1) !important;
  color: var(--text-muted) !important;
  font-size: 0.82rem !important;
  border: 1px solid var(--border) !important;
  border-radius: 2px !important;
}
.streamlit-expanderContent {
  background: rgba(8,33,44,0.5) !important;
  border: 1px solid var(--border) !important;
  border-top: none !important;
}

/* Checkboxes — Submission Checklist */
div[data-testid="stCheckbox"] {
  margin-bottom: 0;
  padding: 0.38rem 0.6rem;
  border-radius: 2px;
  border: 1px solid transparent;
  transition: all 0.12s ease;
}
div[data-testid="stCheckbox"]:hover {
  background: var(--surface-1);
  border-color: var(--border);
}
div[data-testid="stCheckbox"] label {
  font-size: 0.875rem !important;
  color: var(--text-bright) !important;
  cursor: pointer;
}
div[data-testid="stCheckbox"] label p {
  color: var(--text-bright) !important;
}
div[data-testid="stCheckbox"] input[type="checkbox"]:checked ~ div label {
  color: var(--green) !important;
}
div[data-testid="stCheckbox"] input[type="checkbox"]:checked ~ div label p {
  color: var(--green) !important;
  text-decoration: line-through;
  text-decoration-color: rgba(171,192,34,0.4);
}

/* Warnings & info */
.stAlert {
  background: rgba(224,154,58,0.08) !important;
  border: 1px solid rgba(224,154,58,0.25) !important;
  border-radius: 2px !important;
}

/* ══════════════════════════════════════════════
   QUICK QUESTION BUTTONS — Uniform height, wrap text
══════════════════════════════════════════════ */
/* Target the quick-question button columns */
div[data-testid="column"] .stButton > button {
  white-space: normal !important;
  word-break: break-word !important;
  hyphens: auto !important;
  height: auto !important;
  min-height: 72px !important;
  text-align: center !important;
  line-height: 1.5 !important;
  padding: 0.65rem 0.9rem !important;
  font-size: 0.68rem !important;
  letter-spacing: 0.5px !important;
  text-transform: none !important;
  font-weight: 600 !important;
  font-family: 'Urbanist', 'Segoe UI', sans-serif !important;
  background: var(--surface-2) !important;
  border: 1px solid var(--border) !important;
  border-top: 2px solid var(--teal) !important;
  color: var(--text-main) !important;
  transition: all 0.15s ease !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}
div[data-testid="column"] .stButton > button:hover {
  background: var(--midnight-3) !important;
  border-color: var(--border-2) !important;
  border-top-color: var(--green) !important;
  color: var(--text-bright) !important;
  box-shadow: 0 4px 16px rgba(0,0,0,0.2) !important;
  transform: translateY(-1px) !important;
}

/* Scrollbars */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--midnight); }
::-webkit-scrollbar-thumb { background: var(--border-2); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--duck); }

/* Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }

/* ══════════════════════════════════════════════
   UPLOAD ZONE LABEL
══════════════════════════════════════════════ */
.upload-zone-label {
  font-size: 0.62rem;
  color: var(--text-dim);
  letter-spacing: 0.5px;
  margin-bottom: 0.5rem;
  margin-top: -0.3rem;
}

/* ══════════════════════════════════════════════
   SIDEBAR TOGGLE — already handled above in SIDEBAR section
══════════════════════════════════════════════ */

/* ══════════════════════════════════════════════
   COLUMN LAYOUT — equal-height flex columns
   (ensures Quick Question buttons align)
══════════════════════════════════════════════ */
div[data-testid="stHorizontalBlock"] {
  align-items: stretch !important;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
  display: flex !important;
  flex-direction: column !important;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div {
  flex: 1 !important;
  display: flex !important;
  flex-direction: column !important;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] .stButton {
  flex: 1 !important;
  display: flex !important;
  flex-direction: column !important;
}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] .stButton > button {
  flex: 1 !important;
}
</style>
"""

st.markdown(STYLES, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="egis-topbar">
  <div>
    <div class="egis-wordmark">
      <span class="egis-e">E</span><span style="color:#fff;">GIS</span>
      <span class="egis-separator">·</span>
      <span class="egis-tendly">TENDLY</span>
    </div>
    <div class="egis-product">AI Tender Intelligence Platform</div>
    <div class="egis-meta">Internal Operations Tool</div>
  </div>
  <div class="egis-motto-block">
    <div class="egis-motto-line">IMAGINE &nbsp;·&nbsp; CREATE &nbsp;·&nbsp; <span class="highlight">ACHIEVE</span></div>
  </div>
</div>
<div class="divider-main"></div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    "analysis":         None,
    "pages":            [],
    "full_text":        "",
    "structured_text":  "",
    "filename":         "",
    "file_hash":        "",
    "pdf_stats":        {},
    "chat_history":     [],
    "checklist_state":  {},
    "tender_history":   [],
    "analysis_error":   None,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# Patterns used to detect section boundaries inside extracted text.
# Keys are the [SECTION: …] marker injected before the heading line.
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

# Tender-domain keyword groups used for relevance scoring in Q&A retrieval
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "deadline":       ["deadline", "submission", "closing date", "due date", "query deadline", "bid closing"],
    "scope":          ["scope of work", "scope of services", "deliverables", "works", "services"],
    "eligibility":    ["eligibility", "qualification", "minimum requirement", "experience", "turnover", "years"],
    "checklist":      ["checklist", "required documents", "document list", "submission checklist"],
    "commercial":     ["payment", "invoice", "retention", "advance", "milestone", "bid security", "bond", "liquidated damages", "ld clause"],
    "evaluation":     ["evaluation", "scoring", "technical score", "financial score", "criteria", "weight"],
    "risk":           ["risk", "red flag", "concern", "liability", "penalty"],
    "jv":             ["jv", "joint venture", "consortium", "teaming", "lead partner", "subcontract"],
    "insurance":      ["insurance", "indemnity", "public liability", "professional indemnity"],
    "dates":          ["date", "deadline", "timeline", "schedule", "validity", "pre-bid"],
    "legal":          ["governing law", "jurisdiction", "dispute", "arbitration", "court"],
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
    """
    Inject [SECTION: …] markers before lines that match tender section headings.
    This guides the LLM to the right part of the document for each field.
    """
    out_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if 3 < len(stripped) < 120:          # headings are short-ish lines
            for marker, pat in _SECTION_MARKERS.items():
                if re.search(pat, stripped, re.IGNORECASE):
                    out_lines.append(f"\n{marker}")
                    break
        out_lines.append(line)
    return "\n".join(out_lines)


def extract_pdf(file) -> tuple[list[dict], str, str, dict]:
    """
    Full PDF extraction pipeline.

    Returns:
        pages           — list of page dicts for retrieval-augmented chat
        full_text       — clean concatenated text for display
        structured_text — section-annotated text for AI analysis
        stats           — document quality metrics
    """
    pages: list[dict] = []
    image_pages = 0
    char_cursor = 0

    with pdfplumber.open(file) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            raw_text   = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
            table_text = _table_to_text(page)
            combined   = raw_text + table_text

            is_image = len(raw_text.strip()) < CFG.PDF_MIN_PAGE_TEXT
            if is_image:
                image_pages += 1
                page_text = f"\n\n━━ PAGE {i+1} [IMAGE / SCANNED — no text] ━━\n"
            else:
                page_text = f"\n\n━━ PAGE {i+1} ━━\n{_clean(combined)}"

            pages.append({
                "num":        i + 1,
                "text":       page_text,
                "is_image":   is_image,
                "char_start": char_cursor,
                "char_end":   char_cursor + len(page_text),
            })
            char_cursor += len(page_text)

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

    log.info(
        "PDF extracted — %d pages (%d text, %d image), %d words, quality %d%%",
        total_pages, text_pages, image_pages, words, quality_pct,
    )
    return pages, full_text, structured_text, stats


def build_analysis_context(structured_text: str) -> str:
    """
    Build an intelligently-windowed context string for the analysis LLM call.

    Strategy:
      1. Always include the opening section (cover page, project overview, instructions)
      2. Always include the closing section (checklists, T&Cs, annexures, dates tables)
      3. Fill remaining budget with the middle third (scope, eligibility, evaluation)

    This avoids the naïve first-N-chars truncation that drops critical tail content.
    """
    budget = CFG.PDF_ANALYSIS_CHAR_BUDGET
    n      = len(structured_text)

    if n <= budget:
        return structured_text

    head = structured_text[:CFG.PDF_HEAD_CHARS]
    tail = structured_text[max(0, n - CFG.PDF_TAIL_CHARS):]

    mid_budget = budget - len(head) - len(tail)
    if mid_budget > 2_000:
        # Sample from the middle third of the document
        mid_start = max(CFG.PDF_HEAD_CHARS, n // 3)
        mid_end   = min(n - CFG.PDF_TAIL_CHARS, 2 * n // 3)
        mid_slice = structured_text[mid_start: min(mid_start + mid_budget, mid_end)]
        mid_block = f"\n\n[… MID-DOCUMENT EXTRACT (chars {mid_start}–{mid_start+len(mid_slice)}) …]\n\n{mid_slice}"
    else:
        mid_block = ""

    context = head + mid_block + f"\n\n[… END SECTION (last {CFG.PDF_TAIL_CHARS // 1000}k chars) …]\n\n" + tail
    log.info("Analysis context: %d chars (budget %d, doc %d)", len(context), budget, n)
    return context


# ─────────────────────────────────────────────────────────────────────────────
# RETRIEVAL ENGINE  (for Q&A)
# ─────────────────────────────────────────────────────────────────────────────

def _score_page(page_text: str, query: str) -> float:
    """
    Score a page's relevance to a query.
    Uses a simple TF-style keyword scoring weighted by topic group proximity.
    Runs entirely in-process — no embedding model needed.
    """
    q_lower = query.lower()
    p_lower = page_text.lower()
    score   = 0.0

    # 1. Direct word overlap between query tokens and page text
    q_tokens = set(re.findall(r'\b\w{4,}\b', q_lower))
    for tok in q_tokens:
        count = p_lower.count(tok)
        score += min(count, 5) * 1.0

    # 2. Topic-group bonus: if query mentions a topic, boost pages with topic keywords
    for topic, kws in _TOPIC_KEYWORDS.items():
        topic_in_query = any(kw in q_lower for kw in kws)
        if topic_in_query:
            topic_in_page = sum(1 for kw in kws if kw in p_lower)
            score += topic_in_page * 2.0

    # 3. Section marker bonus (page contains a labelled section heading)
    if "[SECTION:" in page_text:
        score += 3.0

    # 4. Table bonus (tables often contain dates, scores, checklists)
    if "[TABLE]" in page_text:
        score += 2.0

    return score


def retrieve_relevant_context(
    pages: list[dict],
    query: str,
    max_snippets: int = CFG.CHAT_MAX_SNIPPETS,
    snippet_chars: int = CFG.CHAT_SNIPPET_CHARS,
) -> tuple[str, list[int]]:
    """
    Find the most relevant pages for a given query and return a focused
    context string + list of page numbers used.

    This dramatically improves Q&A accuracy over always-sending-first-N-chars,
    especially for large documents where key information is deep in the PDF.
    """
    if not pages:
        return "", []

    # Score all non-image pages
    scored = [
        (p["num"], _score_page(p["text"], query), p["text"])
        for p in pages if not p.get("is_image")
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Always include page 1 (cover / intro context) at reduced priority
    top_pages     = scored[:max_snippets]
    page_nums_used = [num for num, _, _ in top_pages]

    # Build context: highest-scoring first, truncated to snippet budget
    snippets = []
    budget   = max_snippets * snippet_chars
    used     = 0
    for num, score, text in top_pages:
        if used >= budget:
            break
        chunk = text[:snippet_chars]
        snippets.append(f"[PAGE {num}]\n{chunk}")
        used += len(chunk)

    context = "\n\n---\n\n".join(snippets)
    log.info(
        "RAG retrieval: query=%r → pages %s (scores: %s)",
        query[:60],
        page_nums_used,
        [round(s, 1) for _, s, _ in top_pages],
    )
    return context, page_nums_used


# ─────────────────────────────────────────────────────────────────────────────
# AI ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _call_api(messages: list[dict], max_tokens: int) -> str:
    """
    OpenRouter API call with exponential-backoff retry.
    Raises RuntimeError on all unrecoverable failures.
    """
    if not CFG.OPENROUTER_API_KEY:
        st.error("⚠️  **OPENROUTER_API_KEY** environment variable is not set. "
                 "Add it to your Streamlit secrets or environment before using Tendly.")
        st.stop()

    headers = {
        "Authorization": f"Bearer {CFG.OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://egis.com/tendly",
        "X-Title":       "Tendly · Egis AI Tender Intelligence",
    }
    payload = {
        "model":       CFG.OPENROUTER_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": 0.05,
    }

    last_err: Exception | None = None
    for attempt in range(CFG.API_MAX_RETRIES):
        try:
            resp = requests.post(
                CFG.API_BASE_URL,
                headers=headers,
                json=payload,
                timeout=CFG.API_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            if "choices" not in data:
                err = data.get("error", {})
                raise RuntimeError(f"API error [{err.get('code','?')}]: {err.get('message', data)}")

            content = data["choices"][0]["message"]["content"]
            usage   = data.get("usage", {})
            log.info(
                "API OK — tokens in=%s out=%s attempt=%d",
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
                attempt + 1,
            )
            return content

        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            wait = CFG.API_RETRY_DELAY * (2 ** attempt)
            log.warning("API attempt %d failed (%s) — retrying in %.1fs", attempt + 1, e, wait)
            time.sleep(wait)
        except requests.HTTPError as e:
            last_err = e
            if resp.status_code in (429, 503):
                wait = CFG.API_RETRY_DELAY * (2 ** attempt)
                log.warning("HTTP %d — retrying in %.1fs", resp.status_code, wait)
                time.sleep(wait)
            else:
                raise RuntimeError(f"HTTP {resp.status_code}: {e}") from e

    raise RuntimeError(
        f"AI service unavailable after {CFG.API_MAX_RETRIES} attempts. Last error: {last_err}"
    )


def _parse_json(raw: str) -> dict:
    """Robustly parse JSON from a model response, stripping any markdown fences."""
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*\n?', '', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\n?```\s*$', '', raw)
    raw = raw.strip()
    # If model prepended text before the JSON object, find the brace boundary
    start = raw.find('{')
    end   = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return json.loads(raw)


# ──────────────────────────────────────────────────────────────────────────────
# Analysis prompt
# ──────────────────────────────────────────────────────────────────────────────
_ANALYSIS_SYSTEM = """You are a Principal Tender Analyst with 25 years of experience in infrastructure, engineering, and professional services procurement across the GCC, Asia-Pacific, and Europe.

Your task: Analyse the supplied tender / RFP document extract and return a SINGLE, COMPLETE JSON object.

STRICT OUTPUT RULES:
1. Output ONLY raw JSON — no markdown fences, no preamble text, no commentary outside the JSON.
2. Use JSON null for any field genuinely absent from the document. Never fabricate or guess.
3. Extract EXACT text for dates, amounts, reference numbers — do not paraphrase them.
4. For array fields, extract ALL items found — never truncate.
5. go_no_go_score must be an integer 0–100.

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
    {"label": "Document Issue / Available From", "date": "..."},
    {"label": "Pre-Bid Meeting",                 "date": "..."},
    {"label": "Query / Clarification Deadline",  "date": "..."},
    {"label": "Addendum Issuance Deadline",      "date": "..."},
    {"label": "Submission Deadline",             "date": "..."},
    {"label": "Bid Opening",                     "date": "..."},
    {"label": "Evaluation Period",               "date": "..."},
    {"label": "Award / LOI Expected",            "date": "..."},
    {"label": "Contract Commencement",           "date": "..."}
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

go_no_go_score guidance:
  ≥70 → GO        (strong fit, manageable risk, clear opportunity)
  40–69 → CONDITIONAL GO  (proceed with conditions or further review)
  <40 → NO-GO     (poor fit, high risk, or disqualifying factor)

Fill every field that has evidence in the document."""


def run_analysis(structured_text: str) -> dict:
    """Run AI extraction on the structured tender document."""
    context = build_analysis_context(structured_text)
    messages = [
        {"role": "system", "content": _ANALYSIS_SYSTEM},
        {"role": "user",   "content": (
            "Analyse this tender document extract and return the complete JSON.\n\n"
            f"{'═' * 60}\n{context}\n{'═' * 60}"
        )},
    ]
    raw    = _call_api(messages, max_tokens=4096)
    result = _parse_json(raw)
    filled = sum(1 for v in result.values() if v not in (None, [], ""))
    log.info("Analysis complete — %d/%d fields populated", filled, len(result))
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Chat / Q&A
# ──────────────────────────────────────────────────────────────────────────────
_CHAT_SYSTEM_TEMPLATE = """You are a senior bid manager and tender analyst with deep expertise in infrastructure and professional services procurement.

You are answering a question about the tender document below. Answer with precision and practical insight — as if briefing your bid team before a submission.

Guidelines:
- Be direct and specific. Reference exact clauses, dates, amounts where available.
- Use bullet points when listing multiple items.
- Flag any compliance traps, risks, or missing information that the team should know.
- If the answer is not clearly stated in the provided pages, say so explicitly — do not guess.
- Keep responses concise but complete. Expand only if the question requires it.

TENDER DOCUMENT — MOST RELEVANT PAGES:
{context}"""


def ask_followup(
    question: str,
    pages: list[dict],
    history: list[dict],
    analysis: dict | None = None,
) -> tuple[str, list[int]]:
    """
    Answer a question about the tender using retrieval-augmented context.

    Returns:
        answer      — the AI response text
        page_nums   — page numbers that were used as context
    """
    # Retrieve the most relevant pages for this question
    context, page_nums = retrieve_relevant_context(pages, question)

    # If we have a structured analysis, prepend a compact summary for grounding
    analysis_summary = ""
    if analysis:
        def _s(k: str) -> str:
            v = analysis.get(k)
            return str(v) if v and str(v).lower() not in ("null", "none") else "not stated"

        analysis_summary = (
            f"\n\nSTRUCTURED ANALYSIS SUMMARY (use as grounding — verify against pages below):\n"
            f"Project: {_s('project_name')} | Location: {_s('project_location')}\n"
            f"Submission Deadline: {_s('submission_deadline')}\n"
            f"Query Deadline: {_s('query_submission_deadline')}\n"
            f"Tender Validity: {_s('tender_validity_days')} days\n"
            f"Bid Security: {_s('bid_security')} | Performance Bond: {_s('performance_bond')}\n"
            f"LDs: {_s('liquidated_damages')} | Payment: {_s('payment_terms')}\n"
        )

    system_msg = _CHAT_SYSTEM_TEMPLATE.format(context=context + analysis_summary)

    messages = [{"role": "system", "content": system_msg}]
    for turn in history[-(CFG.CHAT_HISTORY_TURNS * 2):]:
        messages.append({"role": "user",      "content": turn["q"]})
        messages.append({"role": "assistant", "content": turn["a"]})
    messages.append({"role": "user", "content": question})

    answer = _call_api(messages, max_tokens=1200)
    return answer, page_nums


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def file_md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


_DATE_FMTS = [
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
    "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d %B %Y, %H:%M", "%d %b %Y, %H:%M",
    "%d %B %Y %H:%M", "%d %b %Y %H:%M",
    "%Y/%m/%d", "%d.%m.%Y",
]

_NULL_VALS = {"null", "none", "not specified", "not disclosed", "tbc", "tbd", "n/a", ""}


def days_until(date_str: str | None) -> int | None:
    if not date_str or str(date_str).strip().lower() in _NULL_VALS:
        return None
    clean = re.sub(r'\s+', ' ', str(date_str).strip())
    candidates = [clean, clean.split(" at ")[0].strip(), clean.split(",")[0].strip(), clean.split("(")[0].strip()]
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
    return          "nogo",      "NO-GO",          "#e05c5c"


def pct_int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r'(\d+)', str(s))
    return int(m.group(1)) if m else None


def null_disp(v: Any) -> str:
    """Return display-safe string, or styled 'Not stated'."""
    if v is None or str(v).strip().lower() in _NULL_VALS:
        return "<span style='color:#2a5060;font-style:italic;'>Not stated</span>"
    return str(v)


def li_html(items: list[str], color: str = "#97b8bb") -> str:
    if not items:
        return "<li style='color:#2a5060;font-style:italic;'>Not specified in document</li>"
    return "".join(
        f"<li style='margin-bottom:7px;color:{color};'>{i}</li>"
        for i in items
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
        return str(v) if v and str(v).lower() not in _NULL_VALS else "N/A"

    def bl(k: str) -> str:
        items = a.get(k) or []
        return "\n".join(f"- {i}" for i in items) if items else "- Not specified"

    def risk_md() -> str:
        risks = sorted(a.get("risks") or [], key=lambda x: {"High":0,"Medium":1,"Low":2}.get(x.get("level","Low"),1))
        return "\n".join(f"- **[{r.get('level','?')} · {r.get('category','')}]** {r.get('description','')}" for r in risks) or "- None identified"

    def dates_md() -> str:
        rows = [f"| {d.get('label','')} | {d.get('date','')} |" for d in (a.get("important_dates") or [])]
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

| **Submission Deadline** | {s("submission_deadline")} |
| **Query Deadline** | {s("query_submission_deadline")} |
| **Tender Validity** | {s("tender_validity_days")} days |

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

*Report generated by **Tendly v{CFG.APP_VERSION}** · Egis AI Tender Intelligence · {now}*
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
        for h in reversed(hist[-CFG.HISTORY_MAX:]):
            ah   = h["analysis"]
            proj = ah.get("project_name") or h["filename"]
            loc  = ah.get("project_location") or "—"
            sc   = int(ah.get("go_no_go_score") or 0)
            _, vt, vc = verdict_info(sc)
            st.markdown(f"""
            <div class="sb-card">
              <div class="sb-title">{proj[:42]}</div>
              <div class="sb-meta">📍 {loc[:34]}</div>
              <div class="sb-meta" style="color:{vc};margin-top:4px;">● {vt} &nbsp;·&nbsp; {sc}/100</div>
              <div class="sb-meta">🕐 {h["ts"]}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('<div class="divider-thin"></div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div style="padding:0.4rem 0 0.6rem;">
      <div style="display:flex;align-items:baseline;gap:0.6rem;padding:0.22rem 0;">
        <span style="font-size:0.54rem;color:#1C4055;letter-spacing:0.8px;text-transform:uppercase;
                     white-space:nowrap;min-width:38%;">Model</span>
        <span style="font-size:0.6rem;color:#1C4055;line-height:1.4;word-break:break-all;">
          {CFG.OPENROUTER_MODEL}
        </span>
      </div>
      <div style="display:flex;align-items:baseline;gap:0.6rem;padding:0.22rem 0;">
        <span style="font-size:0.54rem;color:#1C4055;letter-spacing:0.8px;text-transform:uppercase;
                     white-space:nowrap;min-width:38%;">Context</span>
        <span style="font-size:0.6rem;color:#1C4055;line-height:1.4;">
          {CFG.PDF_ANALYSIS_CHAR_BUDGET//1000}k &nbsp;·&nbsp;
          h {CFG.PDF_HEAD_CHARS//1000}k &nbsp;·&nbsp;
          m {CFG.PDF_MID_CHARS//1000}k &nbsp;·&nbsp;
          t {CFG.PDF_TAIL_CHARS//1000}k
        </span>
      </div>
      <div style="display:flex;align-items:baseline;gap:0.6rem;padding:0.22rem 0;">
        <span style="font-size:0.54rem;color:#1C4055;letter-spacing:0.8px;text-transform:uppercase;
                     white-space:nowrap;min-width:38%;">Retrieval</span>
        <span style="font-size:0.6rem;color:#1C4055;line-height:1.4;">
          top-{CFG.CHAT_MAX_SNIPPETS} &nbsp;×&nbsp; {CFG.CHAT_SNIPPET_CHARS//1000}k chars
        </span>
      </div>
      <div style="font-size:0.48rem;color:#163545;letter-spacing:0.8px;margin-top:0.5rem;">
        v{CFG.APP_VERSION} &nbsp;·&nbsp; Egis Tendly
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT ROUTING — choose between landing and analysis views
# The file uploader must be rendered in BOTH branches with the same key
# so Streamlit's widget tree stays consistent across reruns.
# ─────────────────────────────────────────────────────────────────────────────
_has_analysis = bool(st.session_state.get("file_hash"))

if _has_analysis:
    # ── ANALYSIS STATE: compact uploader bar at top ─────────────────────────
    st.markdown("""
    <div style="font-family:'Urbanist',sans-serif;font-size:0.54rem;font-weight:700;
                letter-spacing:2.5px;text-transform:uppercase;color:#2E5A68;
                margin-bottom:0.3rem;">
      Change Document
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
    # ── LANDING STATE: two-column workspace layout ──────────────────────────
    st.markdown('<div style="height:1.8rem;"></div>', unsafe_allow_html=True)
    lc_land, rc_land = st.columns([11, 9], gap="large")

    with lc_land:
        st.markdown("""
        <div style="padding:0 0 0.6rem;">
          <div style="font-family:'Urbanist',sans-serif;font-size:1.3rem;font-weight:800;
                      color:#F0F6F8;letter-spacing:-0.5px;line-height:1.2;margin-bottom:0.5rem;
                      max-width:500px;">
            Upload a tender PDF to extract every critical detail 
            <span style="color:#0099A5;font-weight:300;">instantly, accurately, intelligently.</span>
          </div>
        </div>
        """, unsafe_allow_html=True)
        uploaded_file = st.file_uploader(
            "Upload Tender Document",
            type=["pdf"],
            key="uploader",
            label_visibility="collapsed",
            help="Text-based PDFs only. Scanned / image-only PDFs require OCR pre-processing.",
        )
        st.markdown("""
        <div style="font-size:0.6rem;color:#163545;margin-top:0.4rem;letter-spacing:0.3px;">
          PDF · Text-based · up to 200 MB &nbsp;·&nbsp; Scanned files need OCR pre-processing
        </div>
        """, unsafe_allow_html=True)

    with rc_land:
        CAPS = [
            ("Overview",            "Project name, issuer, contract type, sector, governing law"),
            ("Scope & Eligibility", "Work scope, eligibility criteria, min. qualifications"),
            ("Dates & Deadlines",   "Submission, pre-bid, queries closing, validity period"),
            ("Checklist",           "Interactive document tracker with readiness meter"),
            ("Commercial",          "Bid bond, LD clauses, retention, payment milestones"),
            ("Risks & Flags",       "Categorised risk register with red-flag highlights"),
            ("Go / No-Go",          "0–100 verdict, win themes, clarification questions"),
            ("Ask Tendly",          "Full-document RAG Q&A — any question, any clause"),
        ]
        caps_rows = "".join(f"""
        <div style="display:flex;align-items:center;border-bottom:1px solid rgba(22,53,69,0.6);
                    padding:0.46rem 0;">
          <div style="font-family:'Urbanist',sans-serif;font-size:0.63rem;font-weight:700;
                      text-transform:uppercase;letter-spacing:0.8px;color:#0099A5;
                      white-space:nowrap;padding-right:0.75rem;min-width:38%;">
            {tab}
          </div>
          <div style="font-size:0.72rem;color:#6B8F96;line-height:1.45;padding-left:0.4rem;">
            {desc}
          </div>
        </div>""" for tab, desc in CAPS)
        st.markdown(f"""
        <div style="background:#0C2A38;border:1px solid #163545;
                    border-top:2px solid #ABC022;border-radius:2px;padding:1rem 1.2rem 0.5rem;">
          <div style="font-family:'Urbanist',sans-serif;font-size:0.5rem;font-weight:700;
                      letter-spacing:3px;text-transform:uppercase;color:#ABC022;margin-bottom:0.75rem;">
            What Tendly Extracts
          </div>
          <div style="width:100%;">{caps_rows}</div>
        </div>
        <div style="font-family:'Urbanist',sans-serif;font-size:0.48rem;letter-spacing:2.5px;
                    color:#163545;text-transform:uppercase;margin-top:0.9rem;text-align:right;">
          Imagine · Create · Achieve &nbsp;·&nbsp; Egis Group
        </div>
        """, unsafe_allow_html=True)
    # No uploaded_file yet — stop here; rerun will route to analysis state
    uploaded_file = uploaded_file  # reference for the extraction block below


# ─────────────────────────────────────────────────────────────────────────────
# UPLOAD + EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────
if uploaded_file:
    file_bytes = uploaded_file.read()
    fhash      = file_md5(file_bytes)
    uploaded_file.seek(0)

    if st.session_state.file_hash != fhash:
        with st.spinner("Reading PDF — extracting text and tables…"):
            try:
                pages, full_text, structured_text, stats = extract_pdf(uploaded_file)
                st.session_state.pages            = pages
                st.session_state.full_text        = full_text
                st.session_state.structured_text  = structured_text
                st.session_state.pdf_stats        = stats
                st.session_state.filename         = uploaded_file.name
                st.session_state.file_hash        = fhash
                st.session_state.analysis         = None
                st.session_state.analysis_error   = None
                st.session_state.chat_history     = []
                st.session_state.checklist_state  = {}
            except Exception as exc:
                st.error(f"PDF extraction failed: {exc}")
                log.exception("PDF extraction error")
                st.stop()

    stats      = st.session_state.pdf_stats
    full_text  = st.session_state.full_text
    pages      = st.session_state.pages

    # ── Stats bar ──────────────────────────────────────────────────────────
    st.markdown('<div class="divider-main"></div>', unsafe_allow_html=True)

    sub_dl  = (st.session_state.analysis or {}).get("submission_deadline")
    dl_days = days_until(sub_dl)
    dl_cls, dl_pill = deadline_display(dl_days)
    dl_val       = f"{dl_days}d" if dl_days is not None else "—"
    dl_box_class = "crit" if dl_cls == "crit" else ("warn" if dl_cls == "warn" else "")

    q_pct   = stats.get("quality_pct", 100)
    q_class = "good" if q_pct >= 80 else ("warn" if q_pct >= 50 else "crit")

    segs = ""
    for i in range(5):
        filled = q_pct >= (i + 1) * 20
        seg_cls = f"{'g' if q_pct >= 80 else ('w' if q_pct >= 50 else 'b')}" if filled else ""
        segs += f'<div class="quality-seg {seg_cls}"></div>'

    st.markdown(f"""
    <div class="stat-row">
      <div class="stat-box {q_class}">
        <span class="stat-value">{stats.get('pages','—')}</span>
        <span class="stat-label">Pages</span>
        <div class="quality-bar">{segs}</div>
      </div>
      <div class="stat-box">
        <span class="stat-value">{stats.get('words',0):,}</span>
        <span class="stat-label">Words</span>
      </div>
      <div class="stat-box">
        <span class="stat-value">{stats.get('chars',0)//1000}k</span>
        <span class="stat-label">Characters</span>
      </div>
      <div class="stat-box {q_class}">
        <span class="stat-value">{q_pct}%</span>
        <span class="stat-label">Text Quality</span>
      </div>
 
    """, unsafe_allow_html=True)

    if stats.get("image_pages", 0) > 0:
        st.warning(
            f"⚠️ **{stats['image_pages']} image-only page(s)** detected — these cannot be read as text. "
            "For best results, use a PDF with embedded selectable text or pre-process with an OCR tool."
        )

    # ── Analyse button ─────────────────────────────────────────────────────
    btn_col, _ = st.columns([1, 3])
    with btn_col:
        do_analyse = st.button("⚡  Analyse Tender", use_container_width=True)

    if do_analyse:
        with st.spinner("Analysing tender — extracting all fields…"):
            try:
                result = run_analysis(st.session_state.structured_text)
                st.session_state.analysis       = result
                st.session_state.analysis_error = None
                st.session_state.chat_history   = []
                st.session_state.checklist_state = {item: False for item in (result.get("submission_checklist") or [])}
                st.session_state.tender_history.append({
                    "filename": uploaded_file.name,
                    "analysis": result,
                    "ts":       datetime.now().strftime("%d %b %Y %H:%M"),
                })
                if len(st.session_state.tender_history) > CFG.HISTORY_MAX:
                    st.session_state.tender_history.pop(0)
                st.rerun()
            except json.JSONDecodeError as exc:
                st.error(f"Could not parse AI response as JSON: {exc}")
            except RuntimeError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")
                log.exception("Analysis error")

    # ──────────────────────────────────────────────────────────────────────
    # RESULTS DISPLAY
    # ──────────────────────────────────────────────────────────────────────
    if st.session_state.analysis:
        a = st.session_state.analysis

        st.markdown('<div class="divider-main"></div>', unsafe_allow_html=True)

        # ── Verdict banner ────────────────────────────────────────────────
        score = int(a.get("go_no_go_score") or 0)
        v_mod, v_label, v_color = verdict_info(score)

        st.markdown(f"""
        <div class="verdict verdict--{v_mod}">
          <div class="verdict-eyebrow">Tendly Go / No-Go Assessment</div>
          <div class="verdict-word" style="color:{v_color};font-family:'Urbanist','Segoe UI',sans-serif;">{v_label}</div>
          <div class="verdict-score">{score} / 100</div>
          <div class="verdict-rationale">{a.get('go_no_go_rationale') or ''}</div>
        </div>
        """, unsafe_allow_html=True)

        # ── TABS ──────────────────────────────────────────────────────────
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

        # ═══════════════════════════════════════════════════════════════════
        # TAB 1 — OVERVIEW
        # ═══════════════════════════════════════════════════════════════════
        with tabs[0]:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"""
                <div class="hero-card">
                  <div class="hero-label">Project Name</div>
                  <div class="hero-value">{a.get('project_name') or 'Not extracted'}</div>
                </div>""", unsafe_allow_html=True)
            with c2:
                st.markdown(f"""
                <div class="hero-card">
                  <div class="hero-label">📍 Location</div>
                  <div class="hero-value">{a.get('project_location') or 'Not extracted'}</div>
                </div>""", unsafe_allow_html=True)

            st.markdown(f"""
            <div class="card card--teal-left">
              <div class="card-label">Executive Summary</div>
              <div class="card-body">{a.get('summary') or 'Not extracted'}</div>
            </div>""", unsafe_allow_html=True)

            oc1, oc2, oc3 = st.columns(3)
            with oc1:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">Client & Reference</div>
                  {kv_html([("Issuing Body", a.get("issuer")), ("Department", a.get("issuer_department")), ("Reference No.", a.get("tender_reference"))])}
                </div>""", unsafe_allow_html=True)
            with oc2:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">Tender Details</div>
                  {kv_html([("Sector", f"{a.get('sector') or '—'} · {a.get('sub_sector') or '—'}"), ("Contract Type", a.get("contract_type")), ("Value", f"{a.get('tender_value') or '—'} {a.get('currency') or ''}".strip()), ("Duration", a.get("project_duration"))])}
                </div>""", unsafe_allow_html=True)
            with oc3:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">Conditions</div>
                  {kv_html([("Language", a.get("language_requirement")), ("Governing Law", a.get("governing_law")), ("Dispute Resolution", a.get("dispute_resolution"))])}
                </div>""", unsafe_allow_html=True)

        # ═══════════════════════════════════════════════════════════════════
        # TAB 2 — SCOPE & ELIGIBILITY
        # ═══════════════════════════════════════════════════════════════════
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

                ev_items = a.get("evaluation_criteria") or []
                st.markdown(f"""
                <div class="card">
                  <div class="card-label">⚖️ Evaluation Criteria</div>
                  <div style="display:flex;gap:1.2rem;margin-bottom:0.7rem;">
                    <span style="font-size:0.74rem;color:#009aa6;">Technical: <b>{a.get('technical_weight') or 'N/A'}</b></span>
                    <span style="font-size:0.74rem;color:#abc022;">Financial: <b>{a.get('financial_weight') or 'N/A'}</b></span>
                    <span style="font-size:0.74rem;color:#5d858b;">Method: {a.get('evaluation_method') or 'N/A'}</span>
                  </div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">
                    {li_html(ev_items)}
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

        # ═══════════════════════════════════════════════════════════════════
        # TAB 3 — DATES & DEADLINES
        # ═══════════════════════════════════════════════════════════════════
        with tabs[2]:
            dc1, dc2 = st.columns(2)

            with dc1:
                # Spotlight deadline cards
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
                        <span class="tl-date {cls}">{val or 'Not specified'}</span>
                        {pill_html}
                      </div>
                    </div>""", unsafe_allow_html=True)

                # Tender validity
                tv = a.get("tender_validity_days")
                tv_display = f"{tv} days" if tv and str(tv).isdigit() else (tv or "Not specified")
                st.markdown(f"""
                <div class="card" style="padding:0.9rem 1.2rem;margin-bottom:0.55rem;">
                  <div style="font-size:0.6rem;letter-spacing:2.5px;text-transform:uppercase;color:#5d858b;margin-bottom:4px;">⏳ Tender Validity</div>
                  <span class="tl-date">{tv_display}</span>
                </div>""", unsafe_allow_html=True)

            with dc2:
                all_dates = a.get("important_dates") or []
                if all_dates:
                    st.markdown("""
                    <div class="card card--teal-top" style="padding-bottom:0.4rem;">
                      <div class="card-label">📅 Full Tender Timeline</div>
                    </div>""", unsafe_allow_html=True)
                    for d in all_dates:
                        lbl2 = d.get("label", "")
                        dt   = d.get("date", "") or "—"
                        d2   = days_until(dt)
                        cls2, pill2 = deadline_display(d2)
                        pill_h = f"<span class='tl-pill {cls2}'>{pill2}</span>" if pill2 else ""
                        st.markdown(f"""
                        <div style="display:flex;justify-content:space-between;align-items:center;
                                    padding:0.55rem 1.2rem;border-bottom:1px solid #102030;
                                    background:#0d2d3a;">
                          <span style="font-size:0.83rem;color:#7a9ea3;">{lbl2}</span>
                          <span style="display:flex;align-items:center;gap:6px;">
                            <span style="font-size:0.87rem;font-weight:500;
                                         color:{'#e05c5c' if cls2=='crit' else ('#e09a3a' if cls2=='warn' else '#abc022')};">{dt}</span>
                            {pill_h}
                          </span>
                        </div>""", unsafe_allow_html=True)

                req_items = a.get("submission_requirements") or []
                st.markdown(f"""
                <div class="card" style="margin-top:0.9rem;">
                  <div class="card-label">📦 Submission Requirements</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">
                    {li_html(req_items)}
                  </ul>
                </div>""", unsafe_allow_html=True)

        # ═══════════════════════════════════════════════════════════════════
        # TAB 4 — SUBMISSION CHECKLIST
        # ═══════════════════════════════════════════════════════════════════
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

                for item in checklist:
                    if item not in st.session_state.checklist_state:
                        st.session_state.checklist_state[item] = False
                    checked = st.checkbox(
                        item,
                        value=st.session_state.checklist_state[item],
                        key=f"chk_{abs(hash(item)) % 9_999_991}",
                    )
                    st.session_state.checklist_state[item] = checked

                st.markdown('<div class="divider-thin"></div>', unsafe_allow_html=True)
                st.caption(
                    "⚠️ This checklist is AI-extracted from the tender document. "
                    "Always verify against the original RFP. Your internal bid process may require additional documents."
                )

        # ═══════════════════════════════════════════════════════════════════
        # TAB 5 — COMMERCIAL
        # ═══════════════════════════════════════════════════════════════════
        with tabs[4]:
            cc1, cc2 = st.columns(2)

            with cc1:
                st.markdown(f"""
                <div class="card card--teal-top">
                  <div class="card-label">💰 Financial Terms</div>
                  {kv_html([
                    ("Bid Security / EMD",   a.get("bid_security")),
                    ("Performance Bond",     a.get("performance_bond")),
                    ("Retention",            a.get("retention")),
                    ("Advance Payment",      a.get("advance_payment")),
                    ("Liquidated Damages",   a.get("liquidated_damages")),
                    ("Payment Terms",        a.get("payment_terms")),
                  ])}
                </div>""", unsafe_allow_html=True)

                ins = a.get("insurance_requirements") or []
                st.markdown(f"""
                <div class="card">
                  <div class="card-label">🛡️ Insurance Requirements</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">{li_html(ins)}</ul>
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
                        <div class="prog-track"><div class="prog-fill" style="background:#009aa6;width:{tw_i}%"></div></div>
                      </div>
                      <div class="prog-wrap">
                        <div class="prog-header"><span>Financial</span><span style="color:#abc022">{fw_i}%</span></div>
                        <div class="prog-track"><div class="prog-fill" style="background:#abc022;width:{fw_i}%"></div></div>
                      </div>
                      <div style="font-size:0.73rem;color:#5d858b;margin-top:0.2rem;">
                        Method: <span style="color:#97b8bb">{a.get('evaluation_method') or 'Not specified'}</span>
                      </div>
                    </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div class="card-label">🤝 JV, Consortium & Subcontracting</div>
                  {kv_html([("JV / Consortium", a.get("jv_consortium_rules")), ("Subcontracting", a.get("subcontracting_rules"))])}
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card">
                  <div class="card-label">⚙️ Legal & Governance</div>
                  {kv_html([("Governing Law", a.get("governing_law")), ("Dispute Resolution", a.get("dispute_resolution")), ("Language", a.get("language_requirement"))])}
                </div>""", unsafe_allow_html=True)

        # ═══════════════════════════════════════════════════════════════════
        # TAB 6 — RISKS & FLAGS
        # ═══════════════════════════════════════════════════════════════════
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
                    badge_cls = {"High":"badge-high","Medium":"badge-med","Low":"badge-low"}.get(lvl,"badge-med")
                    st.markdown(f"""
                    <div class="card" style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;padding:0.82rem 1.2rem;">
                      <div style="flex:1">
                        <span style="font-size:0.6rem;letter-spacing:1px;color:#5d858b;text-transform:uppercase;">{cat}</span>
                        <div class="card-body" style="margin-top:4px;">{desc}</div>
                      </div>
                      <span class="badge {badge_cls}" style="margin-top:2px;">{lvl}</span>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown('<div class="card"><div class="card-body">No risks identified in this document.</div></div>', unsafe_allow_html=True)

            red_flags = a.get("red_flags") or []
            if red_flags:
                st.markdown('<div class="sec-head" style="color:#e05c5c;">🚩 Red Flags — Escalate Before Bidding</div>', unsafe_allow_html=True)
                for f in red_flags:
                    st.markdown(f"""
                    <div class="card card--red-left" style="padding:0.82rem 1.2rem;">
                      <div class="card-body">⚠ {f}</div>
                    </div>""", unsafe_allow_html=True)

        # ═══════════════════════════════════════════════════════════════════
        # TAB 7 — ASSESSMENT
        # ═══════════════════════════════════════════════════════════════════
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
                    <span class="badge {'badge-low' if score>=70 else ('badge-med' if score>=40 else 'badge-high')}"
                          style="font-size:0.82rem;padding:3px 12px;margin-left:0.3rem;">
                      {v_label}
                    </span>
                  </div>
                  <div class="card-body" style="margin-top:0.9rem;">{a.get('go_no_go_rationale') or ''}</div>
                </div>""", unsafe_allow_html=True)

                st.markdown(f"""
                <div class="card card--green-left">
                  <div class="card-label">📋 Recommendation</div>
                  <div class="card-body">{a.get('recommendation') or ''}</div>
                </div>""", unsafe_allow_html=True)

            with ac2:
                wt = a.get("win_themes") or []
                st.markdown(f"""
                <div class="card card--green-left">
                  <div class="card-label">🏆 Win Themes</div>
                  <ul class="card-body" style="padding-left:1.1rem;margin:0">{li_html(wt, "#abc022")}</ul>
                </div>""", unsafe_allow_html=True)

                wi = a.get("watch_items") or []
                if wi:
                    st.markdown(f"""
                    <div class="card card--orange-left">
                      <div class="card-label">👁 Watch Items</div>
                      <ul class="card-body" style="padding-left:1.1rem;margin:0">{li_html(wi, "#e09a3a")}</ul>
                    </div>""", unsafe_allow_html=True)

        # ═══════════════════════════════════════════════════════════════════
        # TAB 8 — ASK TENDLY
        # ═══════════════════════════════════════════════════════════════════
        with tabs[7]:
            st.markdown("""
            <div style="font-size:0.81rem;color:#5d858b;margin-bottom:1rem;line-height:1.72;">
            Ask anything about this tender. Answers are grounded in the most relevant pages of the
            document — Sources are shown after each response.
            </div>
            """, unsafe_allow_html=True)

            # Quick-fire question buttons
            QUICK_QS = [
                "List all documents required for submission",
                "What are the top 3 risks to flag to leadership?",
                "What experience and credentials must we demonstrate?",
                "Is JV or consortium allowed? What are the rules?",
                "What is the payment structure and retention policy?",
            ]

            # ── Quick Questions — equal-height buttons ────────────────────
            # ROOT CAUSE of all previous attempts failing:
            # Streamlit injects its own wrapper divs (stVerticalBlock,
            # stVerticalBlockBorderWrapper, etc.) between any st.markdown()
            # div and the st.columns() output.  CSS child selectors (">")
            # therefore never match across that boundary.
            #
            # THE ONLY RELIABLE FIX: target buttons directly by their key
            # (Streamlit sets data-testid="stButton" and the key appears on
            # the button element), and enforce a FIXED height.  No ancestor
            # chain needed — the browser sizes every matched button to the
            # same fixed value regardless of text length.
            st.markdown("""
            <style>
            .qq-label {
                font-size: 0.58rem;
                letter-spacing: 2.5px;
                text-transform: uppercase;
                color: #2a5060;
                margin-bottom: 0.6rem;
            }
            /* Target all qq_ buttons by key prefix ───────────────────────
               Streamlit renders:  div[data-testid="stButton"] > button
               The button's test-id is "baseButton-secondary-qq_0" etc.   */
            button[data-testid^="baseButton-secondary-qq_"],
            button[key^="qq_"] {
                height: 110px             !important;
                white-space: normal       !important;
                word-break: break-word    !important;
                text-align: center        !important;
                line-height: 1.55         !important;
                padding: 0.75rem 0.6rem   !important;
                display: flex             !important;
                align-items: center       !important;
                justify-content: center   !important;
                font-size: 0.68rem        !important;
                font-weight: 700          !important;
                letter-spacing: 1.6px     !important;
            }
            </style>
            """, unsafe_allow_html=True)

            st.markdown('<div class="qq-label">Quick Questions</div>', unsafe_allow_html=True)
            qq_cols = st.columns(len(QUICK_QS))
            for i, (col, q) in enumerate(zip(qq_cols, QUICK_QS)):
                with col:
                    if st.button(q, key=f"qq_{i}", use_container_width=True):
                        with st.spinner("Finding relevant pages and answering…"):
                            try:
                                ans, pgs = ask_followup(
                                    q, pages, st.session_state.chat_history, a
                                )
                                st.session_state.chat_history.append({
                                    "q":       q,
                                    "a":       ans,
                                    "ts":      datetime.now().strftime("%H:%M"),
                                    "sources": pgs,
                                })
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))

            st.markdown('<div class="divider-thin"></div>', unsafe_allow_html=True)

            # Conversation history
            for turn in st.session_state.chat_history:
                st.markdown(f'<div class="bubble-user">{turn["q"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="bubble-ai">{turn["a"]}</div>', unsafe_allow_html=True)
                src = turn.get("sources")
                if src:
                    src_str = ", ".join(f"p.{p}" for p in src)
                    st.markdown(
                        f'<div class="bubble-ts">Sources: {src_str} &nbsp;·&nbsp; {turn.get("ts","")}</div>',
                        unsafe_allow_html=True,
                    )

            # Input
            user_q = st.text_input(
                "Your question",
                placeholder="e.g.  What are the LD caps?  /  Does this require FIDIC?  /  What is the bid bond amount?",
                label_visibility="collapsed",
                key="chat_q",
            )
            btn_ask, btn_clear = st.columns([3, 1])
            with btn_ask:
                if st.button("Ask Tendly  →", use_container_width=True):
                    if user_q.strip():
                        with st.spinner("Finding relevant pages and answering…"):
                            try:
                                ans, pgs = ask_followup(
                                    user_q, pages, st.session_state.chat_history, a
                                )
                                st.session_state.chat_history.append({
                                    "q":       user_q,
                                    "a":       ans,
                                    "ts":      datetime.now().strftime("%H:%M"),
                                    "sources": pgs,
                                })
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
            with btn_clear:
                if st.button("Clear", use_container_width=True):
                    st.session_state.chat_history = []
                    st.rerun()

        # ── EXPORT BAR ─────────────────────────────────────────────────────
        st.markdown('<div class="divider-main"></div>', unsafe_allow_html=True)
        fname_base = uploaded_file.name.replace(".pdf", "").replace(" ", "_")
        report_md  = build_markdown_report(a, uploaded_file.name)

        ec1, ec2, ec3, _ = st.columns([1, 1, 1, 2])
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
            cl_export = "\n".join(
                f"{'[x]' if st.session_state.checklist_state.get(i, False) else '[ ]'} {i}"
                for i in (a.get("submission_checklist") or [])
            )
            st.download_button(
                "⬇  Checklist (.txt)",
                data=cl_export or "No checklist items extracted.",
                file_name=f"tendly_checklist_{fname_base}.txt",
                mime="text/plain",
                use_container_width=True,
            )

    # ── Raw text expander ──────────────────────────────────────────────────
    with st.expander("📄  View Extracted PDF Text"):
        st.markdown(f"""
        <div style="font-size:0.68rem;color:#5d858b;margin-bottom:0.5rem;">
        {stats.get('pages','?')} pages &nbsp;·&nbsp; {stats.get('words',0):,} words &nbsp;·&nbsp;
        {stats.get('text_pages','?')} readable &nbsp;·&nbsp; {stats.get('image_pages','?')} image-only &nbsp;·&nbsp;
        text quality {stats.get('quality_pct','?')}%
        </div>
        """, unsafe_allow_html=True)
        st.text_area(
            "Extracted Content",
            full_text,
            height=380,
            label_visibility="collapsed",
        )
