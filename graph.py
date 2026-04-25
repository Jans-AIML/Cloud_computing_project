#!/usr/bin/env python3
"""
CEEP Architecture Diagrams
===========================
Generates 4 annotated SVG diagrams using diagrams-as-code (mingrammer/diagrams)
then packages them into a self-contained animated HTML viewer.

Usage:
    python graph.py
    # → opens architecture_viewer.html automatically

Diagrams:
  1. ceep_architecture.svg   — Full cloud system architecture
  2. ceep_etl_pipeline.svg   — Upload & ETL pipeline (ingest → embed → store)
  3. ceep_rag_flow.svg        — Search & RAG query flow
  4. ceep_cdk_stacks.svg      — CDK infrastructure stack dependencies
"""

from diagrams.programming.language import Python
from diagrams.onprem.network import Internet
from diagrams.onprem.client import Users
from diagrams.aws.devtools import Codecommit
from diagrams.aws.analytics import Glue
from diagrams.aws.management import Cloudwatch
from diagrams.aws.security import SecretsManager, KMS
from diagrams.aws.storage import S3
from diagrams.aws.network import APIGateway, CloudFront
from diagrams.aws.database import RDS
from diagrams.aws.compute import Lambda, ECR
from diagrams import Diagram, Cluster, Edge
import os
import re
import webbrowser
from pathlib import Path

# ── Add Graphviz to PATH (Windows default install location) ──────────────────
os.environ["PATH"] += os.pathsep + r"C:\Program Files\Graphviz\bin"


# ── Common graph attribute sets ──────────────────────────────────────────────

DARK = dict(
    fontname="Arial",
    fontsize="13",
    bgcolor="white",
    fontcolor="#1e293b",
    pad="1.0",
    splines="ortho",
    nodesep="0.75",
    ranksep="1.1",
)
NODE = dict(fontname="Arial", fontsize="11", fontcolor="#1e293b")
EDGE = dict(color="#64748b", fontcolor="#475569",
            fontsize="9", fontname="Arial")

# Named edge styles for semantic clarity
HTTPS = Edge(color="#38bdf8", label="HTTPS",
             style="bold",   fontname="Arial", fontsize="9")
DATA = Edge(color="#4ade80", label="data",
            style="dashed", fontname="Arial", fontsize="9")
DEPLOY = Edge(color="#fbbf24", label="deploy",
              style="dotted", fontname="Arial", fontsize="9")
SECRETS = Edge(color="#c084fc", label="secrets",
               fontname="Arial", fontsize="9")
LOG = Edge(color="#64748b", label="logs",
           style="dashed", fontname="Arial", fontsize="9")
FLOW = Edge(color="#38bdf8", style="bold",    fontname="Arial", fontsize="9")
RESULT = Edge(color="#4ade80", style="bold",
              label="response", fontname="Arial", fontsize="9")


# ── Diagram 1 ── Full System Architecture ────────────────────────────────────

