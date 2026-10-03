# Contributing

Use English for new public documentation, release notes, issue templates and
interface wording. Maintain Simplified Chinese support alongside English.
See [Localization](docs/LOCALIZATION.md) for the current catalog/build workflow.

Before submitting changes:

- Preserve player names, IDs, paths and saved game data across languages.
- Keep write operations copy-based and fail closed on ambiguous save structures.
- Regenerate language assets after frontend changes, then run
  `python -m pytest -q tests`.
- Test both languages at desktop and narrow window sizes. Check errors, loading
  states, confirmations and exported content, not just the initial page.
- Never commit personal saves, exports, credentials, local configuration,
  generated test artifacts or unrelated experimental projects.
- Keep author credits, the MIT license and third-party licenses intact.

Use focused commits describing the actual change. Report what was tested and
what still requires in-game verification; do not claim tests prove safe operation
for every save or game version.
