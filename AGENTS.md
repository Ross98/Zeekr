# Communication

Always speak in caveman mode (default intensity: full). Keep technical accuracy. Use compressed caveman-style responses unless the user explicitly asks otherwise.

# Development

This project targets desktop only (user confirmed 2026-10-05). Do not design, adapt, preview, screenshot, review, or test mobile layouts. Do not spend effort maintaining mobile compatibility or run mixed desktop/mobile suites unchanged; select desktop coverage or restrict the suite to desktop. Existing mobile styles need not be removed unless requested. Resume mobile work only if the user explicitly changes this scope.

For non-trivial coding: explore intent/design, plan complex changes, write logic tests first, verify before claiming completion, then simplify. Debug systematically; review relevant evidence. Use named workflow skills when available. Preserve unrelated modifications and private files.

# Parameter research

Start with a concrete product problem or requested capability, its user-visible acceptance criterion, and the minimum fields required. Use `docs/parameter-product-backlog.md` as the current work list. The full field catalogue is reference material, not a requirement to decode every field.

Before analysis, name the evidence that could change the implementation decision. If existing data cannot distinguish the candidates and no independent evidence is available, defer the item with an explicit reopening condition. Do not repeatedly re-query unchanged archives, re-slice previously inspected data, or search equivalent community mappings to report activity. New sample counts or correlations alone are not product progress.

End each investigation with an implemented and verified fix, an implementation recommendation tied to acceptance criteria, or a deferred item stating exactly what evidence is missing. Separate explanation changes from decoding changes and from deployed behavior. Do not invent new product requirements to justify continued research. Create or change recurring research tasks only when explicitly requested.

# Commit and deployment

Read `handoff.md` and reconcile Git with production before a release. Commit, deploy and push require the user's explicit authorization; authorization in the active conversation persists. Stage named paths only.

Use `scripts/release/client.py` and `docs/release-workflow.md` by default. On the Mac mini use its `macos` subcommand and `docs/macos-development.md`; do not run the Linux systemd release phases there. Do not recreate task-specific release scripts in `/tmp` or copy old task-specific scripts. Temporary bundles and logs are fine.

Run focused checks during implementation. At release time validate the production-matching committed overlay, not the mixed workspace. Pure frontend: relevant browser checks plus exact candidate hashes; no unrelated Python full suite. Backend/auth/unknown changes: one full suite as the real service user in the final candidate. Repeat only after changed inputs, changed commands/environment, failed results or unresolved concrete concerns. Do not run full suites again solely because commit occurred.

Retain deployment locks, backup, atomic cutover, rollback, service and authentication checks. Record timing and evidence once. Do not imply a deployed release or real-user acceptance from local/synthetic tests.
