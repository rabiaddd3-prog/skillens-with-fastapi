"""Render the SkillLens wordmark ("Skill" + magnifier + "ens") as PDF and PNG for the report,
slides and PDF summary, using the same Source Serif 4 font as the website (bold instance).

Outputs: web/img/logo.pdf, web/img/logo.png (navy on white)
Usage:   python scripts/make_logo.py
"""
import io
from pathlib import Path

import pymupdf
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "img"
NAVY, LENS = (0x14 / 255, 0x21 / 255, 0x3D / 255), (0x2F / 255, 0x5D / 255, 0x9E / 255)

# woff2 (variable) -> static bold TTF in memory
font = TTFont(ROOT / "web" / "fonts" / "source-serif-4-latin.woff2")
font = instantiateVariableFont(font, {"wght": 700, "opsz": 60})
font.flavor = None
buf = io.BytesIO()
font.save(buf)
serif = pymupdf.Font(fontbuffer=buf.getvalue())

size = 48
w_skill, w_ens = serif.text_length("Skill", size), serif.text_length("ens", size)
cap = size * 0.68                     # approximate cap height
lens_w = cap * 0.95
pad = 10
width = pad + w_skill + 4 + lens_w + 2 + w_ens + pad
height = size * 1.25 + 2 * pad
baseline = pad + size * 0.95

doc = pymupdf.open()
page = doc.new_page(width=width, height=height)
tw = pymupdf.TextWriter(page.rect)
tw.append((pad, baseline), "Skill", font=serif, fontsize=size)
tw.append((pad + w_skill + 4 + lens_w + 2, baseline), "ens", font=serif, fontsize=size)
tw.write_text(page, color=NAVY)

# magnifier in place of the L: ring sits on the x-height, handle reaches the baseline
x0 = pad + w_skill + 4
r = lens_w * 0.34
cx, cy = x0 + r + 2, baseline - cap + r + 2
shape = page.new_shape()
shape.draw_circle((cx, cy), r)
shape.finish(color=LENS, width=size * 0.085)
d = r * 0.72
shape.draw_line((cx + d, cy + d), (x0 + lens_w, baseline))
shape.finish(color=LENS, width=size * 0.1, lineCap=1)
shape.commit()

doc.save(OUT / "logo.pdf")
page.get_pixmap(dpi=300, alpha=True).save(OUT / "logo.png")
print("wrote", OUT / "logo.pdf", OUT / "logo.png", f"({width:.0f} x {height:.0f} pt)")
