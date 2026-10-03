# Approved overview layout

Preserve the current vehicle hero, cached-state semantics, temperature timestamps, tyres, activity, location privacy, and existing navigation. Move temperature immediately below the hero. Add today observed distance and actual month charge costs; combine recent ended records with actionable follow-ups. Merge location into activity. End with a 7/30 day observed-distance chart, retaining missing observations.

Use the existing scoped report and ledger APIs; current/previous month report covers the trailing 30 days. Keep amounts, partial distances, unknowns, and zero values distinct. Guard asynchronous results by account/vehicle context and record revisions. Reuse existing trip/charge detail and ledger/place tools, with return-to-overview preserving filtering and scroll.

1. Test aggregate selection and cost/pending semantics first.
2. Build overview module and wire existing detail paths.
3. Reorder current markup and apply responsive theme-aware CSS.
4. Verify synthetic desktop/mobile, contexts, missing data, and navigation; simplify repeated markup/styles.
5. Stage only this scope, test exact staged tree, commit. Copy active production baseline, overlay scope, validate as service user, backup and atomically switch, verify hashes/services/HTTP/feature metadata. No push requested.
