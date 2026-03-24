# Tally API Reference (Skill-Focused)

Source of truth used for this skill:
- OpenAPI: `https://api.tally.so/openapi.json`
- Docs: `https://developers.tally.so/api-reference`

## Base Configuration

- Base URL: `https://api.tally.so`
- Auth header: `Authorization: Bearer <token>`
- Version header: `tally-version: 2026-02-05`
- Response style: JSON

## Auth Lookup Chain

1. `TALLY_API_KEY` environment variable
2. `op read op://Development/Tally API/credential`

## Endpoint Map Used by `tally.py`

### User
- `GET /users/me`

### Forms
- `GET /forms`
  - Query: `page`, `limit`, `workspaceIds[]`
- `POST /forms`
  - Required body fields: `status`, `blocks`
- `GET /forms/{formId}`
- `PATCH /forms/{formId}`
- `DELETE /forms/{formId}`
- `GET /forms/{formId}/questions`

### Submissions
- `GET /forms/{formId}/submissions`
  - Query: `page`, `limit`, `filter`, `startDate`, `endDate`, `afterId`
- `GET /forms/{formId}/submissions/{submissionId}`
- `DELETE /forms/{formId}/submissions/{submissionId}`

### Webhooks
- `GET /webhooks`
  - Query: `page`, `limit`
- `POST /webhooks`
  - Required body fields: `formId`, `url`, `eventTypes`
- `DELETE /webhooks/{webhookId}`
- `GET /webhooks/{webhookId}/events`
  - Query: `page`
- `POST /webhooks/{webhookId}/events/{eventId}`

### Workspaces
- `GET /workspaces`
  - Query: `page`
- `GET /workspaces/{workspaceId}`

## Notes for Builders

- `eventTypes` currently supports `FORM_RESPONSE`.
- Form creation/update blocks are schema-validated in API version `2026-02-05`.
- Pagination uses `hasMore`; this skill caps `--all` at 200 pages.
- Submissions list supports both page-based and cursor-style (`afterId`) pagination.

## Export Semantics in this Skill

- CSV headers come from question titles.
- CSV cells use `formattedAnswer`.
- Duplicate question titles are disambiguated as `title`, `title_2`, `title_3`, ...
- Formula injection guard prefixes dangerous headers/cells with `'`.

## Webhook Secret Handling

- Input: only via `--signing-secret-env <ENV_NAME>`.
- Output: `signingSecret` values are always redacted.
