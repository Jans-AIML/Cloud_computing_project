# Sensitive Data Handling Guide — CEEP

This document describes how CEEP handles private and sensitive information.
Intended for project maintainers, contributors, and anyone auditing the platform.

---

## 1. Data Classification

| Classification | Examples | Storage | Queryable? |
|---|---|---|---|
| **Private / Sensitive** | Community emails, personal names, contact info | S3 private bucket (SSE-KMS) | Never raw; only PII-scrubbed excerpt |
| **Semi-public** | OCDSB letters addressed to specific families | S3 private bucket | Scrubbed excerpt only |
| **Public** | News articles, OCDSB public PDFs, Google Sites content | S3 public-docs bucket | Yes (excerpt + URL) |
| **Generated** | Evidence cards, briefs, RAG answers | RDS pgvector | Yes |

---

## 2. Consent Flow for Email Submissions

```
Contributor clicks "Add Evidence" → selects Email
        │
        ▼
UI shows consent checkbox:
  "I consent to CEEP storing a PII-redacted excerpt of this email
   as evidence. The original will be kept encrypted and never
   displayed verbatim. I can request deletion at any time."
        │
   ✓ Checked            ✗ Not checked
        │                      │
        ▼                      ▼
 Upload proceeds          Request rejected —
 (consent_flag=true)      no record created
```

The `consent_flag` is stored in the `sources` table.
Without it, `run_local_etl()` exits immediately and no chunks are created.

---

## 3. PII Redaction Pipeline

CEEP uses a **local regex-based scrubber** (no external API).
Code: `backend/app/services/local_etl.py` — `_local_pii_scrub()`.

### Processing order (emails only)

1. **Safelist protection** — known school / program / place names are token-replaced
   before any pattern runs, then restored afterwards. This prevents false positives.

2. **PII patterns** (applied in this order to avoid order-dependent bugs):

   | Pattern | Example → Result |
   |---|---|
   | `Name <email@domain>` (combined) | `Jane Doe <j@example.com>` → `[REDACTED-NAME] <[REDACTED-EMAIL]>` |
   | Thread attribution `Name, Month YYYY` | `Jane Smith, Jan 20, 2026` → `[REDACTED-NAME], Jan 20, 2026` |
   | Standalone email address | `test@example.com` → `[REDACTED-EMAIL]` |
   | Phone number | `613-555-1234` → `[REDACTED-PHONE]` |
   | Street address | `123 Elgin Street` → `[REDACTED-ADDRESS]` |

3. **Safelist restoration** — protected terms are put back unchanged.

### Safelist (never redacted, even in emails)

Lady Evelyn, Junior Kindergarten, Senior Kindergarten, Early French Immersion,
French Immersion, Extended French, Old Ottawa East, Ottawa Carleton, Ottawa Catholic,
Elgin Street, Churchill Avenue, Henry Munro, District School, School Board,
and several others — see `_EMAIL_SAFELIST` in `local_etl.py`.

### What is NOT redacted

- Dates and times (they are evidence)
- URLs and hyperlinks
- Organization names (OCDSB, Ottawa Citizen, etc.)
- Names of elected officials acting in their public capacity
- School names, program names, place names

### Scope

PII scrubbing only applies to **email** (`source_type == "email"`) sources.
Public PDFs and URLs use a lighter pattern set (email, phone, address only — no name regex).

---

## 4. Storage Security

| Resource | Protection |
|---|---|
| Private S3 bucket (`ceep-private-uploads-*`) | SSE-KMS + private ACL, no public access |
| Public S3 bucket (`ceep-public-docs-*`) | SSE-S3, public read allowed |
| RDS PostgreSQL | Private VPC subnet, no public endpoint, SSL enforced |
| Groq API key | AWS Secrets Manager (rotatable) |
| DB credentials | AWS Secrets Manager |

### Presigned URL security
- Email uploads use SigV4-signed presigned PUT URLs (required by KMS-encrypted bucket).
- Browser sends only `Content-Type` — no SSE headers (bucket default handles encryption).
- URLs expire in 15 minutes.

---

## 5. Right to Deletion

Any contributor can request deletion of their submission:

```
DELETE /documents/{id}
```

This triggers:
1. Soft-delete of the `documents` row (`deleted_at = now()`).
2. CASCADE delete of all `chunks` rows → embeddings removed from pgvector.
3. Hard-delete of the raw file from S3 (both public and private buckets).

The `evidence_cards` row is also removed (CASCADE from `documents`).
After deletion, the document is immediately excluded from all search and RAG queries.

---

## 6. What Colleagues / Testers Need to Know

- **Do not upload real personal emails from real people** unless you have their explicit consent.
- Test emails should use clearly fictional data (e.g., `test@example.com`, `Jane Test`).
- The PII scrubber strips names only in specific email-thread contexts — a random novel with
  "John Smith" in a paragraph would NOT be redacted. The patterns are conservative by design.
- If you find a false positive or false negative in PII scrubbing, open an issue and include
  the specific text pattern (anonymised) so it can be added to the safelist or patterns.


