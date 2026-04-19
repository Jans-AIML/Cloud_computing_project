#!/usr/bin/env python3
"""
seed_corpus.py — Pre-seed the CEEP corpus with known public sources.

Submits the canonical Save Lady Evelyn, OCDSB, and community URLs
to the CEEP API for crawling and indexing.

Usage:
    cd scripts
    CEEP_API_URL=https://<api-gateway-url> python seed_corpus.py

    # Local dev:
    CEEP_API_URL=http://localhost:8000 python seed_corpus.py
"""

import os
import sys
import time
import httpx

API_URL = os.environ.get("CEEP_API_URL", "http://localhost:8000")

SEED_SOURCES = [
    # ── Save Lady Evelyn (public Google Sites) ────────────────────────────────
    {
        "filename": "lady-evelyn-home.html",
        "content_type": "text/html",
        "source_type": "url",
        "source_url": "https://sites.google.com/view/saveladyevelynschool/home",
        "consent_given": True,
        "label": "Save Lady Evelyn — Home",
    },
    {
        "filename": "lady-evelyn-action.html",
        "content_type": "text/html",
        "source_type": "url",
        "source_url": "https://sites.google.com/view/saveladyevelynschool/taking-action",
        "consent_given": True,
        "label": "Save Lady Evelyn — Taking Action",
    },
    {
        "filename": "lady-evelyn-proposal.html",
        "content_type": "text/html",
        "source_type": "url",
        "source_url": "https://sites.google.com/view/saveladyevelynschool/parents-proposal",
        "consent_given": True,
        "label": "Save Lady Evelyn — Parents' Proposal",
    },
    # ── News coverage ─────────────────────────────────────────────────────────
    {
        "filename": "cbc-ocdsb-jk-reversal.html",
        "content_type": "text/html",
        "source_type": "url",
        "source_url": "https://www.cbc.ca/news/canada/ottawa/ocdsb-delays-closing-kindergarten-registration-alternative-schools-1.7147389",
        "consent_given": True,
        "label": "CBC News — OCDSB JK Registration Reversal, Mar 2026",
    },
    # ── Community context ─────────────────────────────────────────────────────
    {
        "filename": "mainstreeter-lady-evelyn.html",
        "content_type": "text/html",
        "source_type": "url",
        "source_url": "https://www.themainstreeter.com/saving-lady-evelyn-school/",
        "consent_given": True,
        "label": "Mainstreeter — Saving Lady Evelyn School",
    },
    # ── Kitchissippi Ward ─────────────────────────────────────────────────────
    {
        "filename": "kitchissippi-ward.html",
        "content_type": "text/html",
        "source_type": "url",
        "source_url": "https://kitchissippi.ca/",
        "consent_given": True,
        "label": "Kitchissippi Ward — Councillor Jeff Leiper",
    },
]


def seed(client: httpx.Client, source: dict) -> None:
    label = source.pop("label", source["source_url"])
    try:
        response = client.post(
            f"{API_URL}/documents/upload",
            json=source,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        print(f"  ✓ {label} — document_id={data['document_id']}")
    except httpx.HTTPStatusError as exc:
        print(f"  ✗ {label} — HTTP {exc.response.status_code}: {exc.response.text[:200]}")
    except Exception as exc:
        print(f"  ✗ {label} — {exc}")


def main():
    print(f"Seeding CEEP corpus at {API_URL}")
    print(f"Submitting {len(SEED_SOURCES)} sources…\n")

    with httpx.Client() as client:
        # Health check first
        try:
            r = client.get(f"{API_URL}/health", timeout=10)
            r.raise_for_status()
            print(f"API is healthy: {r.json()}\n")
        except Exception as exc:
            print(f"API health check failed: {exc}")
            sys.exit(1)

        for source in SEED_SOURCES:
            seed(client, dict(source))
            time.sleep(0.5)  # gentle rate limiting

    print("\nDone. Documents will appear in the corpus after ETL processing (1–2 min each).")


if __name__ == "__main__":
    main()
