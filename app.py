#!/usr/bin/env python3
"""Loan Processing Pipeline Tracker — Single-file Flask app."""

import json, os, re, glob, uuid, time
from datetime import datetime, date, timedelta
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, redirect, url_for

app = Flask(__name__)

DATA_DIR = Path(os.path.expanduser("~/clawd/projects/loan-tracker/data"))
DATA_FILE = DATA_DIR / "loans.json"
BORROWERS_DIR = Path(os.path.expanduser("~/clawd/intake/borrowers"))

STAGES = [
    "Application", "Processing", "Underwriting",
    "Conditional Approval", "Clear to Close", "Closing", "Funded"
]

STAGE_CHECKLISTS = {
    "Application": [
        "Initial application (1003) completed",
        "Credit report pulled",
        "Borrower ID verified",
        "Disclosures sent (LE, intent to proceed)",
        "Preapproval letter issued",
        "Loan program selected",
    ],
    "Processing": [
        "Income docs collected (paystubs, W2s, tax returns)",
        "Asset docs collected (bank statements)",
        "VOE ordered / completed",
        "Credit report reviewed",
        "Appraisal ordered",
        "Title ordered",
        "Insurance quote obtained",
        "HOI binder requested",
        "Survey ordered (if needed)",
        "Flood cert ordered",
    ],
    "Underwriting": [
        "File submitted to underwriting",
        "AUS findings reviewed (DU/LP)",
        "Income calculated & documented",
        "Assets verified",
        "Appraisal reviewed & approved",
        "Title commitment reviewed",
        "Insurance verified",
    ],
    "Conditional Approval": [
        "Conditions list received",
        "Prior-to-doc conditions cleared",
        "Prior-to-closing conditions cleared",
        "Updated docs collected (if needed)",
        "Re-submitted to UW for final review",
    ],
    "Clear to Close": [
        "Final approval received",
        "Closing Disclosure prepared",
        "CD sent to borrower (3-day wait)",
        "Wire instructions confirmed",
        "Closing scheduled",
        "Final walkthrough confirmed",
    ],
    "Closing": [
        "Docs sent to title/attorney",
        "Borrower signed",
        "Funds wired",
        "Note & deed recorded",
    ],
    "Funded": [
        "Funding confirmed",
        "Post-closing audit complete",
        "File archived",
    ],
}

FHA_EXTRAS = {
    "Application": ["FHA case number assigned", "UFMIP calculated"],
    "Processing": ["DPA program setup (if applicable)", "FHA appraisal requirements noted", "HOA certification (if condo)"],
    "Underwriting": ["FHA-specific AUS (TOTAL Scorecard) reviewed"],
}

CONV_EXTRAS = {
    "Processing": ["PMI quote obtained (if <20% down)", "Gift letter collected (if applicable)", "Reserve verification"],
}

# ─── Data helpers ───

def load_loans():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_loans(loans):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(loans, f, indent=2, default=str)

def build_checklist(stage, loan_type="conventional"):
    items = list(STAGE_CHECKLISTS.get(stage, []))
    if loan_type == "fha":
        items.extend(FHA_EXTRAS.get(stage, []))
    else:
        items.extend(CONV_EXTRAS.get(stage, []))
    return {item: {"done": False, "completed_at": None, "completed_by": None} for item in items}

def build_all_checklists(loan_type="conventional"):
    return {stage: build_checklist(stage, loan_type) for stage in STAGES}

