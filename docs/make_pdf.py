#!/usr/bin/env python3
"""Build proposal_analysis.pdf from the proposal and outcome-analysis markdown.

A small, dependency-free markdown subset is rendered with ReportLab:
headings, paragraphs, bullets, blockquotes, fenced code, and pipe tables.
"""
from __future__ import annotations

import html
import os
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "proposal_analysis.pdf")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1x", parent=styles["Heading1"], fontSize=17,
                    spaceAfter=10, textColor=colors.HexColor("#1a3a5c"))
H2 = ParagraphStyle("H2x", parent=styles["Heading2"], fontSize=13,
                    spaceBefore=12, spaceAfter=6,
                    textColor=colors.HexColor("#24608c"))
H3 = ParagraphStyle("H3x", parent=styles["Heading3"], fontSize=11,
                    spaceBefore=9, spaceAfter=4,
                    textColor=colors.HexColor("#2c3e50"))
BODY = ParagraphStyle("Bodyx", parent=styles["BodyText"], fontSize=9.2,
                      leading=13, alignment=TA_LEFT, spaceAfter=6)
BULLET = ParagraphStyle("Bulletx", parent=BODY, leftIndent=14, bulletIndent=4)
QUOTE = ParagraphStyle("Quotex", parent=BODY, leftIndent=14,
                       textColor=colors.HexColor("#555555"),
                       backColor=colors.HexColor("#eef3f8"),
                       borderPadding=6, spaceBefore=4, spaceAfter=8)
CODE = ParagraphStyle("Codex", parent=BODY, fontName="Courier", fontSize=7.5,
                      leading=9.5, backColor=colors.HexColor("#f4f4f4"),
                      borderPadding=5, spaceAfter=8)


def inline(s: str) -> str:
    s = html.escape(s.strip())
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r'<font face="Courier" size="8">\1</font>', s)
    return s


def parse(md: str) -> list:
    lines = md.splitlines()
    story = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        if line.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(html.escape(lines[i]))
                i += 1
            i += 1
            story.append(Paragraph("<br/>".join(buf), CODE))
            continue

        if line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), H3))
            i += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), H2))
            i += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), H1))
            i += 1
            continue

        if line.startswith("> "):
            story.append(Paragraph(inline(line[2:]), QUOTE))
            i += 1
            continue

        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                data = [[Paragraph(inline(c), BODY) for c in row] for row in rows]
                ncols = max(len(r) for r in data)
                avail = 175 * mm
                widths = [avail / ncols] * ncols
                t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce8f2")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c6d4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.append(t)
                story.append(Spacer(1, 8))
            continue

        if re.match(r"^\s*[-*] ", line):
            story.append(Paragraph(inline(line.strip()[2:]), BULLET,
                                   bulletText="•"))
            i += 1
            continue

        if re.match(r"^\s*\d+\. ", line):
            txt = re.sub(r"^\s*\d+\. ", "", line)
            story.append(Paragraph(inline(txt), BULLET, bulletText="•"))
            i += 1
            continue

        # Paragraph: join wrapped lines until a structural line.
        buf = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith("#") or nxt.startswith("|") or
                    nxt.startswith(">") or nxt.startswith("```") or
                    re.match(r"^[-*] ", nxt) or re.match(r"^\d+\. ", nxt)):
                break
            buf.append(nxt)
            i += 1
        story.append(Paragraph(inline(" ".join(buf)), BODY))

    return story


def main() -> None:
    proposal = open(os.path.join(HERE, "05_proposal.md"), encoding="utf-8").read()
    analysis = open(os.path.join(HERE, "06_analysis.md"), encoding="utf-8").read()

    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="Delay-Tolerant Data Mule — Proposal and Analysis",
        author="Delay-Tolerant Data Mule Project",
    )
    story = parse(proposal)
    story.append(PageBreak())
    story.append(Paragraph("Final Analysis of Outcomes", H1))
    story.extend(parse(analysis))
    doc.build(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
