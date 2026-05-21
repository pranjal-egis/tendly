# import streamlit as st
# import pdfplumber
# import requests
# import os

# # =====================
# # CONFIG
# # =====================
# OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "YOUR_API_KEY")

# st.set_page_config(page_title="Tendly", layout="wide")

# st.title("📑 Tendly")
# st.subheader("AI Tender Intelligence Platform")

# # =====================
# # FILE UPLOAD
# # =====================
# uploaded_file = st.file_uploader(
#     "Upload Tender Document",
#     type=["pdf"]
# )

# # =====================
# # PDF TEXT EXTRACTION
# # =====================
# def extract_full_pdf_text(file):
#     full_text = ""
    
#     with pdfplumber.open(file) as pdf:
#         for i, page in enumerate(pdf.pages):
#             text = page.extract_text()

#             if text:
#                 full_text += f"\n\n--- PAGE {i+1} ---\n\n{text}"
#             else:
#                 full_text += f"\n\n--- PAGE {i+1} (NO TEXT FOUND) ---\n\n"

#     return full_text

# # =====================
# # MAIN LOGIC
# # =====================
# if uploaded_file:

#     st.info("Reading PDF...")

#     full_text = extract_full_pdf_text(uploaded_file)

#     st.success("Tender Uploaded Successfully")

#     st.write("## 📄 Extracted Tender Text")

#     st.text_area(
#         "Tender Content (Full)",
#         full_text,
#         height=400
#     )

#     st.write(f"📊 Total characters extracted: {len(full_text)}")

#     # =====================
#     # AI ANALYSIS BUTTON
#     # =====================
#     if st.button("Generate AI Summary"):

#         if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "YOUR_API_KEY":
#             st.error("⚠️ Please set your OpenRouter API key")
#             st.stop()

#         prompt = f"""
#         Analyze this tender document and provide:

#         1. Tender Summary
#         2. Scope of Work
#         3. Eligibility Criteria
#         4. Important Dates
#         5. Risks
#         6. Submission Requirements

#         Tender Document:
#         {full_text[:10000]}
#         """

#         with st.spinner("Analyzing tender with AI..."):

#             try:
#                 response = requests.post(
#                     url="https://openrouter.ai/api/v1/chat/completions",
#                     headers={
#                         "Authorization": f"Bearer {OPENROUTER_API_KEY}",
#                         "Content-Type": "application/json",
#                     },
#                     json={
#                         "model": "openai/gpt-3.5-turbo",
#                         "messages": [
#                             {"role": "user", "content": prompt}
#                         ]
#                     },
#                     timeout=60
#                 )

#                 result = response.json()

#                 # =====================
#                 # SAFE RESPONSE HANDLING
#                 # =====================
#                 if "choices" in result:
#                     ai_output = result["choices"][0]["message"]["content"]
#                     st.write("## 🤖 AI Analysis")
#                     st.write(ai_output)
#                 else:
#                     st.error("API Error:")
#                     st.json(result)

#             except Exception as e:
#                 st.error(f"Request failed: {str(e)}")



import streamlit as st
import pdfplumber
import requests
import json
import os
from datetime import datetime

