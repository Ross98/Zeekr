# Charge Ledger Edit Entry Implementation Plan

**Goal:** Make editing discoverable directly on collapsed bill rows.
**Architecture:** Keep existing ledger API and draft fields. Add editorOpen state to the existing component and move the editor below the bill list.
**Tech Stack:** Vanilla JavaScript, CSS, Playwright, Python unittest.

- [x] Extend tests/ui_charge_ledger.cjs to assert the editor starts collapsed. Run it and confirm failure before implementation.
- [x] Update zeekr_control/static/charge-ledger.js: add editorOpen=false, show editor only when open, move bill list first, place edit button outside details, close on save/cancel, retain draft on failed save.
- [x] Update zeekr_control/static/insights.css with a flex row for bill disclosure and visible edit button; check narrow layouts.
- [x] Extend browser tests for visible collapsed-row edit, loaded values, cancel, and 1440/390/320px editor layouts.
- [x] Run tests/test_charge_ledger.py and tests/ui_refresh_scroll.cjs. Review synthetic mobile screenshots and git diff --check.
- [x] Confirm final extended tests/ui_charge_ledger.cjs result. Leave changes local; deployment and push require separate authorization.
