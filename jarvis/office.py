"""Bureautique : Word (.docx), PowerPoint (.pptx) et Excel (.xlsx) — mises en page, images et graphiques."""
from __future__ import annotations

import datetime
import re
from pathlib import Path

import security
from registry import P, S, Ctx, backup, path_lock, tool

LAWN = "4CB82C"   # vert pelouse : thème par défaut de Jarvis


def _num(v):
    if isinstance(v, str) and not v.startswith("="):
        s = v.strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
        if re.fullmatch(r"-?\d+([.,]\d+)?", s):
            return float(s.replace(",", ".")) if re.search(r"[.,]", s) else int(s)
        if re.fullmatch(r"-?\d+([.,]\d+)?%", s):
            return float(s[:-1].replace(",", ".")) / 100
    return v


def _risk(path, **k):
    return security.path_level(P(path), True, Ctx.workspace())


def _hex(c: str, default=LAWN) -> str:
    c = (c or default).strip().lstrip("#")
    return c.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", c) else default


# =================================================================== WORD
def _image_ok(ip) -> bool:
    """Image présente ET lisible (un faux PNG écrit en texte ne doit pas faire planter le document)."""
    try:
        if not ip.exists() or ip.stat().st_size < 60:
            return False
        from PIL import Image
        with Image.open(ip) as im:
            im.verify()
        return True
    except Exception:
        return False


@tool("create_word",
      "Crée un .docx depuis du Markdown : '# Titre', '## Sous-titre', '- puce', '1. liste', '**gras**', '*italique*', "
      "'`code`', tableaux '| a | b |', images '![légende](chemin.png)', '---' = saut de page, '> citation'.",
      {"path": S("Chemin .docx"), "markdown": S("Contenu Markdown"), "theme": S("Couleur des titres (hex)")},
      ["path", "markdown"], category="write", risk=_risk)
