# Community Guide — How to Use CEEP

This plain-language guide is for **parents, local organizations, and concerned community
members** who want to use CEEP to support schools like Lady Evelyn, Churchill, Regina Street,
and Riverview.

---

## What is CEEP?

CEEP (Community Evidence & Engagement Platform) is a free, open tool that:

- **Collects and organises evidence** about your school from news, official OCDSB documents,
  and community submissions.
- **Answers questions** about what has changed and when, with citations you can verify.
- **Drafts letters and briefs** for OCDSB supervisors, city councillors, and local media —
  grounded in real evidence, not just opinion.

CEEP does **not** make political decisions. It helps you present facts clearly and efficiently.

---

## Who built it and why?

CEEP was built by Lambton College students as part of a cloud computing course project.
It was inspired by the advocacy efforts around Lady Evelyn Alternative School in Old Ottawa East.
The platform is open-source and free to use and adapt.

---

## What evidence is already in CEEP?

When you first open CEEP, the corpus already includes **14 documents**:

| # | Type | Source | What it contains |
|---|---|---|---|
| 1 | PDF | Save Lady Evelyn parents' proposal | Full community proposal to OCDSB |
| 2 | PDF | Lady Evelyn Evidence deck (compiled) | Composite evidence PDF |
| 3 | PDF | OCDSB Ottawa South capacity study | Official school capacity data |
| 4 | PDF | 340 Parkdale / Greystone design brief | Neighbourhood intensification context |
| 5 | PDF | Kitchissippi Ward update (Leiper) | Councillor communications |
| 6 | PDF | Ottawa Carleton District SB documents | Boundary review materials |
| 7 | PDF | Mainstreeter article (PDF) | OOE community newspaper |
| 8 | PDF | OCDSB March 2026 board agenda | Official board meeting materials |
| 9 | PDF | Save Lady Evelyn action sheet | Community action guide |
| 10 | PDF | Background brief PDF | Supporting evidence compilation |
| 11 | Web | Save Lady Evelyn (Google Sites) | Parents' proposal web page |
| 12 | Web | Yahoo Canada News — March 2026 | JK intake reversal news coverage |
| 13 | Email | Lady Evelyn next steps | Internal community coordination |
| 14 | Email | Re: Lady Evelyn — Mainstreeter op-ed | Press/advocacy coordination |

> **Email sources** are consent-gated and PII-scrubbed — see the Privacy section below.

---

## How to submit your own evidence

### Submitting a public document (news article, PDF, web page)

1. Click **"Add Evidence"** in the navigation bar.
2. Choose **"Public document"** (PDF) or **"Web page"** (URL).
3. Paste the URL, or drag-and-drop a PDF.
4. Click **"Process"** next to the uploaded item — CEEP extracts the text, generates a summary
   evidence card, and adds it to the searchable corpus.

No consent is needed for publicly available documents.

### Submitting a community email

Your email may contain important evidence (e.g., what OCDSB told you, dates, commitments
made). Here is how we handle it:

1. Click **"Add Evidence"** → **"Email"**.
2. Paste or upload your email.
3. Read the **consent notice** carefully:

> *"CEEP will store a PII-redacted excerpt of this email as an evidence card.
> Your name, email address, phone number, and home address will be automatically
> removed before anything is saved or displayed. The original email is stored
> encrypted and is never shown to anyone. You can request deletion at any time."*

4. Check the box and click **"Submit"**.

If you do not consent, nothing is stored — the email is discarded immediately.

### What does "PII-redacted" mean?

PII = Personally Identifiable Information (your name, email address, phone, home address).
Before any excerpt is saved, CEEP replaces these with placeholders like `[REDACTED]`.

School names, ward names, policy terms (e.g., "Junior Kindergarten", "Lady Evelyn",
"Ottawa Carleton District School Board", "French Immersion"), dates, and quotes about
board decisions are **kept exactly as written** because they are the evidence.
Only personal identifiers are removed.

The redaction uses a safelist approach: known school/location names are explicitly
protected from being altered, so your evidence retains its meaning.

---

## Asking questions

Use the **Ask** tab to type a question in plain language, for example:

- *"What changed on March 9–10, 2026 for JK registration at Lady Evelyn?"*
- *"What is the current enrolment capacity at Lady Evelyn?"*
- *"What community proposals have been submitted to OCDSB?"*

CEEP will return a short answer **with inline citations** — every claim is linked to a source
you can click and verify.  
If CEEP is uncertain, it will say so rather than invent information.

---

## Generating a letter or brief

Use the **Write** tab:

1. Choose a template:
   - **Local Op-Ed** — opinion piece for a neighbourhood newspaper
   - **Letter to City Councillor** — formal request to a ward councillor
   - **Submission to OCDSB** — structured brief for the school board
   - **General Advocacy Letter** — flexible template for any audience
2. Describe your **goal** (e.g., "Urge OCDSB to restore full JK enrolment at Lady Evelyn").
3. Choose your **audience and tone** settings.
4. Click **Generate**.

CEEP drafts the document with inline `[1] [2] …` citation markers and a numbered sources
panel below the draft. Every citation is linked to real evidence in the corpus.

**You should always review and edit the draft before sending it.** The tool assists — it does not
replace your own judgment.

---

## Privacy & Your Rights

| Your right | How to exercise it |
|---|---|
| Know what data is stored | Our full data policy is at `/privacy` in the CEEP app |
| Delete your submission | Click **"Delete"** next to any document you uploaded on the Evidence page |
| Export your submission | Click **"Download"** on any evidence card you submitted |
| Ask a question | Email the project team (address in the app footer) |

---

## What CEEP will never do

- Display your name, email, address, or phone number.
- Share data with third parties (no advertising, no analytics vendors).
- Generate content that targets or attacks specific individuals.
- Make political endorsements or party-political statements.
- Store anything without your consent (for private submissions).

---

## How to reuse CEEP for another school or community issue

CEEP is open-source. The code is on GitHub:
<https://github.com/Jans-AIML/Cloud_computing_project>

To adapt it for another school or neighbourhood:

1. Fork the repository.
2. Update the corpus by uploading your own PDFs and URLs through the Evidence page.
3. For cloud deployment, see `docs/developer_guide.md` — it lists all AWS resource names,
   Docker build commands, and CDK deployment steps.

If you need help, open a GitHub Issue and the team will respond.

---

## Glossary

| Term | Plain-language meaning |
|---|---|
| Evidence card | A short, cited excerpt from a source document, stored in CEEP and searchable |
| RAG | "Retrieval-Augmented Generation" — the AI first finds relevant evidence cards, then writes an answer grounded in those cards |
| Corpus | The full collection of evidence cards in CEEP |
| PII | Personally Identifiable Information — your name, contact details, etc. |
| Brief | A short, formal document summarising evidence and making a request to decision-makers |