def draw_system_architecture():
    with Diagram(
        "CEEP — Full Cloud Architecture",
        filename="./diagrams/ceep_architecture",
        outformat=["png"],
        show=False,
        direction="LR",
        graph_attr=DARK,
        node_attr=NODE,
        edge_attr=EDGE,
    ):
        users = Users("Community Users\nOttawa parents & teachers")

        with Cluster("AWS Cloud  ·  us-east-1"):

            with Cluster("Tier 1 — CDN"):
                cf = CloudFront("CloudFront\nHTTPS  ·  SPA routing  ·  OAC")
                s3_fe = S3("S3 Frontend\nReact / Vite SPA")

            with Cluster("Tier 2 — Compute & API"):
                apigw = APIGateway("API Gateway\nHTTP API  ·  10 routes")
                lmb = Lambda("Lambda\nFastAPI + Mangum\n1 GB · 120 s · Docker")
                ecr = ECR("ECR\nlinux/amd64 image")

            with Cluster("Tier 3 — Data"):
                s3_prv = S3(
                    "S3 Private Uploads\nEmails · SSE-KMS · 90-day TTL")
                s3_pub = S3("S3 Public Docs\nPDFs · parsed text · SSE-S3")
                rds = RDS(
                    "RDS PostgreSQL 15\n+ pgvector (384-dim)\ndb.t3.micro · private VPC")

            with Cluster("Security"):
                sm = SecretsManager("Secrets Manager\nDB creds · Groq API key")
                kms = KMS("KMS CMK\nAES-256 · auto-rotation")

            cw = Cloudwatch("CloudWatch\nStructured JSON logs")

        groq = Internet("Groq Cloud\nllama-3.1-8b-instant\n(external LLM)")

        # ── Request path ──────────────────────────────────────────────────────
        users >> HTTPS >> cf
        cf >> Edge(color="#38bdf8", label="origin fetch",
                   style="dashed") >> s3_fe
        users >> HTTPS >> apigw
        apigw >> HTTPS >> lmb

        # ── Data access ───────────────────────────────────────────────────────
        lmb >> DATA >> s3_prv
        lmb >> DATA >> s3_pub
        lmb >> DATA >> rds

        # ── Secrets & encryption ──────────────────────────────────────────────
        lmb >> SECRETS >> sm
        kms >> Edge(color="#c084fc", label="encrypts") >> s3_prv
        kms >> Edge(color="#c084fc", label="encrypts") >> rds

        # ── CI/Deploy path ────────────────────────────────────────────────────
        ecr >> DEPLOY >> lmb

        # ── External LLM ──────────────────────────────────────────────────────
        lmb >> Edge(color="#f97316", label="LLM API", style="bold",
                    fontname="Arial", fontsize="9") >> groq

        # ── Observability ─────────────────────────────────────────────────────
        lmb >> LOG >> cw


# ── Diagram 2 ── ETL / Upload Pipeline ───────────────────────────────────────

def draw_etl_pipeline():
    with Diagram(
        "CEEP — ETL & Upload Pipeline",
        filename="./diagrams/ceep_etl_pipeline",
        outformat=["png"],
        show=False,
        direction="LR",
        graph_attr=DARK,
        node_attr=NODE,
        edge_attr=EDGE,
    ):
        user = Users("User\n(browser)")

        with Cluster("AWS API Layer"):
            apigw = APIGateway("API Gateway")
            lmb = Lambda("Lambda\nFastAPI handler")

        s3_prv = S3("S3 Private\nRaw upload (PDF/EML)")
        s3_pub = S3("S3 Public\nProcessed text")

        with Cluster("ETL Pipeline  (in-Lambda · synchronous)"):
            extract = Python(
                "① Extract\npdfminer  ·  email.parser\nhttpx + BeautifulSoup")
            redact = Python(
                "② PII Redact\nRegex · 18-name safelist\nprotect school entities")
            chunk = Python(
                "③ Chunk\n300 words · 50 overlap\ntiktoken estimate")
            embed = Python(
                "④ Embed\nfastembed ONNX\nBAAI/bge-small-en-v1.5\n384 dims · pre-baked")
            load = Python("⑤ Load\npsycopg2 · pgvector\nON CONFLICT IGNORE")

        with Cluster("RDS PostgreSQL 15"):
            rds = RDS(
                "sources\ndocuments\nchunks  ← pgvector\nevidence_cards\npii_audit")

        step = Edge(color="#38bdf8", style="bold",
                    fontname="Arial", fontsize="9")
        dback = Edge(color="#4ade80", style="dashed",
                     fontname="Arial", fontsize="9")

        user >> Edge(color="#38bdf8", label="POST /documents/upload") >> apigw
        apigw >> step >> lmb
        user >> Edge(color="#fbbf24", label="PUT (pre-signed URL)") >> s3_prv
        lmb >> Edge(color="#c084fc", label="download bytes") >> s3_prv
        lmb >> step >> extract
        extract >> step >> redact
        redact >> step >> chunk
        chunk >> step >> embed
        embed >> step >> load
        load >> Edge(color="#4ade80",
                     label="INSERT chunks + embeddings") >> rds
        lmb >> Edge(color="#64748b", label="clean text",
                    style="dashed") >> s3_pub


# ── Diagram 3 ── Search & RAG Query Flow ─────────────────────────────────────