def create_word(path: str, markdown: str, theme: str = ""):
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor
    color = RGBColor.from_string(_hex(theme, "2E7D1A"))
    missing: list[str] = []
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        try:
            d.styles[name].font.color.rgb = color
        except KeyError:
            pass

    def runs(par, text):
        for tok in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)", text):
            if not tok:
                continue
            if tok.startswith("**"):
                par.add_run(tok[2:-2]).bold = True
            elif tok.startswith("`"):
                r = par.add_run(tok[1:-1])
                r.font.name = "Menlo"
                r.font.size = Pt(10)
            elif tok.startswith("*") and len(tok) > 2:
                par.add_run(tok[1:-1]).italic = True
            else:
                par.add_run(tok)

    lines, i = markdown.splitlines(), 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.strip().startswith("```"):
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            par = d.add_paragraph()
            r = par.add_run("\n".join(code))
            r.font.name, r.font.size = "Menlo", Pt(9)
            i += 1
            continue
        if ln.strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                t = d.add_table(rows=len(rows), cols=ncol)
                t.style = "Light Grid Accent 6"
                for r_i, row in enumerate(rows):
                    for c_i in range(ncol):
                        cell = t.cell(r_i, c_i)
                        cell.text = ""
                        runs(cell.paragraphs[0], row[c_i] if c_i < len(row) else "")
                        if r_i == 0:
                            for rn in cell.paragraphs[0].runs:
                                rn.bold = True
            continue
        img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)", ln.strip())
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if img:
            ip = P(img.group(2))
            if _image_ok(ip):
                d.add_picture(str(ip), width=Inches(6))
                d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                if img.group(1):
                    cap = d.add_paragraph(img.group(1))
                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cap.runs[0].italic = True
            else:
                missing.append(ip.name)
        elif m:
            n = len(m.group(1))
            d.add_heading(m.group(2), level=0 if n == 1 else min(n - 1, 3))
        elif re.match(r"^\s*[-*•]\s+", ln):
            style = "List Bullet 2" if re.match(r"^\s{2,}", ln) else "List Bullet"
            runs(d.add_paragraph(style=style), re.sub(r"^\s*[-*•]\s+", "", ln))
        elif re.match(r"^\s*\d+[.)]\s+", ln):
            runs(d.add_paragraph(style="List Number"), re.sub(r"^\s*\d+[.)]\s+", "", ln))
        elif ln.strip().startswith(">"):
            runs(d.add_paragraph(style="Intense Quote"), ln.strip().lstrip(">").strip())
        elif ln.strip() == "---":
            d.add_page_break()
        elif ln.strip():
            runs(d.add_paragraph(), ln)
        i += 1
    p = P(path)
    with path_lock(p):
        backup(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        d.save(str(p))
    note = f"\n⚠ Image(s) introuvable(s) ou illisible(s), ignorée(s) : {', '.join(missing)}." if missing else ""
    return f"Document Word créé : {p}{note}"


# =================================================================== POWERPOINT
def _chart(slide, spec, x, y, w, h, accent):
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    kind = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "barh": XL_CHART_TYPE.BAR_CLUSTERED, "line": XL_CHART_TYPE.LINE_MARKERS,
            "pie": XL_CHART_TYPE.PIE, "doughnut": XL_CHART_TYPE.DOUGHNUT, "area": XL_CHART_TYPE.AREA}.get(
        str(spec.get("type", "bar")).lower(), XL_CHART_TYPE.COLUMN_CLUSTERED)
    data = CategoryChartData()
    data.categories = [str(c) for c in spec.get("categories", [])]
    series = spec.get("series") or {}
    if isinstance(series, list):
        series = {s.get("name", f"Série {i + 1}"): s.get("values", []) for i, s in enumerate(series)}
    for name, vals in series.items():
        data.add_series(str(name), [float(_num(v)) if _num(v) not in (None, "") else 0 for v in vals])
    gframe = slide.shapes.add_chart(kind, x, y, w, h, data)
    ch = gframe.chart
    ch.has_legend = len(series) > 1 or kind in (XL_CHART_TYPE.PIE, XL_CHART_TYPE.DOUGHNUT)
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
    if kind not in (XL_CHART_TYPE.PIE, XL_CHART_TYPE.DOUGHNUT):
        palette = [accent, RGBColor(0x1F, 0x2A, 0x24), RGBColor(0x9B, 0xD7, 0x7E), RGBColor(0x6B, 0x72, 0x80)]
        for i, s in enumerate(ch.series):
            fill = s.format.fill if kind != XL_CHART_TYPE.LINE_MARKERS else None
            if fill is not None:
                fill.solid()
                fill.fore_color.rgb = palette[i % len(palette)]
            else:
                s.format.line.color.rgb = palette[i % len(palette)]
    if spec.get("title"):
        ch.has_title = True
        ch.chart_title.text_frame.text = str(spec["title"])


@tool("create_powerpoint",
      "Crée une présentation .pptx 16:9 soignée. slides = liste d'objets {layout, title, bullets[], notes, ...} avec layout : "
      "'bullets' (défaut), 'two_columns' (left[], right[]), 'image' (image: chemin, bullets[]), "
      "'chart' (chart: {type: bar|barh|line|pie|doughnut|area, categories[], series: {nom: [valeurs]}, title}), "
      "'big_number' (number, caption), 'quote' (text, author), 'section'. theme = couleur hex.",
      {"path": S("Chemin .pptx"), "title": S("Titre"), "subtitle": S("Sous-titre"),
       "slides": {"type": "array", "items": {"type": "object"}, "description": "Diapositives"},
       "theme": S("Couleur principale hex (défaut vert pelouse)")},
      ["path", "title", "slides"], category="write", risk=_risk)
