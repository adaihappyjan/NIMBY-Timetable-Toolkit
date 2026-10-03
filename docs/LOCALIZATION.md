# Localization

English is the default presentation language; Simplified Chinese is supported.
New public documentation and release notes should be English-first, with Chinese
user-facing translations maintained alongside them.

## Resources and build

- `web/locales/en.json`: source-message catalog.
- `web/locales/en.overrides.json`: reviewed terminology and prose.
- `web/locales/en/`: generated English HTML/JavaScript assets, committed for offline use.
- `web/locales/messages.en.json`: generated full-message diagnostic templates.
- `web/locale.js`: confirmed language switching and saved preference.
- `toolkit_locale.py`: presentation-only API localization.

Existing Chinese source messages remain stable lookup keys. They are not renamed
inside binary-save code. New untranslated messages must be added to the catalog
before release. Generated assets contain a source-hash manifest; stale assets are
rejected instead of silently serving outdated logic.

The build uses Acorn to parse JavaScript, never a search-and-replace over executable
source. Provide Acorn on `NODE_PATH`, then run:

```powershell
npm install --prefix dist/locale-build acorn
$env:NODE_PATH = (Resolve-Path dist/locale-build/node_modules).Path
python scripts/build_locales.py
python -m pytest -q tests
```

The release does not need Acorn, translation services or translation models.
Translation resources are bundled and used offline.

## Data boundaries

Translate application-owned literals and human-readable display attributes only.
Do not translate expression results, names, paths, IDs, object keys, regular
expressions, comparison values or data-classifier strings. API localization is
limited to presentation fields; template captures preserve interpolated data.
Unknown diagnostics retain their original text rather than guessing at user data.
Request English API messages with `X-NIMBY-Language: en`; legacy API clients retain
the original messages unless they opt in.

`language` in user settings stores `en` or `zh-CN`. HTML pins its asset requests to
the same language so another window cannot mix languages mid-load. Switching
requires confirmation and is blocked while a task is visibly running.

## Review checklist

- Use **save**, **timetable**, **headway**, **depot**, **dwell time**, **order** and **blueprint** consistently.
- Preserve numbers, units, placeholders, HTML structure and technical identifiers.
- Keep safety limitations explicit; do not turn estimates into guarantees.
- Test both languages, reload persistence, long labels and narrow windows.
- Test Chinese player names and paths in English mode; they must stay unchanged.
- Do not add experiment directories or local developer configuration to releases.
