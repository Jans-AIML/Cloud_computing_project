# Sensitive Data Handling Guide — CEEP

This document describes exactly how CEEP handles private and sensitive information.
It is intended for project maintainers, contributors, and anyone auditing the platform.

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