def create_powerpoint(path: str, title: str, slides: list, subtitle: str = "", theme: str = ""):
    missing: list[str] = []
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Inches, Pt
    accent = RGBColor.from_string(_hex(theme))
    dark = RGBColor(0x14, 0x1A, 0x16)
    grey = RGBColor(0x5B, 0x63, 0x5E)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    blank = prs.slide_layouts[6]

    def rect(slide, x, y, w, h, color):
        s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
        s.fill.solid()
        s.fill.fore_color.rgb = color
        s.line.fill.background()
        return s

    def text(slide, x, y, w, h, value, size=20, bold=False, color=dark, align=None):
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        lines = value if isinstance(value, list) else [value]
        for k, ln in enumerate(lines):
            para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
            para.text = str(ln)
            para.font.size, para.font.bold, para.font.color.rgb = Pt(size), bold, color
            if align:
                para.alignment = align
        return tb

    def header(slide, t):
        rect(slide, 0, 0, W, Inches(0.12), accent)
        text(slide, Inches(0.7), Inches(0.45), W - Inches(1.4), Inches(1), t, 32, True, dark)
        rect(slide, Inches(0.72), Inches(1.35), Inches(1.1), Emu(38000), accent)

    def bullets(slide, items, x, y, w, h):
        items = [str(b) for b in (items or [])]
        size = 22 if len(items) <= 5 else 19 if len(items) <= 7 else 16
        tb = slide.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        for k, b in enumerate(items):
            para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
            sub = b.startswith(("  ", "\t", "- "))
            para.text = ("–  " if sub else "•  ") + b.strip().lstrip("-").strip()
            para.level = 1 if sub else 0
            para.font.size = Pt(size - (4 if sub else 0))
            para.font.color.rgb = grey if sub else dark
            para.space_after = Pt(10)
        return tb

    # --- couverture
    s = prs.slides.add_slide(blank)
    rect(s, 0, 0, W, H, RGBColor(0x0E, 0x14, 0x10))
    rect(s, 0, H - Inches(0.35), W, Inches(0.35), accent)
    circ = s.shapes.add_shape(MSO_SHAPE.OVAL, W - Inches(4.2), Inches(-1.2), Inches(5.5), Inches(5.5))
    circ.fill.solid()
    circ.fill.fore_color.rgb = accent
    circ.line.fill.background()
    text(s, Inches(0.9), Inches(2.4), Inches(9), Inches(1.6), title, 46, True, RGBColor(0xFF, 0xFF, 0xFF))
    text(s, Inches(0.9), Inches(4.1), Inches(9), Inches(0.8), subtitle or datetime.date.today().strftime("%d/%m/%Y"),
         22, False, RGBColor(0xC9, 0xE8, 0xBC))

    for n, sd in enumerate(slides, start=2):
        if isinstance(sd, str):
            sd = {"title": sd}
        lay = str(sd.get("layout", "bullets")).lower()
        s = prs.slides.add_slide(blank)
        if lay == "section":
            rect(s, 0, 0, W, H, accent)
            text(s, Inches(0.9), Inches(2.9), Inches(11.5), Inches(1.5), sd.get("title", ""), 44, True, RGBColor(0xFF, 0xFF, 0xFF))
        elif lay == "big_number":
            header(s, sd.get("title", ""))
            text(s, Inches(0.7), Inches(2.2), W - Inches(1.4), Inches(2.2), str(sd.get("number", "")), 110, True, accent, PP_ALIGN.CENTER)
            text(s, Inches(1.5), Inches(4.7), W - Inches(3), Inches(1.2), str(sd.get("caption", "")), 24, False, grey, PP_ALIGN.CENTER)
        elif lay == "quote":
            rect(s, 0, 0, Inches(0.25), H, accent)
            text(s, Inches(1.2), Inches(2.0), Inches(11), Inches(3), f"« {sd.get('text', sd.get('title', ''))} »", 34, True, dark)
            text(s, Inches(1.2), Inches(5.2), Inches(11), Inches(0.8), f"— {sd.get('author', '')}", 20, False, grey)
        elif lay == "two_columns":
            header(s, sd.get("title", ""))
            colw = (W - Inches(2)) / 2
            for k, key in enumerate(("left", "right")):
                x = Inches(0.7) + k * (colw + Inches(0.6))
                if sd.get(f"{key}_title"):
                    text(s, x, Inches(1.7), colw, Inches(0.6), sd[f"{key}_title"], 22, True, accent)
                bullets(s, sd.get(key, []), x, Inches(2.35), colw, Inches(4.5))
        elif lay == "image":
            header(s, sd.get("title", ""))
            ip = P(sd.get("image", "")) if sd.get("image") else None
            has_b = bool(sd.get("bullets"))
            if ip is not None and _image_ok(ip):
                from PIL import Image
                iw, ih = Image.open(ip).size
                maxw, maxh = (Inches(6.6) if has_b else Inches(11.5)), Inches(5.2)
                scale = min(maxw / iw, maxh / ih)
                pw, ph = int(iw * scale), int(ih * scale)
                x = Inches(6.1) if has_b else (W - pw) // 2
                s.shapes.add_picture(str(ip), x, Inches(1.75), pw, ph)
            else:
                if ip is not None:
                    missing.append(ip.name)
                has_b and bullets(s, sd["bullets"], Inches(0.7), Inches(1.8), Inches(11.9), Inches(5))   # pleine largeur
                has_b = False
            if has_b:
                bullets(s, sd["bullets"], Inches(0.7), Inches(1.8), Inches(5.1), Inches(5))
        elif lay == "chart" and sd.get("chart"):
            header(s, sd.get("title", ""))
            has_b = bool(sd.get("bullets"))
            if has_b:
                bullets(s, sd["bullets"], Inches(0.7), Inches(1.8), Inches(4.2), Inches(5))
            _chart(s, sd["chart"], Inches(5.2) if has_b else Inches(0.9), Inches(1.7),
                   Inches(7.5) if has_b else Inches(11.5), Inches(5.3), accent)
        else:
            header(s, sd.get("title", ""))
            bullets(s, sd.get("bullets", []), Inches(0.75), Inches(1.75), W - Inches(1.5), Inches(5.2))
        if lay not in ("section",):
            text(s, W - Inches(1.2), H - Inches(0.55), Inches(0.8), Inches(0.4), str(n), 11, False, grey, PP_ALIGN.RIGHT)
        if sd.get("notes"):
            s.notes_slide.notes_text_frame.text = str(sd["notes"])
    p = P(path)
    with path_lock(p):
        backup(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(p))
    note = (f"\n⚠ Image(s) introuvable(s) ou illisible(s), ignorée(s) : {', '.join(missing)} — ces diapos sont en pleine "
            "largeur, sans image. N'invente pas d'image : crée-la d'abord (graphique, capture…) ou n'en mets pas.") if missing else ""
    return f"Présentation créée : {p} ({len(slides) + 1} diapos, dont 1 de titre){note}"


