# Loan Pipeline Tracker

## Overview
Kanban-style mortgage loan pipeline tracker with deadline management, per-stage checklists, and milestone logging.

## Tech
- Python 3 / Flask, single-file app (app.py)
- JSON file storage (data/loans.json)
- Dark theme, mobile-friendly
- Port 8087, systemd: loan-tracker.service

## Features
- 7-stage Kanban board (Application → Funded)
- Per-loan checklists with FHA/Conventional extras
- Deadline countdown with color coding
- Auto-seed from ~/clawd/intake/borrowers/*.md
- Daily digest (/digest)
- Full JSON API (/api/*)
- Milestone logging

## API
- GET /api/loans — all loans
- GET /api/loans/<id> — single loan
- POST /api/loans — create loan (JSON body)
- PUT /api/loans/<id> — update loan
- DELETE /api/loans/<id> — delete loan
- GET /api/digest — deadline digest as JSON
