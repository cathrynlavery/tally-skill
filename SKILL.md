---
name: tally
description: Tally Forms REST API CLI for form management and automation. Use when creating/updating forms, reading submissions, exporting CSV or JSON, managing webhooks, or browsing workspaces via the Tally API.
---

# Tally Forms

Agent-first Tally CLI with JSON envelope responses (`ok`, `command`, `result`/`error`, `next_actions`).

## Quick Start

```bash
python3 <skill-dir>/scripts/tally.py
python3 <skill-dir>/scripts/tally.py health
```

Auth order:
1. `TALLY_API_KEY` env var
2. `op read op://Development/Tally API/credential`

## Command Groups

### Auth & Discovery

```bash
tally
tally health
tally me
```

### Forms

```bash
tally form list [--workspace-id <id>] [--limit <n>] [--page <n>] [--all]
tally form get --id <formId>
tally form create --blocks-file <path> [--workspace-id <id>] [--status DRAFT]
tally form create-simple --name "Contact" --fields "Name=text,Email=email,Message=textarea" [--workspace-id <id>] [--status DRAFT]
tally form update --id <formId> [--name "New Name"] [--status PUBLISHED] [--blocks-file <path>]
tally form delete --id <formId>
tally form questions --id <formId>
```

### Submissions

```bash
tally submission list --form-id <id> [--filter all|completed|partial] [--start-date <iso8601>] [--end-date <iso8601>] [--limit <n>] [--after-id <id>] [--page <n>] [--all]
tally submission get --form-id <id> --id <submissionId>
tally submission delete --form-id <id> --id <submissionId>
tally submission export --form-id <id> [--format csv|json] [--output <path>] [--all]
```

### Webhooks

```bash
tally webhook create --form-id <id> --url <https://endpoint> [--signing-secret-env TALLY_WEBHOOK_SECRET]
tally webhook list [--limit <n>] [--page <n>] [--all]
tally webhook delete --id <webhookId>
tally webhook events --id <webhookId> [--page <n>] [--all]
tally webhook retry --id <webhookId> --event-id <eventId>
```

### Workspaces

```bash
tally workspace list [--page <n>] [--all]
tally workspace get --id <workspaceId>
```

## DSL for `create-simple`

`--fields` grammar:

```text
label=type,label=type,...
```

Supported types:
- `text`
- `email`
- `number`
- `phone`
- `date`
- `time`
- `url`
- `textarea`
- `file`
- `rating`

Use `form create --blocks-file` for complex blocks.

## Common Workflows

### 1) Create a feedback form and connect webhook

```bash
tally form create-simple \
  --name "Customer Feedback" \
  --fields "Full Name=text,Email=email,Comments=textarea,Rating=rating"

tally webhook create \
  --form-id <newFormId> \
  --url https://example.com/webhooks/tally \
  --signing-secret-env TALLY_WEBHOOK_SECRET
```

### 2) Pull submissions and export safe CSV

```bash
tally submission list --form-id <formId> --filter completed --all

tally submission export \
  --form-id <formId> \
  --format csv \
  --output ./exports/tally-submissions.csv \
  --all
```

### 3) Audit form questions before downstream mapping

```bash
tally form questions --id <formId>
tally submission get --form-id <formId> --id <submissionId>
```

### 4) Workspace-scoped discovery

```bash
tally workspace list
tally form list --workspace-id <workspaceId> --all
```

## Security Notes

- API key is never printed in full (preview is redacted).
- CSV export sanitizes header and cell formula prefixes (`=`, `+`, `-`, `@`, tab, carriage-return).
- Webhook `signingSecret` is redacted from output payloads.
- `--blocks-file` and `--output` paths are validated.

## Reference Files

| File | Purpose | When to read |
|---|---|---|
| `references/api_reference.md` | Endpoint map, auth/version headers, payload notes | When adding new commands or debugging request/response mismatches |
| `references/form_templates.md` | Reusable form patterns (simple + blocks-file) | When creating new forms quickly or standardizing across projects |
| `scripts/tally.py` | CLI implementation | When extending behavior, adding endpoints, or changing envelope semantics |
| `agents/openai.yaml` | Agent metadata for this skill | When tuning discovery/prompt defaults |
