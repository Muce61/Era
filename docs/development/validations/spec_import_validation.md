# V1.3.4 Specification Import Validation

Validation date: 2026-07-12  
Result: PASS FOR STAGE GENERATION ONLY

## Inputs and Output

- Input: `/Users/muce/Downloads/V1.3.4_完整交付包.zip`
- Source manual: `docs/spec/system_manual_v1.3.4_final.docx`
- Supporting inputs: `docs/spec/v1.3.4_change_summary.docx`, `docs/spec/v1.3.4_open_issues.docx`, and `docs/spec/v1.3.4_final_revision_record.md`
- Generated searchable manual: `docs/spec/system_manual_v1.3.4_final.md`
- Source DOCX SHA-256: `75469230dc27e4ef530cd9eba176c60fb06dc4e604ca06938bfb1748bc1649fb`
- Generated Markdown SHA-256: `28694530377cdd0c9f6db254fa191b3985b72befc13ef289160f483e0254c893`

## Checks Performed

| Check | Source | Markdown | Result |
| --- | ---: | ---: | --- |
| Body paragraphs | 490 | structurally converted | PASS |
| Headings | 125 | 125 present | PASS |
| Tables | 30 | 30 | PASS |
| Source-code blocks | 23 | 23 fenced blocks | PASS |
| Extracted paragraph/table text fragments | 3,310 | 3,310 present | PASS |
| Formal rule-registry rows | 32 unique | 32 unique | PASS |
| `INV-*` occurrences | 48 / 41 unique | 48 / 41 unique | PASS |
| `INV-*` range | INV-001…INV-041 | INV-001…INV-041 | PASS |
| Uppercase hyphenated contract/rule/test tokens | 137 unique | 137 unique | PASS |

Status-label occurrence counts matched for `FROZEN` (92), `RESEARCH` (19), `DEPRECATED` (7), and `BLOCKED_BY_FORWARD_VALIDATION` (10). Source `BASELINE` occurs 34 times; Markdown occurs 35 times because the required YAML value `FINAL_BASELINE` adds one metadata occurrence. No source label changed.

The YAML header identifies V1.3.4 as `FINAL_BASELINE`, marks it as implementation authority, and lists V1.2 through V1.3.3 as superseded. No older-version document was used as conversion input.

## Differences and Limitations

- The Markdown preserves content hierarchy, tables, formulas expressed as text, code blocks, field names, data contracts, Reason Codes, rule IDs, invariants, and status labels. Word-only pagination, colors, fonts, borders, and headers/footers are not represented because they have no Markdown semantic equivalent.
- The 52-page manual rendered without detected clipping, overlap, or blank-page defects. The local LibreOffice render lacked some Chinese font glyphs; validation therefore used the DOCX OOXML text directly rather than OCR. This is a local preview-font limitation, not a detected source-text loss.
- The DOCX contains no inline images and no Office Math objects requiring separate conversion. No content fragment was missing from the generated Markdown.
- Supporting DOCX files were archived and read for scope/status context; they were not converted to Markdown because the requested primary searchable authority is the main manual and the supplied revision record was already Markdown.

## Unresolved Matters and Gate

No import discrepancy requires manual repair. The risks and choices in `v1.3.4_open_issues.docx` remain unresolved and must not be decided by Codex.

The repository may enter a separately authorized Stage-generation activity. This validation does not approve a Stage, Task, business implementation, testnet, live execution, or compounding work.
