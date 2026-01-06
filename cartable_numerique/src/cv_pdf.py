from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
import os


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16)/255 for i in (0, 2, 4))


def export_cv_pdf(
    path,
    *,
    template,
    accent_hex,
    photo_path,
    full_name,
    title_line,
    contact,
    sections
):
    c = canvas.Canvas(path, pagesize=A4)
    w, h = A4
    accent = colors.Color(*_hex_to_rgb(accent_hex))
    margin = 2 * cm

    # HEADER
    if template == "Classique":
        c.setFillColor(accent)
        c.rect(0, h - 3*cm, w, 3*cm, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(margin, h - 1.5*cm, full_name)
        c.setFont("Helvetica", 11)
        c.drawString(margin, h - 2.3*cm, title_line)
        c.setFont("Helvetica", 10)
        c.drawString(margin, h - 2.8*cm, contact)
        y = h - 4*cm

    else:
        left = 6*cm
        c.setFillColor(accent)
        c.rect(0, 0, left, h, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(left + margin, h - 2*cm, full_name)
        c.setFont("Helvetica", 11)
        c.drawString(left + margin, h - 2.8*cm, title_line)
        c.setFont("Helvetica", 10)
        c.drawString(left + margin, h - 3.4*cm, contact)
        y = h - 4.5*cm

    c.setFillColor(colors.black)
    for title, content in sections:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, y, title)
        y -= 0.5*cm
        c.setFont("Helvetica", 10)
        for line in content.split("\n"):
            c.drawString(margin, y, line)
            y -= 0.4*cm
        y -= 0.4*cm

    c.save()
