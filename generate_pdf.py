#!/usr/bin/env python3
"""Generate PDF from LEECHV3_REPORT.md"""

import markdown
from weasyprint import HTML

# Read markdown
with open("LEECHV3_REPORT.md") as f:
    md_content = f.read()

# Convert markdown to HTML
html_body = markdown.markdown(
    md_content,
    extensions=["tables", "fenced_code"],
)

# Wrap in styled HTML document
html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page {{
        size: A4;
        margin: 2cm 2.5cm;
        @bottom-center {{
            content: "LeechV3 Bot Report — Confidential";
            font-size: 8pt;
            color: #999;
        }}
        @bottom-right {{
            content: "Page " counter(page) " of " counter(pages);
            font-size: 8pt;
            color: #999;
        }}
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        font-size: 10.5pt;
        line-height: 1.6;
        color: #1a1a1a;
        max-width: 100%;
    }}
    h1 {{
        font-size: 24pt;
        font-weight: 700;
        border-bottom: 3px solid #2563eb;
        padding-bottom: 10px;
        margin-top: 0;
        color: #111;
    }}
    h2 {{
        font-size: 16pt;
        font-weight: 600;
        color: #1e40af;
        margin-top: 30px;
        border-bottom: 1px solid #ddd;
        padding-bottom: 6px;
        page-break-after: avoid;
    }}
    h3 {{
        font-size: 12pt;
        font-weight: 600;
        color: #1e3a5f;
        margin-top: 20px;
        page-break-after: avoid;
    }}
    p {{
        margin: 8px 0;
    }}
    strong {{
        color: #111;
    }}
    code {{
        background: #f3f4f6;
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 9.5pt;
        font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    }}
    pre {{
        background: #1e293b;
        color: #e2e8f0;
        padding: 14px 18px;
        border-radius: 6px;
        font-size: 8.5pt;
        line-height: 1.5;
        overflow-x: auto;
        white-space: pre-wrap;
        word-wrap: break-word;
        page-break-inside: avoid;
    }}
    pre code {{
        background: none;
        padding: 0;
        color: #e2e8f0;
        font-size: 8.5pt;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0;
        font-size: 9.5pt;
        page-break-inside: avoid;
    }}
    th {{
        background: #1e40af;
        color: white;
        padding: 8px 10px;
        text-align: left;
        font-weight: 600;
        font-size: 9pt;
    }}
    td {{
        padding: 6px 10px;
        border-bottom: 1px solid #e5e7eb;
    }}
    tr:nth-child(even) {{
        background: #f9fafb;
    }}
    tr:last-child td {{
        font-weight: 600;
    }}
    hr {{
        border: none;
        border-top: 1px solid #ddd;
        margin: 25px 0;
    }}
    ul, ol {{
        margin: 8px 0;
        padding-left: 24px;
    }}
    li {{
        margin: 4px 0;
    }}
    blockquote {{
        border-left: 4px solid #2563eb;
        margin: 12px 0;
        padding: 8px 16px;
        background: #eff6ff;
        color: #1e3a5f;
    }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

# Generate PDF
HTML(string=html_doc).write_pdf("LEECHV3_REPORT.pdf")
print("Generated: LEECHV3_REPORT.pdf")
