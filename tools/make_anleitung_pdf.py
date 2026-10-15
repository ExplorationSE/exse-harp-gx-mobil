"""Erzeugt docs/Anleitung_Windows_Online.pdf aus ANLEITUNG_WINDOWS.md (markdown + Playwright/Chromium).
   python tools/make_anleitung_pdf.py"""
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
md = (ROOT / "ANLEITUNG_WINDOWS.md").read_text(encoding="utf-8")
import re  # noqa: E402
md = re.sub(r"^> \[!(\w+)\]\n", "", md, flags=re.M)
body = markdown.markdown(md, extensions=["tables", "fenced_code"])
ver = re.search(r'__version__ = "([^"]+)"', (ROOT / "harp" / "__init__.py").read_text(encoding="utf-8")).group(1)
html = f"""<!doctype html><html lang="de"><meta charset="utf-8"><style>
body{{font:10.5pt/1.45 "DejaVu Sans",Arial,sans-serif;color:#111;margin:0}}
h1{{font-size:17pt;margin:0 0 8pt}}h2{{font-size:13pt;margin:14pt 0 4pt;border-bottom:1px solid #ccc}}h3{{font-size:11pt}}
code,pre{{font-family:"DejaVu Sans Mono",Consolas,monospace;font-size:9pt}}pre{{background:#f4f4f4;padding:6pt;white-space:pre-wrap}}
blockquote{{border-left:3px solid #0ea5e9;margin:6pt 0;padding:2pt 8pt;background:#f0f9ff}}
table{{border-collapse:collapse;font-size:9pt}}td,th{{border:1px solid #bbb;padding:3pt 5pt;vertical-align:top}}
</style><body>{body}</body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.set_content(html)
    pg.pdf(path=str(ROOT / "docs" / "Anleitung_Windows_Online.pdf"), format="A4", print_background=True,
           margin={"top": "16mm", "bottom": "16mm", "left": "16mm", "right": "16mm"},
           display_header_footer=True, header_template="<span></span>",
           footer_template=f'<div style="font-size:8pt;width:100%;text-align:center;color:#666">ExSE Harp GX Mobil {ver} – Anleitung Windows/Online · Seite <span class="pageNumber"></span>/<span class="totalPages"></span></div>')
    b.close()
print("docs/Anleitung_Windows_Online.pdf")