def draw_rag_flow():
    with Diagram(
        "CEEP — Search & RAG Query Flow",
        filename="./diagrams/ceep_rag_flow",
        outformat=["png"],
        show=False,
        direction="LR",
        graph_attr=DARK,
        node_attr=NODE,
        edge_attr=EDGE,
    ):
        user = Users("User\n(AskPage / SearchPage)")
        apigw = APIGateway("API Gateway\nHTTP API")

        with Cluster("Lambda  —  RAG Pipeline"):
            embed_q = Python(
                "① Embed Query\nfastembed ONNX (384-dim)\nlocal ONNX runtime")
            search = Python(
                "② Hybrid Search\n0.7 × pgvector ANN  (<=>)\n0.3 × PostgreSQL FTS\nre-ranked by combined score")
            ctx = Python("③ Build Context\nTop-K chunks\nnumbered [N] markers")
            llm_call = Python(
                "④ Invoke LLM\nGroq llama-3.1-8b-instant\ncite-only-from-context prompt")
            parse = Python("⑤ Parse Response\nJSON: answer + citations[]")
            audit = Python(
                "⑥ Audit Log\nrag_queries table\nlatency · tokens · chunk_ids")

        with Cluster("RDS PostgreSQL + pgvector"):
            rds = RDS(
                "chunks\n  ↳ HNSW index (ANN)\n  ↳ GIN tsvector (FTS)\nevidence_cards\nrag_queries  (audit)")

        groq = Internet(
            "Groq Cloud\nllama-3.1-8b-instant\nTemp 0.3 · max 4096 tok")
        cw = Cloudwatch("CloudWatch\nlatency · tokens · errors")

        step = Edge(color="#38bdf8", style="bold",
                    fontname="Arial", fontsize="9")
        dback = Edge(color="#4ade80", style="dashed",
                     fontname="Arial", fontsize="9")
        llmout = Edge(color="#f97316", style="bold",
                      fontname="Arial", fontsize="9")

        user >> Edge(color="#38bdf8", label="POST /rag/query") >> apigw
        apigw >> step >> embed_q
        embed_q >> step >> search
        search >> Edge(color="#c084fc", label="ANN + FTS query") >> rds
        rds >> dback >> search
        search >> step >> ctx
        ctx >> step >> llm_call
        llm_call >> llmout >> groq
        groq >> dback >> llm_call
        llm_call >> step >> parse
        parse >> step >> audit
        audit >> Edge(color="#64748b", label="INSERT rag_query") >> rds
        parse >> RESULT >> user
        audit >> Edge(color="#64748b", style="dotted") >> cw


# ── Diagram 4 ── CDK Infrastructure Stacks ───────────────────────────────────

def draw_cdk_stacks():
    from diagrams.aws.network import VPC

    with Diagram(
        "CEEP — CDK Infrastructure Stacks",
        filename="./diagrams/ceep_cdk_stacks",
        outformat=["png"],
        show=False,
        direction="TB",
        graph_attr={**DARK, "splines": "curved",
                    "ranksep": "1.4", "bgcolor": "white"},
        node_attr=NODE,
        edge_attr=EDGE,
    ):
        cdk = Codecommit(
            "AWS CDK v2 (Python)\n4 stacks · account 563142504525\nus-east-1")

        with Cluster("StorageStack  ·  Tier 3"):
            vpc = VPC("VPC\n2 AZs · NAT t3.nano (~$3/mo)")
            kms = KMS("KMS CMK\nalias/ceep-cmk · auto-rotate")
            s3_prv = S3("S3 Private Uploads\nSSE-KMS · 90-day lifecycle")
            s3_pub = S3("S3 Public Docs\nSSE-S3")
            s3_fe = S3("S3 Frontend\nVersioned · static assets")
            rds = RDS(
                "RDS PostgreSQL 15\ndb.t3.micro · private subnet\npgvector extension")
            sm = SecretsManager(
                "Secrets Manager\nDB creds (auto-rotated)\nGroq API key")

        with Cluster("ComputeStack  ·  Tier 2"):
            ecr = ECR("ECR\nDocker image\nlinux/amd64")
            lmb = Lambda(
                "Lambda\n1 GB · 120 s · VPC private\nFastAPI + Mangum")
            apigw = APIGateway(
                "API Gateway\nHTTP API · 10 routes\nCORS configured")

        with Cluster("FrontendStack  ·  Tier 1"):
            cf = CloudFront(
                "CloudFront\nHTTPS · OAC · SPA routing\nd3voaboc02j1x3.cloudfront.net")

        with Cluster("EtlStack  ·  (future async)"):
            glue = Glue("Glue\nasync ETL jobs\n(planned — not active)")

        prov = Edge(color="#4ade80", label="provisions",
                    fontname="Arial", fontsize="9")
        dep = Edge(color="#fbbf24", label="depends on",
                   style="dashed", fontname="Arial", fontsize="9")

        cdk >> prov >> vpc
        cdk >> prov >> kms
        cdk >> prov >> s3_prv
        cdk >> prov >> s3_pub
        cdk >> prov >> s3_fe
        cdk >> prov >> rds
        cdk >> prov >> sm
        cdk >> prov >> ecr
        cdk >> prov >> lmb
        cdk >> prov >> apigw
        cdk >> prov >> cf
        cdk >> prov >> glue

        lmb >> dep >> rds
        lmb >> dep >> sm
        lmb >> dep >> s3_prv
        cf >> dep >> s3_fe
        apigw >> dep >> lmb


