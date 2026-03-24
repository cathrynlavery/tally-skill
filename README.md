# tally-skill

Your AI agent shouldn't need a browser to create a form, pull survey results, or wire up a webhook. This CLI gives it 18 commands to manage [Tally](https://lttlmg.ht/tallyforms) forms programmatically — create multi-page surveys from the terminal, export submissions as safe CSV, and pipe form data into any pipeline.

**Zero dependencies.** Pure Python stdlib. One `git clone` to install. Structured JSON output every agent can parse.

## Install

### As a Claude Code skill

```bash
git clone https://github.com/cathrynlavery/tally-skill.git ~/.claude/skills/tally
```

### Standalone

```bash
git clone https://github.com/cathrynlavery/tally-skill.git
cd tally-skill
python3 scripts/tally.py health
```

## Authentication

Set your [Tally API key](https://lttlmg.ht/tallyforms) via environment variable (generate one at Settings > API keys):

```bash
export TALLY_API_KEY='tly-xxxx'
```

The CLI also checks 1Password (`op://Development/Tally API/credential`) as a fallback.

## Quick Start

```bash
# Verify credentials
python3 scripts/tally.py health

# List your forms
python3 scripts/tally.py form list

# Create a survey with text, multiple choice, and rating fields — one command
python3 scripts/tally.py form create-simple \
  --name "Customer Feedback" \
  --fields "Name=text,Email=email,How did you find us?=choice:Google/Twitter/Friend/Other,Rating=rating,Comments=textarea"

# Export submissions as CSV (formula-injection safe)
python3 scripts/tally.py submission export \
  --form-id <id> --format csv --output feedback.csv --all

# Set up a webhook to pipe new submissions somewhere
python3 scripts/tally.py webhook create \
  --form-id <id> --url https://example.com/webhook
```

## Create Forms from the Terminal

### One-liner (simple DSL)

```bash
tally form create-simple \
  --name "Event Registration" \
  --fields "Name=text,Email=email,Company=text,Dietary needs=dropdown:None/Vegetarian/Vegan/Gluten-free,Topics=checkbox:AI/Marketing/Product/Engineering"
```

Supported field types: `text`, `email`, `number`, `phone`, `date`, `time`, `url`, `textarea`, `file`, `rating`, `choice:a/b/c`, `dropdown:a/b/c`, `checkbox:a/b/c`

### Multi-page forms (simplified JSON)

For forms with page breaks, headings, and mixed field types, use a blocks file. No UUIDs needed — they're auto-generated:

```json
{
  "status": "DRAFT",
  "blocks": [
    {"type": "FORM_TITLE", "title": "Job Application"},
    {"type": "text", "label": "Full Name", "required": true},
    {"type": "email", "label": "Email", "required": true},
    {"type": "PAGE_BREAK"},
    {"type": "HEADING", "text": "About You"},
    {"type": "choice", "label": "Department", "options": ["Engineering", "Marketing", "Design"]},
    {"type": "textarea", "label": "Why do you want to join?", "required": true},
    {"type": "PAGE_BREAK"},
    {"type": "dropdown", "label": "Experience", "options": ["0-1 years", "2-4", "5-9", "10+"]},
    {"type": "rating", "label": "How excited are you?"},
    {"type": "file", "label": "Upload resume"}
  ]
}
```

```bash
tally form create --blocks-file application.json
```

See [references/form_templates.md](references/form_templates.md) for more templates.

## Commands

### Auth & Discovery

| Command | Description |
|---------|-------------|
| `tally` | Machine-parseable command index + auth status |
| `tally health` | Verify credentials and API connectivity |
| `tally me` | Current user info |

### Forms

| Command | Description |
|---------|-------------|
| `tally form list` | List forms (supports `--workspace-id`, `--all`) |
| `tally form get --id <id>` | Get form details with blocks |
| `tally form create-simple --name "..." --fields "..."` | Create form from DSL |
| `tally form create --blocks-file <path>` | Create form from JSON (simplified or raw) |
| `tally form update --id <id>` | Update name, status, or blocks |
| `tally form delete --id <id>` | Delete form (moves to trash) |
| `tally form questions --id <id>` | List form questions |

### Submissions

| Command | Description |
|---------|-------------|
| `tally submission list --form-id <id>` | List submissions (`--filter`, `--start-date`, `--end-date`, `--after-id`, `--all`) |
| `tally submission get --form-id <id> --id <id>` | Get single submission |
| `tally submission delete --form-id <id> --id <id>` | Delete submission |
| `tally submission export --form-id <id>` | Export as CSV or JSON (`--format`, `--output`, `--all`) |

### Webhooks

| Command | Description |
|---------|-------------|
| `tally webhook create --form-id <id> --url <url>` | Create webhook (`--signing-secret-env`) |
| `tally webhook list` | List all webhooks |
| `tally webhook delete --id <id>` | Delete webhook |
| `tally webhook events --id <id>` | View delivery history |
| `tally webhook retry --id <id> --event-id <id>` | Retry failed delivery |

### Workspaces

| Command | Description |
|---------|-------------|
| `tally workspace list` | List workspaces |
| `tally workspace get --id <id>` | Get workspace details |

## Agent-First JSON Output

Every command returns structured JSON with `next_actions` your agent can chain:

```json
{
  "ok": true,
  "command": "tally form create-simple ...",
  "result": { "form": {"id": "abc123"}, "fieldCount": 5 },
  "next_actions": [
    { "command": "tally webhook create --form-id abc123 --url ...", "description": "Set up webhook" },
    { "command": "tally submission list --form-id abc123", "description": "Check for submissions" }
  ]
}
```

Errors include `http_status`, `retryable`, and `fix` guidance so agents can self-correct.

## Security

- API keys never printed in full (redacted to `tly-...xx`)
- CSV exports sanitize formula injection (`=`, `+`, `-`, `@`, tab, CR)
- Webhook `signingSecret` redacted from all output
- Secrets passed via `--signing-secret-env` (env var name, not the value)
- File paths validated before read/write
- Rate limit retry with exponential backoff + jitter
- Auto-pagination capped at 200 pages

## API Coverage

Wraps the [Tally REST API](https://developers.tally.so/api-reference/introduction) (version `2025-05-30`):

- Users: `GET /users/me`
- Forms: full CRUD + questions
- Submissions: list, get, delete, export (CSV/JSON)
- Webhooks: create, list, delete, events, retry
- Workspaces: list, get

## Built by

[Cathryn Lavery](https://x.com/cathrynlavery) — Founder of [BestSelf Co](https://bestself.co) ($55M+ bootstrapped). Sold to PE in 2022. Bought it back in 2024. Now becoming AI-native and documenting the journey at [founder.codes](https://founder.codes).

## License

MIT
