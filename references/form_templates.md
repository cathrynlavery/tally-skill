# Tally Form Templates

Use these when generating forms with `tally form create-simple` or `tally form create --blocks-file`.

## Quick Forms (DSL)

### Contact Form

```bash
tally form create-simple \
  --name "Contact Us" \
  --fields "Full Name=text,Email=email,Company=text,Message=textarea"
```

### Customer Feedback

```bash
tally form create-simple \
  --name "Product Feedback" \
  --fields "Name=text,Email=email,Rating=rating,What do you like most?=choice:Features/Design/Price/Support,Comments=textarea"
```

### Lead Qualification

```bash
tally form create-simple \
  --name "Lead Qualification" \
  --fields "Name=text,Email=email,Phone=phone,Website=url,Monthly Budget=number,Industry=dropdown:SaaS/E-commerce/Agency/Other"
```

### Event Registration

```bash
tally form create-simple \
  --name "Event Registration" \
  --fields "Name=text,Email=email,Company=text,Dietary needs=dropdown:None/Vegetarian/Vegan/Gluten-free,Topics of interest=checkbox:AI/Marketing/Product/Engineering"
```

## Multi-Page Forms (Simplified Blocks File)

The blocks file supports a simplified JSON format. No UUIDs needed — they're auto-generated.

### Job Application (multi-page with choices)

```json
{
  "status": "DRAFT",
  "blocks": [
    {"type": "FORM_TITLE", "title": "Job Application"},
    {"type": "text", "label": "Full Name", "required": true},
    {"type": "email", "label": "Email", "required": true},
    {"type": "phone", "label": "Phone Number"},
    {"type": "PAGE_BREAK"},
    {"type": "HEADING", "text": "About You"},
    {"type": "choice", "label": "Department", "options": ["Engineering", "Marketing", "Design", "Operations"]},
    {"type": "textarea", "label": "Why do you want to join?", "required": true},
    {"type": "PAGE_BREAK"},
    {"type": "HEADING", "text": "Skills & Experience"},
    {"type": "dropdown", "label": "Years of experience", "options": ["0-1", "2-4", "5-9", "10+"]},
    {"type": "checkbox", "label": "Tools you use", "options": ["VS Code", "Figma", "Notion", "Slack", "Linear"]},
    {"type": "rating", "label": "How excited are you about this role?"},
    {"type": "file", "label": "Upload your resume"}
  ]
}
```

Create: `tally form create --blocks-file application.json`

### Customer Survey (multi-page)

```json
{
  "status": "DRAFT",
  "blocks": [
    {"type": "FORM_TITLE", "title": "Customer Satisfaction Survey"},
    {"type": "TEXT_BLOCK", "text": "Thanks for taking a few minutes to share your feedback."},
    {"type": "email", "label": "Email (optional)"},
    {"type": "PAGE_BREAK"},
    {"type": "HEADING", "text": "Your Experience"},
    {"type": "rating", "label": "Overall satisfaction"},
    {"type": "choice", "label": "How often do you use our product?", "options": ["Daily", "Weekly", "Monthly", "Rarely"]},
    {"type": "choice", "label": "Would you recommend us?", "options": ["Definitely", "Probably", "Not sure", "No"]},
    {"type": "PAGE_BREAK"},
    {"type": "HEADING", "text": "Details"},
    {"type": "textarea", "label": "What's working well?"},
    {"type": "textarea", "label": "What could be improved?"},
    {"type": "dropdown", "label": "Which feature matters most?", "options": ["Speed", "Reliability", "Design", "Price", "Support"]}
  ]
}
```

## Simplified Block Types

| Type | Description | Extra fields |
|------|-------------|-------------|
| `FORM_TITLE` | Form title | `title` |
| `PAGE_BREAK` | Multi-page separator | |
| `HEADING` | Section heading | `text` |
| `TEXT_BLOCK` | Descriptive paragraph | `text` |
| `text` | Short text input | `label`, `required`, `placeholder` |
| `email` | Email input | `label`, `required` |
| `number` | Number input | `label`, `required` |
| `phone` | Phone input | `label`, `required` |
| `date` | Date picker | `label`, `required` |
| `time` | Time picker | `label`, `required` |
| `url` | URL input | `label`, `required` |
| `textarea` | Long text | `label`, `required` |
| `file` | File upload | `label` |
| `rating` | Star rating (1-5) | `label`, `stars` |
| `choice` | Multiple choice (radio) | `label`, `options`, `required` |
| `dropdown` | Dropdown select | `label`, `options`, `required` |
| `checkbox` | Multi-select checkboxes | `label`, `options`, `required` |

## Notes

- Simplified blocks auto-generate all UUIDs and grouping.
- You can mix simplified and raw Tally blocks in the same file.
- Raw Tally blocks (with `uuid`, `groupUuid`, `groupType`) pass through unchanged.
- `PAGE_BREAK` creates multi-page forms. Fields before the first break are page 1, etc.
- For conditional logic, use the raw Tally block format (inspect an existing form with `tally form get --id <id>` to see the structure).