# =================================================================== EXCEL
@tool("create_excel",
      "Crée un classeur .xlsx. sheets = {\"Feuille\": [[en-têtes…], [valeurs…]]} ; '=' en début de cellule = formule. "
      "charts (facultatif) = [{sheet, type: bar|line|pie, title, data: 'B1:C13' (avec en-têtes), categories: 'A2:A13', anchor: 'E2'}].",
      {"path": S("Chemin .xlsx"), "sheets": {"type": "object", "description": "Feuilles → lignes"},
       "charts": {"type": "array", "items": {"type": "object"}, "description": "Graphiques"}},
      ["path", "sheets"], category="write", risk=_risk)
def create_excel(path: str, sheets: dict, charts: list | None = None):
    import openpyxl
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.cell import range_boundaries
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="D9E7D2")
    for name, rows in sheets.items():
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "-", str(name))[:31])
        for row in rows or []:
            ws.append([_num(v) for v in (row if isinstance(row, list) else [row])])
        if rows:
            for c in ws[1]:
                c.font = Font(bold=True, color="FFFFFF")
                c.fill = PatternFill("solid", fgColor=LAWN)
                c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[1].height = 22
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for r in ws.iter_rows(min_row=2):
                for c in r:
                    c.border = Border(bottom=thin)
                    if isinstance(c.value, float) and 0 < abs(c.value) < 1 and str(rows[0][c.column - 1] if c.column - 1 < len(rows[0]) else "").endswith("%"):
                        c.number_format = "0.0%"
        for col in range(1, ws.max_column + 1):
            width = max((len(str(ws.cell(r, col).value)) for r in range(1, ws.max_row + 1)
                         if ws.cell(r, col).value is not None), default=8)
            ws.column_dimensions[get_column_letter(col)].width = min(max(width + 3, 10), 60)
    for ch in charts or []:
        try:
            ws = wb[ch.get("sheet") or wb.sheetnames[0]]
            kind = str(ch.get("type", "bar")).lower()
            c = {"line": LineChart, "pie": PieChart}.get(kind, BarChart)()
            c.title = ch.get("title")
            c.height, c.width = 8, 16
            mc, mr, xc, xr = range_boundaries(ch["data"])
            c.add_data(Reference(ws, min_col=mc, min_row=mr, max_col=xc, max_row=xr), titles_from_data=True)
            if ch.get("categories"):
                a, b, cc, dd = range_boundaries(ch["categories"])
                c.set_categories(Reference(ws, min_col=a, min_row=b, max_col=cc, max_row=dd))
            if kind != "pie" and c.series:
                c.series[0].graphicalProperties.solidFill = LAWN
                c.series[0].graphicalProperties.line.solidFill = LAWN
            ws.add_chart(c, ch.get("anchor") or f"{get_column_letter(ws.max_column + 2)}2")
        except Exception as e:
            return f"[erreur] graphique {ch} : {e}"
    p = P(path)
    with path_lock(p):
        backup(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(p))
    return f"Classeur Excel créé : {p} ({len(sheets)} feuille(s), {len(charts or [])} graphique(s))"