# =====================
# PAGE CONFIG
# =====================
st.set_page_config(
    page_title="Tendly · AI Tender Intelligence",
    page_icon="📑",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# =====================
# CUSTOM CSS
# =====================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Background */
.stApp {
    background: #0e0f13;
    color: #e8e4dc;
}

/* Header */
.tendly-header {
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 4px;
}
.tendly-logo {
    font-family: 'DM Serif Display', serif;
    font-size: 3rem;
    color: #e8e4dc;
    letter-spacing: -1px;
    line-height: 1;
}
.tendly-tag {
    font-size: 0.8rem;
    font-weight: 500;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #c8a96e;
    border: 1px solid #c8a96e44;
    padding: 3px 10px;
    border-radius: 2px;
    margin-left: 4px;
    vertical-align: middle;
}
.tendly-sub {
    font-size: 0.95rem;
    color: #7a7a7a;
    margin-bottom: 2rem;
    font-weight: 300;
}

/* Divider */
.gold-divider {
    height: 1px;
    background: linear-gradient(90deg, #c8a96e, transparent);
    margin: 1.5rem 0;
}

/* Cards */
.analysis-card {
    background: #161820;
    border: 1px solid #2a2c35;
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.analysis-card:hover {
    border-color: #c8a96e55;
}
.card-icon {
    font-size: 1.4rem;
    margin-bottom: 0.5rem;
}
.card-title {
    font-family: 'DM Serif Display', serif;
    font-size: 1.1rem;
    color: #c8a96e;
    margin-bottom: 0.5rem;
}
.card-body {
    font-size: 0.9rem;
    color: #b8b8b8;
    line-height: 1.7;
}

/* Risk badges */
.risk-high   { color: #e05c5c; background: #e05c5c18; border: 1px solid #e05c5c44; padding: 2px 10px; border-radius: 20px; font-size: 0.78rem; font-weight: 600; }
.risk-medium { color: #e09a3a; background: #e09a3a18; border: 1px solid #e09a3a44; padding: 2px 10px; border-radius: 20px; font-size: 0.78rem; font-weight: 600; }
.risk-low    { color: #4caf78; background: #4caf7818; border: 1px solid #4caf7844; padding: 2px 10px; border-radius: 20px; font-size: 0.78rem; font-weight: 600; }

/* Stat boxes */
.stat-row {
    display: flex;
    gap: 12px;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
}
.stat-box {
    flex: 1;
    min-width: 120px;
    background: #161820;
    border: 1px solid #2a2c35;
    border-radius: 6px;
    padding: 1rem;
    text-align: center;
}
.stat-value {
    font-family: 'DM Serif Display', serif;
    font-size: 1.6rem;
    color: #c8a96e;
}
.stat-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #555;
    margin-top: 4px;
}

/* Upload area */
.stFileUploader > div {
    border: 1px dashed #3a3c47 !important;
    border-radius: 8px !important;
    background: #13141a !important;
}

/* Buttons */
.stButton > button {
    background: #c8a96e !important;
    color: #0e0f13 !important;
    border: none !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.5px !important;
    padding: 0.6rem 2rem !important;
    border-radius: 4px !important;
    transition: opacity 0.2s !important;
}
.stButton > button:hover {
    opacity: 0.85 !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: transparent;
    border-bottom: 1px solid #2a2c35;
    gap: 0;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #7a7a7a !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.5px !important;
    padding: 0.6rem 1.2rem !important;
    border-bottom: 2px solid transparent !important;
}
.stTabs [aria-selected="true"] {
    color: #c8a96e !important;
    border-bottom-color: #c8a96e !important;
}

/* Chat */
.chat-bubble-user {
    background: #1e2028;
    border: 1px solid #2a2c35;
    border-radius: 8px 8px 2px 8px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
    color: #e8e4dc;
    text-align: right;
}
.chat-bubble-ai {
    background: #161820;
    border: 1px solid #2a2c35;
    border-left: 3px solid #c8a96e;
    border-radius: 2px 8px 8px 8px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
    font-size: 0.9rem;
    color: #b8b8b8;
    line-height: 1.7;
}

/* Text areas and inputs */
.stTextArea textarea, .stTextInput input {
    background: #13141a !important;
    border: 1px solid #2a2c35 !important;
    color: #e8e4dc !important;
    font-family: 'DM Sans', sans-serif !important;
    border-radius: 6px !important;
}

/* Spinner */
.stSpinner > div {
    border-top-color: #c8a96e !important;
}

/* Success/info/error */
.stSuccess, .stInfo, .stError {
    border-radius: 6px !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #0a0b0e !important;
}

/* Hide streamlit branding */
#MainMenu, footer, header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# =====================
# HEADER
# =====================
st.markdown("""
<div class="tendly-header">
    <span class="tendly-logo">Tendly</span>
    <span class="tendly-tag">AI Intelligence</span>
</div>
<div class="tendly-sub">Upload a tender document and get structured AI analysis in seconds.</div>
<div class="gold-divider"></div>
""", unsafe_allow_html=True)

# =====================
# SESSION STATE INIT
# =====================
if "analysis" not in st.session_state:
    st.session_state.analysis = None
if "full_text" not in st.session_state:
    st.session_state.full_text = ""
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "filename" not in st.session_state:
    st.session_state.filename = ""

# =====================
# HELPERS
# =====================
# =====================
# CONFIG
# =====================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "YOUR_API_KEY")
OPENROUTER_MODEL   = "openai/gpt-3.5-turbo"   # swap to any free model on OpenRouter

def call_openrouter(messages: list, max_tokens: int = 1500) -> str:
    """Central OpenRouter call — returns the assistant message text."""
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "YOUR_API_KEY":
        st.error("⚠️ Please set your OPENROUTER_API_KEY environment variable.")
        st.stop()

    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    result = response.json()

    if "choices" not in result:
        raise RuntimeError(f"OpenRouter error: {result}")

    return result["choices"][0]["message"]["content"]

def extract_full_pdf_text(file) -> tuple[str, dict]:
    """Extract text from PDF, return (full_text, stats)."""
    full_text = ""
    page_count = 0
    word_count = 0

    with pdfplumber.open(file) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                full_text += f"\n\n--- PAGE {i+1} ---\n\n{text}"
                word_count += len(text.split())
            else:
                full_text += f"\n\n--- PAGE {i+1} (NO TEXT FOUND) ---\n\n"

    stats = {
        "pages": page_count,
        "words": word_count,
        "chars": len(full_text),
    }
    return full_text, stats

def run_analysis(text: str) -> dict:
    """Call OpenRouter and return structured JSON analysis."""
    system_prompt = (
        "You are an expert tender analyst. Analyze tender documents and return ONLY valid JSON "
        "with no markdown fences and no extra text. Return this exact structure:\n"
        '{"summary":"...","issuer":"...","tender_value":"...","sector":"...",'
        '"scope":["..."],"eligibility":["..."],'
        '"important_dates":[{"label":"...","date":"..."}],'
        '"submission_requirements":["..."],"evaluation_criteria":["..."],'
        '"risks":[{"description":"...","level":"High/Medium/Low"}],'
        '"red_flags":["..."],"recommendation":"..."}'
    )

    truncated = text[:10000]   # stay within free-tier context limits

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": f"Analyze this tender document:\n\n{truncated}"},
    ]

    raw = call_openrouter(messages, max_tokens=1500).strip()

    # Strip any accidental markdown fences the model adds
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    return json.loads(raw)

def ask_followup(question: str, text: str, history: list) -> str:
    """Answer a follow-up question about the tender via OpenRouter."""
    system_msg = (
        "You are a tender analysis assistant. Answer questions about the tender document below "
        "concisely and accurately. Be direct. Use bullet points when listing multiple items. "
        "Keep answers under 250 words unless asked for more.\n\n"
        f"TENDER DOCUMENT (first 8,000 chars):\n{text[:8000]}"
    )

    messages = [{"role": "system", "content": system_msg}]
    for h in history[-6:]:   # keep last 6 turns for context
        messages.append({"role": "user",      "content": h["q"]})
        messages.append({"role": "assistant", "content": h["a"]})
    messages.append({"role": "user", "content": question})

    return call_openrouter(messages, max_tokens=600)

def export_report(analysis: dict, filename: str) -> str:
    """Generate a plain-text report for download."""
    lines = [
        "TENDLY AI ANALYSIS REPORT",
        f"Generated: {datetime.now().strftime('%d %b %Y, %H:%M')}",
        f"Document: {filename}",
        "=" * 60,
        "",
        "SUMMARY",
        analysis.get("summary", ""),
        "",
        f"Issuer       : {analysis.get('issuer', 'N/A')}",
        f"Tender Value : {analysis.get('tender_value', 'N/A')}",
        f"Sector       : {analysis.get('sector', 'N/A')}",
        "",
        "SCOPE OF WORK",
        *[f"  • {s}" for s in analysis.get("scope", [])],
        "",
        "ELIGIBILITY CRITERIA",
        *[f"  • {e}" for e in analysis.get("eligibility", [])],
        "",
        "IMPORTANT DATES",
        *[f"  {d['label']}: {d['date']}" for d in analysis.get("important_dates", [])],
        "",
        "SUBMISSION REQUIREMENTS",
        *[f"  • {r}" for r in analysis.get("submission_requirements", [])],
        "",
        "EVALUATION CRITERIA",
        *[f"  • {c}" for c in analysis.get("evaluation_criteria", [])],
        "",
        "RISKS",
        *[f"  [{r['level']}] {r['description']}" for r in analysis.get("risks", [])],
        "",
        "RED FLAGS",
        *[f"  ⚠ {f}" for f in analysis.get("red_flags", [])],
        "",
        "RECOMMENDATION",
        analysis.get("recommendation", ""),
        "",
        "=" * 60,
        "Generated by Tendly · AI Tender Intelligence",
    ]
    return "\n".join(lines)

# =====================
# FILE UPLOAD SECTION
# =====================
col_upload, col_info = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader(
        "Upload Tender Document (PDF)",
        type=["pdf"],
        label_visibility="collapsed",
        help="Supports text-based PDFs up to ~50 pages"
    )

with col_info:
    st.markdown("""
    <div style="padding: 1rem; background: #13141a; border-radius: 8px; border: 1px solid #2a2c35; font-size: 0.82rem; color: #7a7a7a; line-height: 1.8;">
    <strong style="color: #c8a96e;">What Tendly analyses:</strong><br>
    📌 Scope & deliverables<br>
    ✅ Eligibility & compliance<br>
    📅 Critical dates<br>
    ⚠️ Risks & red flags<br>
    📋 Submission requirements<br>
    🎯 Go/No-Go recommendation
    </div>
    """, unsafe_allow_html=True)

# =====================
# MAIN LOGIC
# =====================
if uploaded_file:

    # Re-extract only when a new file is uploaded
    if st.session_state.filename != uploaded_file.name:
        with st.spinner("Reading PDF..."):
            st.session_state.full_text, stats = extract_full_pdf_text(uploaded_file)
            st.session_state.filename = uploaded_file.name
            st.session_state.analysis = None
            st.session_state.chat_history = []

    full_text = st.session_state.full_text
    _, stats = extract_full_pdf_text(uploaded_file)

    st.markdown('<div class="gold-divider"></div>', unsafe_allow_html=True)

    # Stats row
    st.markdown(f"""
    <div class="stat-row">
        <div class="stat-box">
            <div class="stat-value">{stats['pages']}</div>
            <div class="stat-label">Pages</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{stats['words']:,}</div>
            <div class="stat-label">Words</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{stats['chars']//1000}k</div>
            <div class="stat-label">Characters</div>
        </div>
        <div class="stat-box">
            <div class="stat-value" style="font-size:1rem; padding-top:6px; color:#4caf78;">✓</div>
            <div class="stat-label">Extracted</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Analyse button
    col_btn, col_spacer = st.columns([1, 3])
    with col_btn:
        analyze_btn = st.button("⚡ Analyse Tender", use_container_width=True)

    if analyze_btn:
        with st.spinner("Analysing with Claude..."):
            try:
                st.session_state.analysis = run_analysis(full_text)
                st.session_state.chat_history = []
            except json.JSONDecodeError as e:
                st.error(f"Could not parse AI response as JSON: {e}")
            except RuntimeError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Unexpected error: {e}")

    # ========================
    # DISPLAY ANALYSIS
    # ========================
    if st.session_state.analysis:
        a = st.session_state.analysis

        st.markdown('<div class="gold-divider"></div>', unsafe_allow_html=True)

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📋 Overview", "📐 Scope & Eligibility",
            "📅 Dates & Requirements", "⚠️ Risks & Flags", "💬 Ask Tendly"
        ])

        # ── TAB 1: OVERVIEW ──────────────────────────────────
        with tab1:
            st.markdown(f"""
            <div class="analysis-card">
                <div class="card-title">Summary</div>
                <div class="card-body">{a.get('summary', 'N/A')}</div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-icon">🏢</div>
                    <div class="card-title">Issuing Body</div>
                    <div class="card-body">{a.get('issuer', 'Not specified')}</div>
                </div>
                """, unsafe_allow_html=True)
            with c2:
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-icon">💰</div>
                    <div class="card-title">Tender Value</div>
                    <div class="card-body">{a.get('tender_value', 'Not specified')}</div>
                </div>
                """, unsafe_allow_html=True)
            with c3:
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-icon">🏭</div>
                    <div class="card-title">Sector</div>
                    <div class="card-body">{a.get('sector', 'Not specified')}</div>
                </div>
                """, unsafe_allow_html=True)

            # Recommendation
            rec = a.get("recommendation", "")
            st.markdown(f"""
            <div class="analysis-card" style="border-left: 3px solid #c8a96e;">
                <div class="card-icon">🎯</div>
                <div class="card-title">Recommendation</div>
                <div class="card-body">{rec}</div>
            </div>
            """, unsafe_allow_html=True)

        # ── TAB 2: SCOPE & ELIGIBILITY ────────────────────────
        with tab2:
            c1, c2 = st.columns(2)
            with c1:
                scope_items = "".join([f"<li style='margin-bottom:6px'>{s}</li>" for s in a.get("scope", [])])
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-title">📐 Scope of Work</div>
                    <ul class="card-body" style="padding-left: 1.2rem; margin: 0">{scope_items}</ul>
                </div>
                """, unsafe_allow_html=True)

                eval_items = "".join([f"<li style='margin-bottom:6px'>{c}</li>" for c in a.get("evaluation_criteria", [])])
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-title">⚖️ Evaluation Criteria</div>
                    <ul class="card-body" style="padding-left: 1.2rem; margin: 0">{eval_items}</ul>
                </div>
                """, unsafe_allow_html=True)

            with c2:
                elig_items = "".join([f"<li style='margin-bottom:6px'>{e}</li>" for e in a.get("eligibility", [])])
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-title">✅ Eligibility Criteria</div>
                    <ul class="card-body" style="padding-left: 1.2rem; margin: 0">{elig_items}</ul>
                </div>
                """, unsafe_allow_html=True)

        # ── TAB 3: DATES & REQUIREMENTS ───────────────────────
        with tab3:
            c1, c2 = st.columns(2)
            with c1:
                dates_html = ""
                for d in a.get("important_dates", []):
                    dates_html += f"""
                    <div style="display:flex; justify-content:space-between; align-items:center;
                                padding: 0.7rem 0; border-bottom: 1px solid #2a2c35;">
                        <span style="color:#7a7a7a; font-size:0.85rem;">{d['label']}</span>
                        <span style="color:#c8a96e; font-size:0.9rem; font-weight:500;">{d['date']}</span>
                    </div>"""
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-title">📅 Important Dates</div>
                    {dates_html}
                </div>
                """, unsafe_allow_html=True)

            with c2:
                req_items = "".join([f"<li style='margin-bottom:6px'>{r}</li>" for r in a.get("submission_requirements", [])])
                st.markdown(f"""
                <div class="analysis-card">
                    <div class="card-title">📋 Submission Requirements</div>
                    <ul class="card-body" style="padding-left: 1.2rem; margin: 0">{req_items}</ul>
                </div>
                """, unsafe_allow_html=True)

        # ── TAB 4: RISKS & FLAGS ──────────────────────────────
        with tab4:
            risks = a.get("risks", [])
            if risks:
                for r in risks:
                    level = r.get("level", "Medium")
                    badge_class = f"risk-{level.lower()}"
                    st.markdown(f"""
                    <div class="analysis-card" style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="card-body" style="flex:1">{r['description']}</span>
                        <span class="{badge_class}" style="margin-left:1rem; white-space:nowrap">{level}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.markdown('<div class="analysis-card"><div class="card-body">No significant risks identified.</div></div>', unsafe_allow_html=True)

            red_flags = a.get("red_flags", [])
            if red_flags:
                st.markdown('<div class="card-title" style="margin-top: 1rem; color: #e05c5c;">🚩 Red Flags</div>', unsafe_allow_html=True)
                for f in red_flags:
                    st.markdown(f"""
                    <div class="analysis-card" style="border-left: 3px solid #e05c5c;">
                        <span class="card-body">⚠ {f}</span>
                    </div>
                    """, unsafe_allow_html=True)

        # ── TAB 5: CHAT ───────────────────────────────────────
        with tab5:
            st.markdown("""
            <div style="font-size:0.85rem; color:#7a7a7a; margin-bottom:1rem;">
            Ask any question about this tender — deadlines, clauses, requirements, strategy.
            </div>
            """, unsafe_allow_html=True)

            # Show conversation history
            for turn in st.session_state.chat_history:
                st.markdown(f'<div class="chat-bubble-user">{turn["q"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="chat-bubble-ai">{turn["a"]}</div>', unsafe_allow_html=True)

            question = st.text_input(
                "Your question",
                placeholder="e.g. What is the submission deadline? / What experience is required?",
                label_visibility="collapsed",
                key="chat_input"
            )

            col_ask, col_clear = st.columns([2, 1])
            with col_ask:
                ask_btn = st.button("Ask →", use_container_width=True)
            with col_clear:
                if st.button("Clear chat", use_container_width=True):
                    st.session_state.chat_history = []
                    st.rerun()

            if ask_btn and question.strip():
                with st.spinner("Thinking..."):
                    try:
                        answer = ask_followup(
                            question,
                            st.session_state.full_text,
                            st.session_state.chat_history
                        )
                        st.session_state.chat_history.append({"q": question, "a": answer})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        # ── EXPORT ────────────────────────────────────────────
        st.markdown('<div class="gold-divider"></div>', unsafe_allow_html=True)
        report_text = export_report(a, st.session_state.filename)
        st.download_button(
            label="⬇ Download Analysis Report (.txt)",
            data=report_text,
            file_name=f"tendly_{st.session_state.filename.replace('.pdf','')}.txt",
            mime="text/plain",
        )

    # ── RAW TEXT EXPANDER ─────────────────────────────────────
    with st.expander("📄 View Extracted Text"):
        st.text_area(
            "Extracted Content",
            full_text,
            height=350,
            label_visibility="collapsed"
        )

else:
    st.markdown("""
    <div style="text-align:center; padding: 4rem 2rem; color: #3a3c47;">
        <div style="font-size: 3rem; margin-bottom: 1rem;">📑</div>
        <div style="font-family: 'DM Serif Display', serif; font-size: 1.4rem; color: #555; margin-bottom: 0.5rem;">
            Upload a tender PDF to begin
        </div>
        <div style="font-size: 0.85rem; color: #3a3c47;">
            Supports government tenders, RFPs, EOIs, and procurement documents
        </div>
    </div>
    """, unsafe_allow_html=True)