def make_loan(name, **kwargs):
    loan_type = kwargs.get("loan_type", "conventional")
    return {
        "id": kwargs.get("id", str(uuid.uuid4())[:8]),
        "borrower": name,
        "co_borrower": kwargs.get("co_borrower", ""),
        "property_address": kwargs.get("property_address", ""),
        "loan_amount": kwargs.get("loan_amount", ""),
        "loan_type": loan_type,
        "stage": kwargs.get("stage", "Application"),
        "dates": {
            "contract_date": kwargs.get("contract_date", ""),
            "lock_expiration": kwargs.get("lock_expiration", ""),
            "appraisal_deadline": kwargs.get("appraisal_deadline", ""),
            "uw_submission_deadline": kwargs.get("uw_submission_deadline", ""),
            "loan_approval_deadline": kwargs.get("loan_approval_deadline", ""),
            "closing_date": kwargs.get("closing_date", ""),
        },
        "checklists": build_all_checklists(loan_type),
        "notes": kwargs.get("notes", ""),
        "created_at": datetime.now().isoformat(),
        "milestones": [],
    }

def seed_borrower_files():
    """Read borrower .md files and seed loans if not already present."""
    loans = load_loans()
    if not BORROWERS_DIR.exists():
        return loans
    existing_names = {l["borrower"].lower() for l in loans.values()}
    for md in BORROWERS_DIR.glob("*.md"):
        try:
            text = md.read_text()
        except Exception:
            continue
        # Parse basic fields from markdown
        name = md.stem.replace("-", " ").replace("_", " ").title()
        if name.lower() in existing_names:
            continue
        kwargs = {}
        for line in text.split("\n"):
            ll = line.lower()
            if "loan amount" in ll or "purchase price" in ll:
                nums = re.findall(r'[\$]?([\d,]+)', line)
                if nums:
                    kwargs["loan_amount"] = nums[0].replace(",", "")
            if "property" in ll or "address" in ll:
                val = line.split(":", 1)[-1].strip() if ":" in line else ""
                if val:
                    kwargs["property_address"] = val
            if "fha" in ll:
                kwargs["loan_type"] = "fha"
            if "closing" in ll and "date" in ll:
                dates = re.findall(r'\d{1,2}/\d{1,2}/\d{2,4}', line)
                if dates:
                    kwargs["closing_date"] = dates[0]
        loan = make_loan(name, **kwargs)
        loans[loan["id"]] = loan
        existing_names.add(name.lower())
    save_loans(loans)
    return loans

def seed_hardcoded():
    """Seed the two known urgent files if not present."""
    loans = load_loans()
    existing_names = {l["borrower"].lower() for l in loans.values()}

    if "david fuste" not in existing_names:
        loan = make_loan("David Fuste", stage="Application",
                         notes="Just went under contract — needs fast processing")
        loans[loan["id"]] = loan

    if "ileana rodriguez" not in existing_names:
        loan = make_loan("Ileana Rodriguez", co_borrower="Katia Cabrera",
                         loan_amount="308000", loan_type="fha",
                         stage="Processing",
                         loan_approval_deadline="3/4/2026",
                         closing_date="3/13/2026",
                         notes="FHA $308K, loan approval deadline 3/4/2026, closing 3/13/2026")
        loans[loan["id"]] = loan

    save_loans(loans)
    return loans

def days_until(date_str):
    if not date_str:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            d = datetime.strptime(date_str, fmt).date()
            return (d - date.today()).days
        except ValueError:
            continue
    return None

def deadline_class(days):
    if days is None:
        return ""
    if days < 0:
        return "overdue"
    if days <= 3:
        return "red"
    if days <= 7:
        return "yellow"
    return "green"

# ─── Startup ───

with app.app_context():
    seed_borrower_files()
    seed_hardcoded()