@tool("edit_office",
      "Modifie un fichier Office existant : remplacer un texte dans .docx/.pptx, ou écrire une cellule .xlsx "
      "(find='Feuille1!B3', replace=valeur ou formule).",
      {"path": S("Chemin"), "find": S("Texte à trouver ou cellule"), "replace": S("Nouveau texte / valeur")},
      category="write", risk=_risk)
def edit_office(path: str, find: str, replace: str):
    p = P(path)
    if not p.exists():
        return f"[erreur] introuvable : {p}"
    with path_lock(p):
        backup(p)
        ext = p.suffix.lower()
        if ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(str(p))
            sheet, cell = find.split("!", 1) if "!" in find else (wb.active.title, find)
            sheet = sheet.strip("'")
            if sheet not in wb.sheetnames:
                return f"[erreur] feuille « {sheet} » absente ({', '.join(wb.sheetnames)})"
            wb[sheet][cell] = _num(replace)
            wb.save(str(p))
            return f"{sheet}!{cell} = {replace}"
        if ext == ".docx":
            import docx
            d = docx.Document(str(p))
            pars = list(d.paragraphs) + [cp for t in d.tables for r in t.rows for c in r.cells for cp in c.paragraphs]
        elif ext == ".pptx":
            from pptx import Presentation
            d = Presentation(str(p))
            pars = [pa for s in d.slides for shp in s.shapes if shp.has_text_frame for pa in shp.text_frame.paragraphs]
        else:
            return "[erreur] format non géré (docx, pptx, xlsx)"
        n = 0
        for par in pars:
            hit = False
            for run in par.runs:
                if find in run.text:
                    run.text = run.text.replace(find, replace)
                    n += 1
                    hit = True
            full = "".join(r.text for r in par.runs)
            if not hit and find in full and par.runs:
                par.runs[0].text = full.replace(find, replace)
                for r in par.runs[1:]:
                    r.text = ""
                n += 1
        d.save(str(p))
    return f"{n} remplacement(s) dans {p}" if n else f"[erreur] « {find} » introuvable dans {p}"
