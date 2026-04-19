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

CEEP was built by Algonquin College students as part of a cloud computing course project.
It was inspired by the advocacy efforts around Lady Evelyn Alternative School in Old Ottawa East.
The platform is open-source and free to use and adapt.

---

## What evidence is already in CEEP?

When you first open CEEP, the corpus already includes:

| Source | What it contains |
|---|---|
| Save Lady Evelyn (Google Sites) | Main page, actions page, parents' proposal |
| CBC News / Yahoo News Canada | Coverage of the March 2026 JK intake reversal |
| Mainstreeter articles | OOE community context and advocacy coverage |
| OCDSB public PDFs | Official capacity studies and boundary review documents |
| 340 Parkdale design brief | Neighbourhood intensification context |
| Kitchissippi Ward updates | Councillor Jeff Leiper's office communications |

---

## How to submit your own evidence

### Submitting a public document (news article, PDF, web page)

1. Click **"Add Evidence"** in the navigation bar.
2. Choose **"Public document"**.
3. Paste the URL, or drag-and-drop a PDF.
4. CEEP will extract the text, create a citable evidence card, and add it to the searchable corpus.

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

PII = Personally Identifiable Information (your name, email, phone, address).
Before any excerpt is saved, an automated system replaces these with labels like:

> *"[REDACTED-NAME] wrote on [REDACTED-DATE] that the school..."*

Dates, place names, policy details, and quotes about school decisions are **kept** because
they are the evidence. Only personal identifiers are removed.

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
   - Submission to OCDSB Supervisor
   - Letter to City Councillor
   - Letter to MPP / MP
   - Local newspaper op-ed
2. Select your **goal** (e.g., "Request restoration of full programming at Lady Evelyn").
3. Choose your **tone** (formal / community voice).
4. Click **Generate**.

CEEP drafts the letter with evidence cards as footnotes.
**You should always review and edit the draft before sending it.** The tool assists — it does not
replace your own judgment.

---

## Privacy & Your Rights

| Your right | How to exercise it |
|---|---|
| Know what data is stored | Our full data policy is at `/privacy` in the CEEP app |
| Delete your submission | Click your name (top right) → "My submissions" → "Delete" |
| Export your submission | Click "Export" on any evidence card you submitted |
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

CEEP is open-source. The code is on GitHub (link in the app footer).  
To adapt it for another school or neighbourhood:

1. Fork the repository.
2. Update `docs/corpus_sources.md` with your evidence sources.
3. Run `scripts/seed_corpus.py` to pre-load your sources.
4. Deploy to your own AWS account (free tier covers a small community project).

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