---

## 1. Data Classification

| Classification | Examples | Storage | Queryable? |
|---|---|---|---|
| **Private / Sensitive** | Community emails, personal names, contact info | S3 private bucket (SSE-KMS) | Never raw; only redacted excerpt |
| **Semi-public** | OCDSB letters addressed to specific families | S3 private bucket | Redacted excerpt only |
| **Public** | News articles, OCDSB public PDFs, Google Sites content | S3 public-docs bucket | Yes (excerpt + URL) |
| **Generated** | Evidence cards, briefs, RAG answers | RDS + S3 | Yes |

---

## 2. Consent Flow for Email Submissions

```
Contributor uploads email
        │
        ▼
UI shows consent modal:
  "I consent to CEEP storing a PII-redacted excerpt of this email
   as an evidence card. The original will be kept encrypted and
   never displayed. I can request deletion at any time."
        │
   ✓ Accept          ✗ Decline
        │                   │
        ▼                   ▼
 Upload proceeds       File rejected,
 with consent_flag=true  nothing stored
```

- The `consent_flag` and `contributor_id` are stored alongside the S3 object metadata.
- Without `consent_flag=true`, the Glue ETL job skips the file.

---

## 3. PII Redaction Pipeline (AWS Comprehend)

The `pii_redactor.py` Glue job runs **before** any text is chunked or embedded.

### Entity types redacted

| Comprehend Entity | Replaced with |
|---|---|
| `NAME` | `[REDACTED-NAME]` |
| `EMAIL` | `[REDACTED-EMAIL]` |
| `PHONE` | `[REDACTED-PHONE]` |
| `ADDRESS` | `[REDACTED-ADDRESS]` |
| `DATE_TIME` (in private emails) | kept — dates are evidence |
| `URL` | kept — links are evidence |
| `ORGANIZATION` | kept unless it's a private school name used to identify a child |

### Confidence threshold

Only entities with `Score >= 0.90` are redacted. Lower-confidence detections are
logged to CloudWatch for human review but not auto-redacted (to avoid losing evidence).

### Audit

Every redaction event is written to the `pii_audit` table in RDS:

```sql
CREATE TABLE pii_audit (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id),
    entity_type TEXT NOT NULL,
    score       REAL NOT NULL,
    char_start  INT,
    char_end    INT,
    redacted_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 4. Encryption

| At-rest target | Mechanism |
|---|---|
| S3 private bucket (raw emails) | SSE-KMS with a dedicated CMK |
| S3 public-docs bucket | SSE-S3 (AES-256) |
| RDS PostgreSQL | RDS encryption enabled at creation (AES-256) |
| Lambda environment variables | KMS-encrypted env vars |
| Secrets Manager secrets | KMS CMK |

All traffic uses TLS 1.2+ (API Gateway enforces this; CloudFront enforces HTTPS).

---

## 5. Access Control (IAM)

| Principal | Access |
|---|---|
| Lambda execution role | Read S3 public-docs, read/write RDS, call Bedrock, call Comprehend |
| Glue job role | Read S3 private bucket (raw emails), write S3 public-docs, call Comprehend, write RDS |
| Frontend user (unauthenticated) | POST to API Gateway upload endpoint only |
| Admin user (authenticated via Cognito) | All endpoints + deletion |
| No principal | Direct S3 or RDS access from the internet |

---

## 6. Right to Deletion

A contributor can request deletion by:
1. Calling `DELETE /documents/{document_id}` (authenticated endpoint).
2. The Lambda handler:
   - Deletes the raw object from S3 private bucket.
   - Soft-deletes the evidence card rows in RDS (sets `deleted_at`).
   - Removes embeddings from pgvector.
   - Logs deletion to CloudWatch.
3. Background Glue job hard-deletes soft-deleted rows after 30 days (data retention policy).

---

## 7. What Community Users See

- Only **redacted evidence cards** are ever displayed in the UI.
- Source metadata shown: `source_type`, `source_url` (for public docs), `date`, `topic` — **never** the author's name or contact info.
- The brief generator never inserts personal identifiers into generated letters.
- The RAG system is instructed (system prompt) to never reproduce names of private individuals.

---

## 8. Security Checklist Before Any Production Deploy

- [ ] KMS CMKs created and assigned to S3 private bucket and RDS instance.
- [ ] S3 private bucket has BlockPublicAccess = true on all four settings.
- [ ] API Gateway has CORS restricted to the CloudFront distribution domain.
- [ ] Secrets Manager secrets are not logged by CloudTrail (enabled by default — verify `ExcludeManagementEventSources`).
- [ ] Comprehend is called via VPC endpoint (no traffic to public internet for PII data).
- [ ] Bedrock is called via VPC endpoint.
- [ ] RDS is in a private subnet with no public IP.
- [ ] Lambda is in the same VPC as RDS; security group allows only Lambda → RDS on port 5432.
- [ ] CloudWatch log groups have a 90-day retention policy (not infinite — avoids storing PII in logs long-term).
- [ ] Lambda function has X-Ray tracing enabled.
