# Renewal Campaign — WhatsApp Template Sending Integration

## Context

The WhatsApp Inbox system (countrylinks.in/whatsapp) has a "Renewals" tab that displays ISP customer renewal data fetched from a separate IMS automation system (countrylinks.in/ims). When an operator sends a WhatsApp template from this Renewals section, it must follow the same database logging flow as the standalone IMS dashboard.

## API Endpoint

All template sends from the Renewals tab go through:

```
POST /ims/api/renewals/send
```

**Request body:**
```json
{
  "renewal_id": 42,
  "template_name": "pack_expiry_alert",
  "params": ["Avinash", "shrirameth_avinash", "2026-05-26"],
  "operator_name": "whatsapp_inbox",
  "override_duplicate": false
}
```

**Response (success):**
```json
{
  "success": true,
  "result": {
    "success": true,
    "message_id": "wamid.HBgLOTE3...",
    "status": "sent"
  }
}
```

**Response (duplicate blocked):**
```json
{
  "success": false,
  "error": "Duplicate: Template 'pack_expiry_alert' already sent to 9876543210 within the last 24 hours."
}
```

## Database: countrylinks_user_database

### Tables Involved

#### 1. `renewal_records` (READ ONLY during send)

Source of customer data displayed in the Renewals tab.

```sql
CREATE TABLE renewal_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_name VARCHAR(255),
    mobile VARCHAR(20),
    account_id VARCHAR(100),
    plan_name VARCHAR(255),
    expiry_date DATE,
    days_remaining INT,
    category VARCHAR(50),          -- 'expired' | 'today' | 'upcoming'
    zone_name VARCHAR(100),
    amount VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_account (account_id)
);
```

#### 2. `whatsapp_campaign_logs` (WRITTEN on every send attempt)

Logs every template send — success or failure.

```sql
CREATE TABLE whatsapp_campaign_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    renewal_id INT,                -- FK to renewal_records.id
    mobile VARCHAR(20),            -- recipient phone number
    template_name VARCHAR(100),    -- e.g. 'pack_expiry_alert'
    template_params JSON,          -- e.g. ["Avinash", "ACC123", "2026-05-26"]
    status VARCHAR(50),            -- 'sent' | 'failed' | 'pending'
    whatsapp_message_id VARCHAR(255), -- Meta API message ID (null if failed)
    operator_name VARCHAR(255),    -- who triggered it (e.g. 'whatsapp_inbox')
    error_message TEXT,            -- error details if failed
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 3. `operator_actions` (WRITTEN for audit trail)

Tracks who did what for accountability.

```sql
CREATE TABLE operator_actions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    operator_name VARCHAR(255),    -- e.g. 'whatsapp_inbox'
    action_type VARCHAR(100),      -- 'send_message' | 'bulk_send'
    target_id INT,                 -- renewal_records.id
    details JSON,                  -- {"template": "...", "mobile": "..."}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Send Flow (what happens on each send)

```
Operator clicks "Send" on a renewal record
    │
    ▼
Step 1: DUPLICATE CHECK (query whatsapp_campaign_logs)
    SELECT COUNT(*) FROM whatsapp_campaign_logs
    WHERE mobile = ? AND template_name = ? AND renewal_id = ?
      AND status = 'sent' AND sent_at > (NOW - 24 hours)
    → If count > 0 and override_duplicate = false → BLOCK (return 409)
    │
    ▼
Step 2: SEND via Meta WhatsApp Cloud API
    POST https://graph.facebook.com/v18.0/{PHONE_ID}/messages
    Body: { messaging_product: "whatsapp", to: "91XXXXXXXXXX", type: "template", ... }
    │
    ├── SUCCESS → status = 'sent', capture message_id
    └── FAILURE → status = 'failed', capture error_message
    │
    ▼
Step 3: LOG TO whatsapp_campaign_logs
    INSERT INTO whatsapp_campaign_logs
      (renewal_id, mobile, template_name, template_params, status, whatsapp_message_id, operator_name, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    │
    ▼
Step 4: LOG TO operator_actions
    INSERT INTO operator_actions
      (operator_name, action_type, target_id, details)
    VALUES ('whatsapp_inbox', 'send_message', 42, '{"template":"...","mobile":"..."}')
```

## Template Mapping by Category

| Customer Category | Condition | Template Name | Template Params |
|-------------------|-----------|---------------|-----------------|
| expired | expiry_date < today | `pack_expiry_alert` | {{1}}=name, {{2}}=account_id, {{3}}=expiry_date |
| today | expiry_date == today | `recharge_today1` | {{1}}=name, {{2}}=account_id, {{3}}=expiry_date |
| upcoming | expiry_date > today | `recharge_reminder` | {{1}}=name, {{2}}=account_id, {{3}}=expiry_date |

## Bulk Send

```
POST /ims/api/renewals/bulk-send
```

```json
{
  "renewal_ids": [42, 43, 44, 45],
  "operator_name": "whatsapp_inbox",
  "override_duplicate": false
}
```

Each record in the list gets:
- Its category-appropriate template auto-selected
- Params auto-filled from renewal_records data
- Individual log entry in whatsapp_campaign_logs
- One operator_actions entry for the bulk operation

## Duplicate Protection Rules

- Same template + same mobile + same renewal_id = blocked within 24 hours
- Configurable via `DUPLICATE_INTERVAL_HOURS` env var (default: 24)
- Operator can override with `override_duplicate: true`
- Failed sends do NOT count as duplicates (only status='sent' blocks)

## Important Notes

1. The Renewals tab in WhatsApp inbox fetches data from `/ims/api/renewals/` (separate Python/Flask app)
2. Both apps share the same MySQL database (`countrylinks_user_database`)
3. The IMS app handles all DB writes — the WhatsApp inbox only calls the API
4. Phone numbers are stored as 10-digit Indian numbers; the API adds "91" prefix before sending
5. Template params are auto-populated — operators should NOT manually type them
6. The `operator_name` field distinguishes sends from dashboard vs inbox (use 'whatsapp_inbox' for inbox sends)
