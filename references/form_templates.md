# Tally Form Templates

Use these when generating forms quickly with `tally form create-simple` or `tally form create --blocks-file`.

## 1) Contact Form (Simple DSL)

```bash
tally form create-simple \
  --name "Contact Us" \
  --fields "Full Name=text,Email=email,Company=text,Message=textarea"
```

## 2) Customer Feedback (Simple DSL)

```bash
tally form create-simple \
  --name "Product Feedback" \
  --fields "Name=text,Email=email,Rating=rating,Comments=textarea"
```

## 3) Lead Qualification (Simple DSL)

```bash
tally form create-simple \
  --name "Lead Qualification" \
  --fields "Name=text,Email=email,Phone=phone,Website=url,Monthly Budget=number"
```

## 4) Blocks File Template (Advanced)

Use this when you need full control over block payloads.

```json
{
  "status": "DRAFT",
  "blocks": [
    {
      "uuid": "11111111-1111-4111-8111-111111111111",
      "type": "FORM_TITLE",
      "groupUuid": "11111111-1111-4111-8111-111111111111",
      "groupType": "FORM_TITLE",
      "payload": { "html": "Application Form" }
    },
    {
      "uuid": "22222222-2222-4222-8222-222222222222",
      "type": "QUESTION",
      "groupUuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "groupType": "QUESTION",
      "payload": { "isRequired": true }
    },
    {
      "uuid": "33333333-3333-4333-8333-333333333333",
      "type": "LABEL",
      "groupUuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "groupType": "QUESTION",
      "payload": { "html": "What is your full name?" }
    },
    {
      "uuid": "44444444-4444-4444-8444-444444444444",
      "type": "INPUT_TEXT",
      "groupUuid": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "groupType": "QUESTION",
      "payload": {}
    }
  ]
}
```

Create from file:

```bash
tally form create --blocks-file ./application-form.json
```

## Notes

- Keep every block `uuid`/`groupUuid` as valid UUIDs.
- For question groups, `QUESTION`, `LABEL`, and input block share the same `groupUuid` and use `groupType: QUESTION`.
- Start with simple DSL unless you need advanced block-specific payload controls.