# ─── HTML Template ───

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loan Pipeline Tracker</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}
.header h1{font-size:1.3rem;color:#f0f6fc}
.header .links a{margin-left:16px;font-size:.9rem}
.container{padding:16px;max-width:1600px;margin:0 auto}
/* Kanban */
.kanban{display:flex;gap:12px;overflow-x:auto;padding-bottom:12px}
.kanban-col{min-width:220px;flex:1;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px}
.kanban-col h3{font-size:.85rem;color:#8b949e;text-transform:uppercase;margin-bottom:8px;text-align:center}
.kanban-card{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;margin-bottom:8px;cursor:pointer;transition:border-color .2s}
.kanban-card:hover{border-color:#58a6ff}
.kanban-card .name{font-weight:600;color:#f0f6fc;font-size:.95rem}
.kanban-card .meta{font-size:.75rem;color:#8b949e;margin-top:4px}
.kanban-card .deadline-badges{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px}
.badge{font-size:.7rem;padding:2px 6px;border-radius:4px;font-weight:600}
.badge.green{background:#1a4d2e;color:#3fb950}
.badge.yellow{background:#4d3800;color:#d29922}
.badge.red{background:#4d0000;color:#f85149}
.badge.overdue{background:#f85149;color:#fff;animation:flash 1s infinite}
@keyframes flash{0%,100%{opacity:1}50%{opacity:.4}}
/* Detail page */
.loan-detail{max-width:900px;margin:0 auto}
.loan-header{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
.loan-header h2{color:#f0f6fc;margin-bottom:8px}
.info-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
.info-item{font-size:.85rem}.info-item .label{color:#8b949e}.info-item .val{color:#c9d1d9;font-weight:600}
.dates-section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
.dates-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.date-card{text-align:center;padding:8px;border-radius:6px;border:1px solid #30363d}
.date-card .dlabel{font-size:.75rem;color:#8b949e}
.date-card .dval{font-size:1rem;font-weight:700;margin:4px 0}
.date-card .countdown{font-size:.8rem;font-weight:600}
.date-card.green .countdown{color:#3fb950}
.date-card.yellow .countdown{color:#d29922}
.date-card.red .countdown{color:#f85149}
.date-card.overdue .countdown{color:#f85149;animation:flash 1s infinite}
.checklist-section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
.checklist-section h3{color:#f0f6fc;margin-bottom:10px;font-size:1rem}
.stage-tab{display:inline-block;padding:6px 12px;margin:0 4px 8px 0;border-radius:4px;font-size:.8rem;cursor:pointer;background:#21262d;color:#8b949e;border:1px solid #30363d}
.stage-tab.active{background:#1f6feb;color:#fff;border-color:#1f6feb}
.check-item{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #21262d;font-size:.85rem}
.check-item:last-child{border-bottom:none}
.check-item input[type=checkbox]{accent-color:#3fb950;width:16px;height:16px}
.check-item .done-info{color:#3fb950;font-size:.7rem;margin-left:auto}
.btn{display:inline-block;padding:6px 14px;border-radius:6px;font-size:.85rem;cursor:pointer;border:1px solid #30363d;background:#21262d;color:#c9d1d9;transition:background .2s}
.btn:hover{background:#30363d}
.btn-primary{background:#1f6feb;color:#fff;border-color:#1f6feb}
.btn-primary:hover{background:#1a5ccf}
.btn-danger{background:#4d0000;color:#f85149;border-color:#f85149}
select,input[type=text],input[type=date],textarea{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:4px;font-size:.85rem;width:100%}
.form-group{margin-bottom:12px}
.form-group label{display:block;font-size:.8rem;color:#8b949e;margin-bottom:4px}
.stage-select{display:flex;gap:8px;align-items:center;margin-bottom:12px}
.notes-section textarea{min-height:80px}
/* Digest */
.digest{max-width:800px;margin:0 auto}
.digest-item{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px;margin-bottom:8px}
.digest-item .urgency{font-weight:700}
/* Mobile */
@media(max-width:768px){.kanban{flex-direction:column}.kanban-col{min-width:100%}}
</style>
</head>
<body>
<div class="header">
<h1>🏠 Loan Pipeline Tracker</h1>
<div class="links">
<a href="/">Pipeline</a>
<a href="/add">+ New Loan</a>
<a href="/digest">Digest</a>
</div>
</div>
<div class="container">
{% block content %}{% endblock %}
</div>
</body>
</html>"""

KANBAN_PAGE = """{% extends "base" %}{% block content %}
<div class="kanban">
{% for stage in stages %}
<div class="kanban-col">
<h3>{{ stage }} ({{ stage_loans[stage]|length }})</h3>
{% for loan in stage_loans[stage] %}
<a href="/loan/{{ loan.id }}" style="text-decoration:none;color:inherit">
<div class="kanban-card">
<div class="name">{{ loan.borrower }}{% if loan.co_borrower %} & {{ loan.co_borrower }}{% endif %}</div>
<div class="meta">
{% if loan.loan_amount %}${{ "{:,.0f}".format(loan.loan_amount|float) }}{% endif %}
{{ loan.loan_type|upper }}
</div>
{% if loan.property_address %}<div class="meta">{{ loan.property_address }}</div>{% endif %}
<div class="deadline-badges">
{% for dname, dval in loan.dates.items() %}
{% if dval %}
{% set days = days_until(dval) %}
{% if days is not none %}
<span class="badge {{ deadline_class(days) }}">{{ dname.replace('_',' ').title() }}: {{ days }}d</span>
{% endif %}
{% endif %}
{% endfor %}
</div>
</div>
</a>
{% endfor %}
</div>
{% endfor %}
</div>
{% endblock %}"""

LOAN_PAGE = """{% extends "base" %}{% block content %}
<div class="loan-detail">
<div class="loan-header">
<div style="display:flex;justify-content:space-between;align-items:start;flex-wrap:wrap;gap:8px">
<div>
<h2>{{ loan.borrower }}{% if loan.co_borrower %} & {{ loan.co_borrower }}{% endif %}</h2>
<div class="info-grid" style="margin-top:8px">
<div class="info-item"><span class="label">Loan Type:</span> <span class="val">{{ loan.loan_type|upper }}</span></div>
<div class="info-item"><span class="label">Amount:</span> <span class="val">${{ "{:,.0f}".format(loan.loan_amount|float) if loan.loan_amount else 'TBD' }}</span></div>
<div class="info-item"><span class="label">Property:</span> <span class="val">{{ loan.property_address or 'TBD' }}</span></div>
<div class="info-item"><span class="label">Stage:</span> <span class="val">{{ loan.stage }}</span></div>
</div>
</div>
<div style="display:flex;gap:8px;flex-wrap:wrap">
<a href="/loan/{{ loan.id }}/edit" class="btn">Edit</a>
<form method="post" action="/loan/{{ loan.id }}/delete" style="display:inline" onsubmit="return confirm('Delete this loan?')">
<button class="btn btn-danger" type="submit">Delete</button>
</form>
</div>
</div>
{% if loan.notes %}<div style="margin-top:8px;font-size:.85rem;color:#d29922">📌 {{ loan.notes }}</div>{% endif %}
</div>
<!-- Stage Move -->
<div class="stage-select">
<span style="font-size:.85rem;color:#8b949e">Move to:</span>
{% for s in stages %}
<form method="post" action="/loan/{{ loan.id }}/stage" style="display:inline">
<input type="hidden" name="stage" value="{{ s }}">
<button class="btn {% if s == loan.stage %}btn-primary{% endif %}" type="submit" style="font-size:.75rem;padding:4px 8px">{{ s }}</button>
</form>
{% endfor %}
</div>
<!-- Dates -->
<div class="dates-section">
<h3 style="margin-bottom:10px;color:#f0f6fc">📅 Deadlines</h3>
<div class="dates-grid">
{% for dname, dval in loan.dates.items() %}
{% set days = days_until(dval) if dval else None %}
<div class="date-card {{ deadline_class(days) if days is not none else '' }}">
<div class="dlabel">{{ dname.replace('_',' ').title() }}</div>
<div class="dval">{{ dval or '—' }}</div>
{% if days is not none %}<div class="countdown">{{ days }} day{{ 's' if days != 1 else '' }} {{ 'left' if days >= 0 else 'OVERDUE' }}</div>{% endif %}
</div>
{% endfor %}
</div>
</div>
<!-- Checklists -->
<div class="checklist-section">
<h3>✅ Checklists</h3>
<div id="stage-tabs">
{% for s in stages %}
<span class="stage-tab {% if s == loan.stage %}active{% endif %}" onclick="showStage('{{ s }}',this)">{{ s }}</span>
{% endfor %}
</div>
{% for s in stages %}
<div class="stage-checklist" id="cl-{{ s|replace(' ','-') }}" style="{% if s != loan.stage %}display:none{% endif %}">
<form method="post" action="/loan/{{ loan.id }}/checklist">
<input type="hidden" name="stage" value="{{ s }}">
{% for item, info in loan.checklists.get(s, {}).items() %}
<div class="check-item">
<input type="checkbox" name="items" value="{{ item }}" {% if info.done %}checked{% endif %}>
<span{% if info.done %} style="text-decoration:line-through;color:#8b949e"{% endif %}>{{ item }}</span>
{% if info.done and info.completed_at %}
<span class="done-info">✓ {{ info.completed_at[:10] }}{% if info.completed_by %} by {{ info.completed_by }}{% endif %}</span>
{% endif %}
</div>
{% endfor %}
<div style="margin-top:10px;display:flex;gap:8px;align-items:center">
<input type="text" name="completed_by" placeholder="Your name" style="width:150px">
<button class="btn btn-primary" type="submit">Save Checklist</button>
</div>
</form>
</div>
{% endfor %}
</div>
<!-- Milestones -->
{% if loan.milestones %}
<div class="checklist-section">
<h3>📋 Milestone Log</h3>
{% for m in loan.milestones[-20:]|reverse %}
<div style="font-size:.8rem;padding:4px 0;border-bottom:1px solid #21262d;color:#8b949e">
<span style="color:#c9d1d9">{{ m.action }}</span> — {{ m.timestamp[:16] }}{% if m.by %} by {{ m.by }}{% endif %}
</div>
{% endfor %}
</div>
{% endif %}
</div>
<script>
function showStage(s,el){
document.querySelectorAll('.stage-checklist').forEach(e=>e.style.display='none');
document.querySelectorAll('.stage-tab').forEach(e=>e.classList.remove('active'));
document.getElementById('cl-'+s.replace(/ /g,'-')).style.display='block';
el.classList.add('active');
}
</script>
{% endblock %}"""

EDIT_PAGE = """{% extends "base" %}{% block content %}
<div class="loan-detail">
<h2 style="color:#f0f6fc;margin-bottom:16px">{% if loan %}Edit: {{ loan.borrower }}{% else %}Add New Loan{% endif %}</h2>
<form method="post">
<div class="info-grid" style="gap:12px">
<div class="form-group"><label>Borrower Name</label><input type="text" name="borrower" value="{{ loan.borrower if loan else '' }}" required></div>
<div class="form-group"><label>Co-Borrower</label><input type="text" name="co_borrower" value="{{ loan.co_borrower if loan else '' }}"></div>
<div class="form-group"><label>Property Address</label><input type="text" name="property_address" value="{{ loan.property_address if loan else '' }}"></div>
<div class="form-group"><label>Loan Amount</label><input type="text" name="loan_amount" value="{{ loan.loan_amount if loan else '' }}"></div>
<div class="form-group"><label>Loan Type</label>
<select name="loan_type"><option value="conventional" {% if loan and loan.loan_type=='conventional' %}selected{% endif %}>Conventional</option><option value="fha" {% if loan and loan.loan_type=='fha' %}selected{% endif %}>FHA</option><option value="va" {% if loan and loan.loan_type=='va' %}selected{% endif %}>VA</option><option value="usda" {% if loan and loan.loan_type=='usda' %}selected{% endif %}>USDA</option><option value="non-qm" {% if loan and loan.loan_type=='non-qm' %}selected{% endif %}>Non-QM</option></select></div>
<div class="form-group"><label>Stage</label>
<select name="stage">{% for s in stages %}<option value="{{ s }}" {% if loan and loan.stage==s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></div>
<div class="form-group"><label>Contract Date</label><input type="text" name="contract_date" value="{{ loan.dates.contract_date if loan else '' }}" placeholder="MM/DD/YYYY"></div>
<div class="form-group"><label>Lock Expiration</label><input type="text" name="lock_expiration" value="{{ loan.dates.lock_expiration if loan else '' }}" placeholder="MM/DD/YYYY"></div>
<div class="form-group"><label>Appraisal Deadline</label><input type="text" name="appraisal_deadline" value="{{ loan.dates.appraisal_deadline if loan else '' }}" placeholder="MM/DD/YYYY"></div>
<div class="form-group"><label>UW Submission Deadline</label><input type="text" name="uw_submission_deadline" value="{{ loan.dates.uw_submission_deadline if loan else '' }}" placeholder="MM/DD/YYYY"></div>
<div class="form-group"><label>Loan Approval Deadline</label><input type="text" name="loan_approval_deadline" value="{{ loan.dates.loan_approval_deadline if loan else '' }}" placeholder="MM/DD/YYYY"></div>
<div class="form-group"><label>Closing Date</label><input type="text" name="closing_date" value="{{ loan.dates.closing_date if loan else '' }}" placeholder="MM/DD/YYYY"></div>
</div>
<div class="form-group notes-section"><label>Notes</label><textarea name="notes">{{ loan.notes if loan else '' }}</textarea></div>
<div style="margin-top:12px;display:flex;gap:8px">
<button class="btn btn-primary" type="submit">Save</button>
<a href="{% if loan %}/loan/{{ loan.id }}{% else %}/{% endif %}" class="btn">Cancel</a>
</div>
</form>
</div>
{% endblock %}"""

DIGEST_PAGE = """{% extends "base" %}{% block content %}
<div class="digest">
<h2 style="color:#f0f6fc;margin-bottom:16px">📋 Daily Digest — {{ today }}</h2>
{% if not items %}
<p style="color:#8b949e">No urgent action items today. All clear! 🎉</p>
{% endif %}
{% for item in items %}
<div class="digest-item">
<div style="display:flex;justify-content:space-between;align-items:center">
<span class="urgency" style="color:{% if item.urgency == 'OVERDUE' %}#f85149{% elif item.urgency == 'CRITICAL' %}#f85149{% elif item.urgency == 'URGENT' %}#d29922{% else %}#3fb950{% endif %}">{{ item.urgency }}</span>
<span style="font-size:.8rem;color:#8b949e">{{ item.days }} days</span>
</div>
<div style="font-weight:600;color:#f0f6fc;margin:4px 0">{{ item.borrower }}</div>
<div style="font-size:.85rem;color:#c9d1d9">{{ item.message }}</div>
</div>
{% endfor %}
</div>
{% endblock %}"""

# ─── Routes ───

@app.route("/")
def index():
    loans = load_loans()
    stage_loans = {s: [] for s in STAGES}
    for loan in loans.values():
        s = loan.get("stage", "Application")
        if s in stage_loans:
            stage_loans[s].append(loan)
    return render_template_string(KANBAN_PAGE, stages=STAGES, stage_loans=stage_loans,
                                  days_until=days_until, deadline_class=deadline_class)

@app.route("/loan/<lid>")
def loan_detail(lid):
    loans = load_loans()
    loan = loans.get(lid)
    if not loan:
        return redirect("/")
    return render_template_string(LOAN_PAGE, loan=loan, stages=STAGES,
                                  days_until=days_until, deadline_class=deadline_class)

@app.route("/loan/<lid>/stage", methods=["POST"])
def loan_stage(lid):
    loans = load_loans()
    if lid in loans:
        new_stage = request.form.get("stage", loans[lid]["stage"])
        old_stage = loans[lid]["stage"]
        if new_stage != old_stage:
            loans[lid]["stage"] = new_stage
            loans[lid]["milestones"].append({
                "action": f"Moved from {old_stage} → {new_stage}",
                "timestamp": datetime.now().isoformat(),
                "by": ""
            })
            save_loans(loans)
    return redirect(f"/loan/{lid}")

@app.route("/loan/<lid>/checklist", methods=["POST"])
def loan_checklist(lid):
    loans = load_loans()
    if lid not in loans:
        return redirect("/")
    stage = request.form.get("stage", "")
    checked = set(request.form.getlist("items"))
    by = request.form.get("completed_by", "").strip()
    now = datetime.now().isoformat()
    cl = loans[lid]["checklists"].get(stage, {})
    for item, info in cl.items():
        was_done = info.get("done", False)
        is_done = item in checked
        if is_done and not was_done:
            info["done"] = True
            info["completed_at"] = now
            info["completed_by"] = by
            loans[lid]["milestones"].append({"action": f"[{stage}] ✓ {item}", "timestamp": now, "by": by})
        elif not is_done and was_done:
            info["done"] = False
            info["completed_at"] = None
            info["completed_by"] = None
            loans[lid]["milestones"].append({"action": f"[{stage}] ✗ Unchecked: {item}", "timestamp": now, "by": by})
    save_loans(loans)
    return redirect(f"/loan/{lid}")

@app.route("/loan/<lid>/edit", methods=["GET", "POST"])
def loan_edit(lid):
    loans = load_loans()
    loan = loans.get(lid)
    if not loan:
        return redirect("/")
    if request.method == "POST":
        loan["borrower"] = request.form.get("borrower", loan["borrower"])
        loan["co_borrower"] = request.form.get("co_borrower", "")
        loan["property_address"] = request.form.get("property_address", "")
        loan["loan_amount"] = request.form.get("loan_amount", "")
        old_type = loan["loan_type"]
        loan["loan_type"] = request.form.get("loan_type", "conventional")
        loan["stage"] = request.form.get("stage", loan["stage"])
        loan["notes"] = request.form.get("notes", "")
        for dk in loan["dates"]:
            loan["dates"][dk] = request.form.get(dk, "")
        # Rebuild checklists if loan type changed
        if loan["loan_type"] != old_type:
            loan["checklists"] = build_all_checklists(loan["loan_type"])
        save_loans(loans)
        return redirect(f"/loan/{lid}")
    return render_template_string(EDIT_PAGE, loan=loan, stages=STAGES)

@app.route("/loan/<lid>/delete", methods=["POST"])
def loan_delete(lid):
    loans = load_loans()
    loans.pop(lid, None)
    save_loans(loans)
    return redirect("/")

@app.route("/add", methods=["GET", "POST"])
def add_loan():
    if request.method == "POST":
        loans = load_loans()
        lt = request.form.get("loan_type", "conventional")
        loan = make_loan(
            request.form.get("borrower", "Unknown"),
            co_borrower=request.form.get("co_borrower", ""),
            property_address=request.form.get("property_address", ""),
            loan_amount=request.form.get("loan_amount", ""),
            loan_type=lt,
            stage=request.form.get("stage", "Application"),
            contract_date=request.form.get("contract_date", ""),
            lock_expiration=request.form.get("lock_expiration", ""),
            appraisal_deadline=request.form.get("appraisal_deadline", ""),
            uw_submission_deadline=request.form.get("uw_submission_deadline", ""),
            loan_approval_deadline=request.form.get("loan_approval_deadline", ""),
            closing_date=request.form.get("closing_date", ""),
            notes=request.form.get("notes", ""),
        )
        loans[loan["id"]] = loan
        save_loans(loans)
        return redirect(f"/loan/{loan['id']}")
    return render_template_string(EDIT_PAGE, loan=None, stages=STAGES)

@app.route("/digest")
def digest():
    loans = load_loans()
    items = []
    for loan in loans.values():
        if loan["stage"] == "Funded":
            continue
        for dname, dval in loan["dates"].items():
            d = days_until(dval)
            if d is None:
                continue
            if d < 0:
                urgency = "OVERDUE"
            elif d <= 3:
                urgency = "CRITICAL"
            elif d <= 7:
                urgency = "URGENT"
            else:
                urgency = "UPCOMING"
            items.append({
                "borrower": loan["borrower"] + (f" & {loan['co_borrower']}" if loan.get("co_borrower") else ""),
                "message": f"{dname.replace('_',' ').title()}: {dval} ({d} days {'left' if d >= 0 else 'overdue'})",
                "urgency": urgency,
                "days": d,
                "sort": d,
            })
        # Incomplete checklist items for current stage
        cl = loan["checklists"].get(loan["stage"], {})
        pending = [item for item, info in cl.items() if not info.get("done")]
        if pending:
            items.append({
                "borrower": loan["borrower"] + (f" & {loan['co_borrower']}" if loan.get("co_borrower") else ""),
                "message": f"[{loan['stage']}] {len(pending)} pending items: {', '.join(pending[:3])}{'...' if len(pending) > 3 else ''}",
                "urgency": "ACTION",
                "days": 999,
                "sort": 999,
            })
    items.sort(key=lambda x: x["sort"])
    return render_template_string(DIGEST_PAGE, items=items, today=date.today().isoformat())

# ─── JSON API ───

@app.route("/api/loans", methods=["GET"])
def api_loans():
    return jsonify(load_loans())

@app.route("/api/loans/<lid>", methods=["GET"])
def api_loan(lid):
    loans = load_loans()
    if lid not in loans:
        return jsonify({"error": "not found"}), 404
    return jsonify(loans[lid])

@app.route("/api/loans", methods=["POST"])
def api_create_loan():
    data = request.json or {}
    loan = make_loan(
        data.get("borrower", "Unknown"),
        **{k: data.get(k, "") for k in ["co_borrower", "property_address", "loan_amount", "loan_type", "stage",
                                          "contract_date", "lock_expiration", "appraisal_deadline",
                                          "uw_submission_deadline", "loan_approval_deadline", "closing_date", "notes"]}
    )
    loans = load_loans()
    loans[loan["id"]] = loan
    save_loans(loans)
    return jsonify(loan), 201

@app.route("/api/loans/<lid>", methods=["PUT"])
def api_update_loan(lid):
    loans = load_loans()
    if lid not in loans:
        return jsonify({"error": "not found"}), 404
    data = request.json or {}
    loan = loans[lid]
    for k in ["borrower", "co_borrower", "property_address", "loan_amount", "loan_type", "stage", "notes"]:
        if k in data:
            loan[k] = data[k]
    if "dates" in data:
        loan["dates"].update(data["dates"])
    save_loans(loans)
    return jsonify(loan)

@app.route("/api/loans/<lid>", methods=["DELETE"])
def api_delete_loan(lid):
    loans = load_loans()
    loans.pop(lid, None)
    save_loans(loans)
    return jsonify({"ok": True})

@app.route("/api/digest", methods=["GET"])
def api_digest():
    # Reuse digest logic
    loans = load_loans()
    items = []
    for loan in loans.values():
        if loan["stage"] == "Funded":
            continue
        for dname, dval in loan["dates"].items():
            d = days_until(dval)
            if d is None:
                continue
            items.append({"borrower": loan["borrower"], "deadline": dname, "date": dval, "days": d})
    items.sort(key=lambda x: x["days"])
    return jsonify(items)

# ─── Jinja base template ───

@app.context_processor
def inject_base():
    return {}

# Register base template
app.jinja_env.globals["base"] = TEMPLATE
from jinja2 import DictLoader
app.jinja_loader = type('Loader', (), {
    'get_source': lambda self, env, name: (TEMPLATE if name == 'base' else '', name, lambda: True),
    'list_templates': lambda self: ['base'],
})()

# Proper template loader that handles extends
class InlineLoader:
    def get_source(self, environment, template):
        if template == "base":
            return TEMPLATE, "base", lambda: True
        raise Exception(f"Template {template} not found")
    def list_templates(self):
        return ["base"]

app.jinja_loader = InlineLoader()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8087, debug=False)
