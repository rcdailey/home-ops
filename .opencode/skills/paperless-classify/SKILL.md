---
name: paperless-classify
description: >-
  Use when classifying, triaging, or organizing Paperless documents; reviewing the paperless inbox;
  assigning document metadata; discussing taxonomy conventions; or running
  `./scripts/paperless.sh classify`. Triggers on phrases like "classify documents", "triage
  paperless", "check the inbox", "what needs classification", "paperless taxonomy". Do NOT use for
  uploading documents, managing users/groups/workflows, or general paperless CRUD.
---

# Paperless Document Classification

Classify documents in Paperless-ngx by analyzing OCR content and assigning metadata (correspondent,
document type, tags, title) using existing taxonomy. The LLM is the classifier; the CLI provides the
data gathering and persistence interface.

## Prerequisites

- `ai-classified` tag exists in Paperless (run `./scripts/paperless.sh classify tag` to ensure)
- Taxonomy (types, correspondents, tags) is populated with initial entries
- Documents have been uploaded and OCR processing is complete

## Workflow

### 1. Check the inbox

```bash
./scripts/paperless.sh classify inbox
```

Shows documents without the `ai-classified` tag. These have never been reviewed by the AI
classifier, regardless of whether Paperless auto-assigned some fields.

### 2. Get the briefing

```bash
# All inbox docs (default limit 10)
./scripts/paperless.sh classify brief

# Specific documents
./scripts/paperless.sh classify brief 12 13 14
```

Outputs the full taxonomy (correspondents, types, tags with IDs) followed by each document's current
metadata and sanitized content (truncated to 2000 chars; YAKE keywords appended for docs over 5000
chars).

### 3. Analyze and decide

For each document, determine:

1. **Correspondent** (who issued it)
2. **Document type** (what form it takes)
3. **Tags** (topical domains)
4. **Title** (clean, normalized)

### 4. Apply classification

```bash
./scripts/paperless.sh doc update ID \
  --title "Clean Title Here" \
  --correspondent CORR_ID \
  --type TYPE_ID \
  --tag TAG_ID --tag TAG_ID
```

The `--tag` flag uses replace semantics: specified tags become the complete tag set, and
`ai-classified` is automatically injected. The agent never specifies `ai-classified` directly.

### 5. Handle taxonomy gaps

If a document needs a correspondent, type, or tag that does not exist:

- **Correspondent**: Create without asking (each business is unique)
- **Tag**: Propose to user before creating (tags must earn their existence)
- **Type**: Propose to user before creating (types are finite; see cap below)

```bash
./scripts/paperless.sh correspondent create "Parker Brothers Carpet Cleaning"
./scripts/paperless.sh tag create "home"
./scripts/paperless.sh type create "Warranty"
```

## Taxonomy Conventions

### Document Types (the "what")

The broad form of the document. Finite set, hard cap at 25.

Examples: Receipt, Invoice, Insurance Policy, Warranty, Contract, Tax Return, Bank Statement,
Certificate, License, Letter, Manual, Recipe

Principles:

- Types describe the document's form, not its topic
- If two documents would go in the same physical folder type, they share a type
- "Carpet Cleaning Receipt" is wrong; "Receipt" is the type
- Challenge whether an existing type fits before proposing a new one
- If count reaches 26, stop and consolidate immediately (merge + bulk reassign)

### Correspondents (the "who")

The entity that issued or produced the document. Normalized to common business name.

Examples: "AAA Insurance" (not "Auto Club Indemnity Company"), "Parker Brothers Carpet Cleaning",
"Wells Fargo", "IRS"

Principles:

- Use the name you would say out loud
- Merge subsidiaries into the parent brand you recognize
- One correspondent per entity; no department variants
- NEVER a family member; correspondents are external issuers only
- Create freely (each business is unique)

### Tags (the "about")

Topical labels that cut across types and correspondents. Enable cross-domain queries.

Examples: home, auto, medical, pets, financial, technology, school, appliances

Principles:

- Tags must NOT duplicate what type or correspondent already captures
- Tags answer "what domain is this relevant to?" not "what is it?"
- Broad tags that compose well: "home" + type "Warranty" beats a "home-warranty" tag
- Aim for 10-20 total; each should apply to 5+ documents to earn its existence
- Property-specific tags acceptable if filtering by property is useful
- Never create single-use tags

### Title Formatting

- Structure: `Correspondent - Description (Date or Context)`
- Examples:
  - "Parker Brothers - Carpet Cleaning Invoice (Oct 2024)"
  - "AAA Insurance - Home Policy Declaration (2025-2026)"
  - "Kwik Kar - QX60 Transmission Warranty (Nov 2022)"
- Keep titles concise but specific enough to distinguish from similar documents
- Include date context when the document is time-bounded

## Taxonomy Maintenance

### Type consolidation (when cap is reached)

```bash
# List current types
./scripts/paperless.sh type list

# Identify types to merge, then bulk-update affected docs
./scripts/paperless.sh doc list --type OLD_TYPE_ID
# Update each doc to new type, then delete the old type
./scripts/paperless.sh type delete OLD_TYPE_ID
```

### Reviewing auto-classification

Paperless auto-classifies on ingestion using a sklearn classifier trained on existing documents. Its
assignments may be wrong. The inbox workflow reviews ALL untagged documents regardless of whether
Paperless pre-filled fields. When the brief shows incorrect auto-assigned values, overwrite them
with correct values.

Over time, correct classifications improve the auto-classifier. The feedback loop is automatic.

## Decision Framework

| Action | When | Ask user? |
| ------ | ---- | --------- |
| Create correspondent | Always (each business is unique) | No |
| Create tag | No existing tag covers the domain | Yes |
| Create type | No existing type fits the form | Yes |
| Merge types | Count reaches 26 | Yes (confirm plan) |
| Delete tag/type | Never without explicit request | Always |

## Content Strategy

The `brief` command applies these transformations to document content:

1. Fix encoding artifacts (ftfy)
2. Strip fill characters, decorative separators, excess whitespace
3. Truncate to first 2000 characters
4. Append YAKE keyword extraction for documents over 5000 characters

This provides sufficient signal for classification in most cases. For ambiguous documents, use
`./scripts/paperless.sh doc show ID --full` to read the complete content.