# ── HTML viewer generator ─────────────────────────────────────────────────────

def generate_html_viewer():
    diagrams_meta = [
        (
            "ceep_architecture.svg",
            "Full Architecture",
            "Complete AWS 3-tier cloud architecture — CloudFront CDN → API Gateway → Lambda (FastAPI) → RDS/pgvector + S3",
            "#38bdf8",
        ),
        (
            "ceep_etl_pipeline.svg",
            "ETL Pipeline",
            "Document ingestion: pre-signed S3 upload → PII redaction → 300-word chunking → fastembed ONNX → pgvector INSERT",
            "#4ade80",
        ),
        (
            "ceep_rag_flow.svg",
            "RAG Query Flow",
            "Hybrid search + RAG: query embedding → 70% ANN + 30% FTS → context assembly → Groq Llama 3.1 → grounded answer",
            "#f97316",
        ),
        (
            "ceep_cdk_stacks.svg",
            "CDK Stacks",
            "AWS CDK v2 (Python) — StorageStack → ComputeStack → FrontendStack → EtlStack (future) with explicit dependencies",
            "#c084fc",
        ),
    ]

    panels = []
    tab_buttons = []

    for i, (filename, title, description, color) in enumerate(diagrams_meta):
        p = Path(filename)
        if p.exists():
            svg_raw = p.read_text(encoding="utf-8")
            # Strip XML / DOCTYPE declarations so SVG embeds cleanly
            svg_raw = re.sub(r"<\?xml[^?]*\?>", "", svg_raw)
            svg_raw = re.sub(r"<!DOCTYPE[^>]*>", "", svg_raw)
            # Make SVG responsive
            svg_raw = re.sub(
                r"(<svg\b[^>]*?)(\bwidth=\"[^\"]*\")",
                r'\1width="100%"',
                svg_raw, count=1,
            )
            svg_raw = re.sub(
                r"(<svg\b[^>]*?)(\bheight=\"[^\"]*\")",
                r'\1height="100%"',
                svg_raw, count=1,
            )
            svg_raw = svg_raw.strip()
        else:
            svg_raw = f'<svg xmlns="http://www.w3.org/2000/svg"><text fill="#e2e8f0" x="20" y="40">File not found: {filename}</text></svg>'

        active = "active" if i == 0 else ""
        tab_buttons.append(
            f'<button class="tab-btn {active}" data-tab="{i}" style="--accent:{color}" onclick="switchTab({i})">'
            f'  <span class="tab-dot" style="background:{color}"></span>'
            f'  {title}'
            f'</button>'
        )
        panels.append(
            f'<div class="diagram-panel {active}" id="panel-{i}">'
            f'  <div class="panel-header">'
            f'    <h2 style="color:{color}">{title}</h2>'
            f'    <p class="panel-desc">{description}</p>'
            f'  </div>'
            f'  <div class="svg-container" id="svg-{i}">{svg_raw}</div>'
            f'</div>'
        )

    tab_buttons_html = "\n        ".join(tab_buttons)
    panels_html = "\n    ".join(panels)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CEEP Architecture Diagrams</title>
  <style>
    /* ── Reset & base ──────────────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: #020617;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}

    /* ── Header ────────────────────────────────────────────────────────────── */
    header {{
      padding: 1.5rem 2rem 1rem;
      border-bottom: 1px solid #1e293b;
      background: linear-gradient(180deg, #0f172a 0%, transparent 100%);
    }}
    header h1 {{
      font-size: 1.6rem;
      font-weight: 700;
      background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      letter-spacing: -0.02em;
    }}
    header p {{
      color: #64748b;
      font-size: 0.85rem;
      margin-top: 0.3rem;
    }}

    /* ── Tab bar ───────────────────────────────────────────────────────────── */
    .tab-bar {{
      display: flex;
      gap: 0.4rem;
      padding: 1rem 2rem 0;
      flex-wrap: wrap;
      border-bottom: 1px solid #1e293b;
      background: #0f172a;
    }}
    .tab-btn {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.5rem 1.1rem;
      border: 1px solid #334155;
      border-bottom: none;
      border-radius: 8px 8px 0 0;
      background: #1e293b;
      color: #94a3b8;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
      font-family: inherit;
    }}
    .tab-btn:hover {{
      background: #334155;
      color: #e2e8f0;
    }}
    .tab-btn.active {{
      background: #020617;
      color: #e2e8f0;
      border-color: var(--accent);
      border-bottom-color: #020617;
      position: relative;
      z-index: 1;
    }}
    .tab-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      flex-shrink: 0;
    }}

    /* ── Main content ──────────────────────────────────────────────────────── */
    main {{
      flex: 1;
      padding: 1.5rem 2rem;
    }}

    /* ── Diagram panel ─────────────────────────────────────────────────────── */
    .diagram-panel {{
      display: none;
      flex-direction: column;
      gap: 1rem;
      height: calc(100vh - 220px);
    }}
    .diagram-panel.active {{ display: flex; }}

    .panel-header h2 {{
      font-size: 1.15rem;
      font-weight: 600;
    }}
    .panel-desc {{
      color: #64748b;
      font-size: 0.8rem;
      margin-top: 0.25rem;
      max-width: 80ch;
    }}

    .svg-container {{
      flex: 1;
      border: 1px solid #1e293b;
      border-radius: 12px;
      overflow: hidden;
      background: #0f172a;
      position: relative;
      min-height: 0;
      cursor: grab;
    }}
    .svg-container:active {{ cursor: grabbing; }}
    .svg-container > svg {{
      width: 100%;
      height: 100%;
      display: block;
    }}

    /* ── Animated edges (Graphviz SVG targets) ─────────────────────────────── */

    /* All edge paths: animated flowing dashes */
    .svg-container .edge path {{
      stroke-dasharray: 10 5;
      animation: flowDash 1.4s linear infinite;
    }}

    /* Arrowheads pulse in sync */
    .svg-container .edge polygon {{
      animation: arrowPulse 1.4s ease-in-out infinite;
    }}

    @keyframes flowDash {{
      to {{ stroke-dashoffset: -15; }}
    }}
    @keyframes arrowPulse {{
      0%, 100% {{ opacity: 0.7; }}
      50%       {{ opacity: 1.0; }}
    }}

    /* Node hover: glow */
    .svg-container .node image,
    .svg-container .node polygon,
    .svg-container .node ellipse {{
      transition: filter 0.25s, transform 0.25s;
      transform-origin: center;
    }}
    .svg-container .node:hover image {{
      filter: brightness(1.35) drop-shadow(0 0 8px rgba(56, 189, 248, 0.8));
    }}
    .svg-container .node:hover polygon,
    .svg-container .node:hover ellipse {{
      filter: drop-shadow(0 0 6px rgba(56, 189, 248, 0.6));
    }}
    /* Clusters pulse on hover */
    .svg-container .cluster polygon {{
      transition: stroke 0.2s, fill 0.2s;
    }}
    .svg-container .cluster:hover polygon {{
      stroke: #38bdf8;
      filter: drop-shadow(0 0 4px rgba(56, 189, 248, 0.4));
    }}

    /* Entrance animation for panels */
    @keyframes fadeSlide {{
      from {{ opacity: 0; transform: translateY(12px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .diagram-panel.active {{
      animation: fadeSlide 0.35s ease-out;
    }}

    /* ── Legend ────────────────────────────────────────────────────────────── */
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      padding: 0.75rem 1rem;
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 8px;
      flex-shrink: 0;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.75rem;
      color: #94a3b8;
    }}
    .legend-line {{
      width: 28px;
      height: 3px;
      border-radius: 2px;
    }}
    .legend-line.dashed {{
      background: repeating-linear-gradient(
        90deg,
        currentColor 0px,
        currentColor 6px,
        transparent 6px,
        transparent 10px
      );
    }}

    /* ── Footer ────────────────────────────────────────────────────────────── */
    footer {{
      text-align: center;
      padding: 0.75rem;
      color: #334155;
      font-size: 0.72rem;
      border-top: 1px solid #1e293b;
    }}

    /* ── Controls ───────────────────────────────────────────────────────────── */
    .controls {{
      position: absolute;
      bottom: 12px;
      right: 12px;
      display: flex;
      gap: 6px;
      z-index: 10;
    }}
    .ctrl-btn {{
      background: #1e293b;
      border: 1px solid #334155;
      color: #94a3b8;
      font-size: 1rem;
      width: 32px;
      height: 32px;
      border-radius: 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
      font-family: monospace;
    }}
    .ctrl-btn:hover {{ background: #334155; color: #e2e8f0; }}

    /* Toggle animation button */
    .anim-toggle {{
      position: absolute;
      top: 12px;
      right: 12px;
      background: #1e293b;
      border: 1px solid #334155;
      color: #38bdf8;
      font-size: 0.72rem;
      padding: 4px 10px;
      border-radius: 20px;
      cursor: pointer;
      z-index: 10;
      transition: all 0.15s;
    }}
    .anim-toggle:hover {{ background: #334155; }}
    .anim-toggle.paused {{ color: #64748b; }}
  </style>
</head>
<body>
  <header>
    <h1>CEEP — Architecture Diagrams</h1>
    <p>Community Evidence &amp; Engagement Platform  ·  AWS Cloud (us-east-1)  ·  Generated with diagrams-as-code</p>
  </header>

  <nav class="tab-bar">
    {tab_buttons_html}
  </nav>

  <main>
    {panels_html}
  </main>

  <!-- Legend (shared) -->
  <div style="padding: 0 2rem 0.75rem">
    <div class="legend">
      <div class="legend-item">
        <div class="legend-line" style="background:#38bdf8"></div> HTTPS request
      </div>
      <div class="legend-item">
        <div class="legend-line dashed" style="color:#4ade80"></div> Data / result
      </div>
      <div class="legend-item">
        <div class="legend-line dashed" style="color:#fbbf24"></div> Deploy / provision
      </div>
      <div class="legend-item">
        <div class="legend-line" style="background:#c084fc"></div> Secrets
      </div>
      <div class="legend-item">
        <div class="legend-line" style="background:#f97316"></div> LLM API call
      </div>
      <div class="legend-item">
        <div class="legend-line dashed" style="color:#64748b"></div> Logs / audit
      </div>
    </div>
  </div>

  <footer>
    CEEP · Built with <a href="https://diagrams.mingrammer.com" style="color:#475569">diagrams-as-code</a>
    (mingrammer/diagrams v0.25) · Graphviz SVG · Animated via CSS stroke-dashoffset
  </footer>

  <script>
    // ── Tab switching ─────────────────────────────────────────────────────────
    function switchTab(idx) {{
      document.querySelectorAll('.tab-btn').forEach((b, i) => {{
        b.classList.toggle('active', i === idx);
      }});
      document.querySelectorAll('.diagram-panel').forEach((p, i) => {{
        p.classList.toggle('active', i === idx);
      }});
    }}

    // ── Pan & zoom ────────────────────────────────────────────────────────────
    document.querySelectorAll('.svg-container').forEach(container => {{
      let scale = 1, tx = 0, ty = 0;
      let dragging = false, startX, startY, startTx, startTy;

      const svg = container.querySelector('svg');

      function applyTransform() {{
        svg.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
        svg.style.transformOrigin = '0 0';
      }}

      // Mouse wheel zoom
      container.addEventListener('wheel', e => {{
        e.preventDefault();
        const rect = container.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const delta = e.deltaY < 0 ? 1.12 : 0.89;
        const newScale = Math.min(4, Math.max(0.3, scale * delta));
        tx = mx - (mx - tx) * (newScale / scale);
        ty = my - (my - ty) * (newScale / scale);
        scale = newScale;
        applyTransform();
      }}, {{ passive: false }});

      // Drag to pan
      container.addEventListener('mousedown', e => {{
        dragging = true;
        startX = e.clientX; startY = e.clientY;
        startTx = tx; startTy = ty;
      }});
      document.addEventListener('mousemove', e => {{
        if (!dragging) return;
        tx = startTx + e.clientX - startX;
        ty = startTy + e.clientY - startY;
        applyTransform();
      }});
      document.addEventListener('mouseup', () => {{ dragging = false; }});

      // Double-click to reset
      container.addEventListener('dblclick', () => {{
        scale = 1; tx = 0; ty = 0; applyTransform();
      }});

      // Inject control buttons
      const controls = document.createElement('div');
      controls.className = 'controls';
      controls.innerHTML = `
        <button class="ctrl-btn" title="Zoom in"  onclick="zoomBtn(this.closest('.svg-container'), 1.2)">+</button>
        <button class="ctrl-btn" title="Zoom out" onclick="zoomBtn(this.closest('.svg-container'), 0.83)">−</button>
        <button class="ctrl-btn" title="Reset"    onclick="resetZoom(this.closest('.svg-container'))">⊙</button>
      `;
      container.appendChild(controls);

      // Animate toggle
      const toggle = document.createElement('button');
      toggle.className = 'anim-toggle';
      toggle.textContent = '⏸ Pause flow';
      toggle.onclick = () => {{
        const paused = toggle.classList.toggle('paused');
        toggle.textContent = paused ? '▶ Play flow' : '⏸ Pause flow';
        container.style.setProperty('--anim-state', paused ? 'paused' : 'running');
        container.querySelectorAll('.edge path, .edge polygon').forEach(el => {{
          el.style.animationPlayState = paused ? 'paused' : 'running';
        }});
      }};
      container.appendChild(toggle);
    }});

    function zoomBtn(container, factor) {{
      const svg = container.querySelector('svg');
      const t = new DOMMatrix(getComputedStyle(svg).transform);
      const cx = container.clientWidth / 2;
      const cy = container.clientHeight / 2;
      const newScale = Math.min(4, Math.max(0.3, t.a * factor));
      const tx = cx - (cx - t.e) * (newScale / t.a);
      const ty = cy - (cy - t.f) * (newScale / t.a);
      svg.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{newScale}})`;
      svg.style.transformOrigin = '0 0';
    }}

    function resetZoom(container) {{
      const svg = container.querySelector('svg');
      svg.style.transform = '';
    }}

    // ── Keyboard shortcuts ────────────────────────────────────────────────────
    document.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {{
        const active = document.querySelector('.tab-btn.active');
        const btns = [...document.querySelectorAll('.tab-btn')];
        const idx = btns.indexOf(active);
        const next = e.key === 'ArrowRight'
          ? (idx + 1) % btns.length
          : (idx - 1 + btns.length) % btns.length;
        switchTab(next);
      }}
      if (e.key >= '1' && e.key <= '4') switchTab(Number(e.key) - 1);
    }});
  </script>
</body>
</html>
"""

    Path("architecture_viewer.html").write_text(html, encoding="utf-8")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Generating CEEP architecture diagrams...")

    draw_system_architecture()
    print("  OK  ceep_architecture.svg")

    draw_etl_pipeline()
    print("  OK  ceep_etl_pipeline.svg")

    draw_rag_flow()
    print("  OK  ceep_rag_flow.svg")

    draw_cdk_stacks()
    print("  OK  ceep_cdk_stacks.svg")

    generate_html_viewer()
    print("  OK  architecture_viewer.html")

    viewer = Path("architecture_viewer.html").resolve()
    print(f"\nOpening {viewer}")
    webbrowser.open(viewer.as_uri())


if __name__ == "__main__":
    main()
