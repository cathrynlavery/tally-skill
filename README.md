# tally-skill

Agent-first CLI for the [Tally](https://lttlmg.ht/tallyforms) REST API. Create forms, export submissions, manage webhooks — all from the command line with structured JSON output designed for AI agent chaining.

**Zero dependencies.** Pure Python stdlib. Works with Claude Code, Codex, or any agent that can run shell commands.

## Install

### As a Claude Code skill

```bash
# Clone into your skills directory
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

# Create a form with the simple DSL
python3 scripts/tally.py form create-simple \
  --name "Customer Feedback" \
  --fields "Name=text,Email=email,Rating=rating,Comments=textarea"

# Export submissions as CSV
python3 scripts/tally.py submission export \
  --form-id <id> --format csv --output feedback.csv --all

# Set up a webhook
python3 scripts/tally.py webhook create \
  --form-id <id> --url https://example.com/webhook
```

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
| `tally form create-simple --name "..." --fields "..."` | Create form from `label=type` DSL |
| `tally form create --blocks-file <path>` | Create form from JSON block definitions |
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

## Simple Form DSL

The `create-simple` command uses a `label=type` grammar for quick form creation:

```
--fields "Full Name=text,Email=email,Comments=textarea,Rating=rating"
```

Supported types: `text`, `email`, `number`, `phone`, `date`, `time`, `url`, `textarea`, `file`, `rating`

For complex forms with choice fields, conditional logic, or custom payloads, use `--blocks-file` with a JSON file. See [references/form_templates.md](references/form_templates.md) for examples.

## Agent-First JSON Output

Every command returns a structured JSON envelope:

```json
{
  "ok": true,
  "command": "tally form list",
  "timestamp": "2026-03-24T14:22:01Z",
  "result": { "forms": [...], "hasMore": true },
  "next_actions": [
    { "command": "tally form list --page 2", "description": "Next page" },
    { "command": "tally form get --id abc123", "description": "View details" }
  ]
}
```

Errors include `http_status`, `retryable`, `fix` guidance, and `next_actions`:

```json
{
  "ok": false,
  "error": { "message": "Form not found", "http_status": 404 },
  "retryable": false,
  "fix": "Run `tally form list` to find valid form IDs"
}
```

## Security

- API keys are never printed in full (redacted to `tly-...xx`)
- CSV exports sanitize formula injection (`=`, `+`, `-`, `@`, tab, CR)
- Webhook `signingSecret` is redacted from all output
- Secrets passed via `--signing-secret-env` (env var name, not the value)
- File paths validated before read/write operations
- Rate limit retry with exponential backoff + jitter (100 req/min limit)
- Auto-pagination capped at 200 pages to prevent runaway requests

## Project Structure

```
tally-skill/
├── SKILL.md                    # Claude Code skill definition
├── README.md                   # This file
├── scripts/
│   └── tally.py                # CLI implementation (stdlib only, ~1500 lines)
├── references/
│   ├── api_reference.md        # Endpoint map and payload notes
│   └── form_templates.md       # Reusable form patterns
└── agents/
    └── openai.yaml             # Agent UI metadata
```

## API Coverage

Wraps the [Tally REST API](https://developers.tally.so/api-reference/introduction) (version `2025-05-30`):

- Users: `GET /users/me`
- Forms: full CRUD + questions
- Submissions: list, get, delete, export (CSV/JSON)
- Webhooks: create, list, delete, events, retry
- Workspaces: list, get

## License

MIT
