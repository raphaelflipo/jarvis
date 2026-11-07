"""
Lecture, analyse et conversion de (presque) tous les formats de fichiers — 100 % local et gratuit.

  • Texte et structure : PDF, Word (.docx .doc .rtf .odt), Excel (.xlsx .xls .csv), PowerPoint (.pptx), HTML, Markdown, code, e-mails…
  • OCR intégré de macOS (framework Vision, hors ligne, FR/EN) : images, photos, captures, PDF scannés.
  • Aperçu Quick Look : Pixelmator (.pxd), Photoshop (.psd), Illustrator, Affinity, Sketch, Keynote/Pages/Numbers, HEIC…
  • Exports Canva (PDF, PNG, JPG, PPTX, MP4) : lus comme n'importe quel fichier de ces formats.
  • Conversion : sips (images), textutil (documents), Keynote/Pages/Numbers (iWork ↔ Office ↔ PDF), PDF → images.
"""
from __future__ import annotations

import email
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from email import policy
from pathlib import Path

import config
import security
from registry import I, P, S, Ctx, backup, path_lock, tool, trunc
from security import BLOCKED, NORMAL, RISKY, SAFE

IMG = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
TEXTUTIL = {".doc", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive", ".wordml"}
IWORK = {".pages": "Pages", ".key": "Keynote", ".numbers": "Numbers"}
DESIGN = {".pxd", ".pxm", ".psd", ".ai", ".sketch", ".fig", ".af", ".afdesign", ".afphoto", ".afpub", ".eps", ".indd",
          ".canva", ".xd", ".svg"}
AV = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".aiff", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
TMP = Path(tempfile.gettempdir()) / "jarvis-files"


def _env():
    e = os.environ.copy()
    e["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + e.get("PATH", "")
    return e


def _run(argv, timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=_env())


def _tmpdir() -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=TMP))


# ====================================================================== OCR (Vision)
def ocr(path: Path) -> str:
    """Reconnaissance de texte macOS (hors ligne). Renvoie '' si indisponible."""
    try:
        import Vision
        from Foundation import NSURL
    except Exception:
        return ""
    try:
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(True)
        try:
            req.setRecognitionLanguages_(["fr-FR", "en-US", "de-DE", "es-ES", "it-IT"])
        except Exception:
            pass
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(path)), None)
        res = handler.performRequests_error_([req], None)
        if isinstance(res, tuple) and not res[0]:
            return ""
        lines = []
        for obs in req.results() or []:
            c = obs.topCandidates_(1)
            if c and len(c):
                lines.append(str(c[0].string()))
        return "\n".join(lines)
    except Exception:
        return ""


# ====================================================================== rendus visuels
def to_png(path: Path) -> Path | None:
    """Image quelconque (HEIC, TIFF, WebP, BMP, GIF…) → PNG temporaire."""
    if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return path
    out = _tmpdir() / (path.stem + ".png")
    if shutil.which("sips"):
        r = _run(["sips", "-s", "format", "png", str(path), "--out", str(out)])
        if r.returncode == 0 and out.exists():
            return out
    try:
        from PIL import Image
        Image.open(path).convert("RGB").save(out)
        return out
    except Exception:
        return ql_preview(path)


def ql_preview(path: Path, size: int = 1800) -> Path | None:
    """Aperçu Quick Look (fonctionne pour .pxd, .psd, Keynote, Pages, Sketch, Affinity… si l'app est installée)."""
    if not shutil.which("qlmanage"):
        return None
    d = _tmpdir()
    try:
        _run(["qlmanage", "-t", "-s", str(size), "-o", str(d), str(path)], timeout=60)
    except subprocess.TimeoutExpired:
        return None
    pngs = list(d.glob("*.png"))
    return pngs[0] if pngs else None


def iwork_preview(path: Path) -> Path | None:
    """Les fichiers Keynote/Pages/Numbers contiennent un aperçu (preview.jpg ou QuickLook/Preview.pdf)."""
    names = ("preview.jpg", "QuickLook/Thumbnail.jpg", "QuickLook/Preview.pdf", "preview-web.jpg")
    d = _tmpdir()
    try:
        if path.is_dir():
            for n in names:
                if (path / n).exists():
                    shutil.copy(path / n, d / Path(n).name)
                    return d / Path(n).name
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for n in names:
                    if n in z.namelist():
                        out = d / Path(n).name
                        out.write_bytes(z.read(n))
                        return out
    except (OSError, zipfile.BadZipFile):
        pass
    return None


def pdf_pages(path: Path, pages: list[int] | None = None, scale: float = 2.0, limit: int = 20) -> list[Path]:
    try:
        import pypdfium2 as pdfium
    except Exception:
        p = ql_preview(path)
        return [p] if p else []
    doc = pdfium.PdfDocument(str(path))
    n = len(doc)
    idx = [i for i in (pages or range(min(n, limit))) if 0 <= i < n][:limit]
    d = _tmpdir()
    out = []
    for i in idx:
        img = doc[i].render(scale=scale).to_pil()
        f = d / f"page-{i + 1:03d}.png"
        img.save(f)
        out.append(f)
    return out


def visuals(path: Path, pages: list[int] | None = None) -> list[Path]:
    """Images représentant le fichier (pour la vision et l'OCR)."""
    ext = path.suffix.lower()
    if ext in IMG:
        p = to_png(path)
        return [p] if p else []
    if ext == ".pdf":
        return pdf_pages(path, pages, limit=6)
    if ext in IWORK:
        p = iwork_preview(path)
        if p and p.suffix == ".pdf":
            return pdf_pages(p, pages, limit=6)
        if p:
            return [p]
    p = ql_preview(path)
    return [p] if p else []


# ====================================================================== extraction de texte
def _docx(p: Path) -> str:
    import docx
    d = docx.Document(str(p))
    parts = []
    for para in d.paragraphs:
        if para.text.strip():
            st = para.style.name if para.style is not None else ""
            parts.append(("# " if st.startswith("Heading") or st == "Title" else "") + para.text)
    for t in d.tables:
        parts.append("")
        for row in t.rows:
            parts.append("| " + " | ".join(c.text.strip() for c in row.cells) + " |")
    n_img = sum(1 for r in d.part.rels.values() if "image" in r.reltype)
    if n_img:
        parts.append(f"\n[{n_img} image(s) dans le document — analyze_file pour l'aspect visuel]")
    return "\n".join(parts)


def _pptx(p: Path) -> str:
    from pptx import Presentation
    out = []
    for i, s in enumerate(Presentation(str(p)).slides, 1):
        out.append(f"--- Diapo {i} ---")
        for shp in s.shapes:
            if shp.has_text_frame and shp.text_frame.text.strip():
                out.append(shp.text_frame.text)
            elif getattr(shp, "has_table", False) and shp.has_table:
                for row in shp.table.rows:
                    out.append("| " + " | ".join(c.text for c in row.cells) + " |")
            elif getattr(shp, "has_chart", False) and shp.has_chart:
                try:
                    ch = shp.chart
                    cats = list(ch.plots[0].categories)
                    for se in ch.series:
                        out.append(f"[graphique] {se.name}: " + ", ".join(f"{c}={v}" for c, v in zip(cats, se.values)))
                except Exception:
                    out.append("[graphique]")
            elif shp.shape_type == 13:
                out.append("[image]")
        if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
            out.append("[notes] " + s.notes_slide.notes_text_frame.text)
    return "\n".join(out)


def _xlsx(p: Path) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(str(p), data_only=False)
    out = []
    for ws in wb.worksheets:
        out.append(f"--- Feuille « {ws.title} » ({ws.max_row} lignes × {ws.max_column} colonnes) ---")
        for r_i, row in enumerate(ws.iter_rows(max_row=500, values_only=True), 1):
            if any(v is not None for v in row):
                out.append(f"{r_i}: " + "\t".join("" if v is None else str(v) for v in row))
        if ws.max_row > 500:
            out.append(f"… {ws.max_row - 500} lignes de plus")
    return "\n".join(out)


def _xls(p: Path) -> str:
    try:
        import xlrd
    except ImportError:
        return "[.xls : module xlrd absent — convertis en .xlsx avec convert_file]"
    book = xlrd.open_workbook(str(p))
    out = []
    for sh in book.sheets():
        out.append(f"--- Feuille « {sh.name} » ({sh.nrows}×{sh.ncols}) ---")
        for r in range(min(sh.nrows, 500)):
            out.append(f"{r + 1}: " + "\t".join(str(c.value) for c in sh.row(r)))
    return "\n".join(out)


def _pdf(p: Path) -> str:
    from pypdf import PdfReader
    rd = PdfReader(str(p))
    n = len(rd.pages)
    texts = [(pg.extract_text() or "") for pg in rd.pages[:80]]
    total = sum(len(t.strip()) for t in texts)
    head = f"[PDF · {n} page(s)]"
    if total >= 80 * min(n, 80) * 0.5 or total > 4000:
        return head + "\n" + "\n\n".join(f"--- Page {i + 1} ---\n{t}" for i, t in enumerate(texts) if t.strip())
    # PDF scanné ou image : OCR
    parts = []
    for i, img in enumerate(pdf_pages(p, limit=15)):
        txt = ocr(img)
        if txt:
            parts.append(f"--- Page {i + 1} (OCR) ---\n{txt}")
    if parts:
        return head + " — texte reconnu par OCR\n" + "\n\n".join(parts)
    return head + "\n" + "\n".join(texts) + "\n[peu de texte : PDF probablement scanné ; utilise analyze_file]"


def _image(p: Path) -> str:
    info = ""
    try:
        from PIL import Image
        with Image.open(p) as im:
            info = f"{im.width}×{im.height} px, {im.mode}"
            exif = im.getexif() if hasattr(im, "getexif") else {}
            if exif and exif.get(36867) or exif and exif.get(306):
                info += f", prise le {exif.get(36867) or exif.get(306)}"
    except Exception:
        if shutil.which("sips"):
            r = _run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(p)])
            m = re.findall(r"pixel(?:Width|Height): (\d+)", r.stdout)
            if len(m) == 2:
                info = f"{m[0]}×{m[1]} px"
    txt = ocr(p) or (ocr(to_png(p)) if p.suffix.lower() in (".heic", ".heif", ".webp") else "")
    return (f"[Image {p.suffix[1:].upper()} · {info}]\n" +
            (f"Texte détecté (OCR) :\n{txt}" if txt else "Aucun texte détecté.") +
            "\n→ Pour décrire le contenu visuel, utilise analyze_file.")


def _email(p: Path) -> str:
    msg = email.message_from_bytes(p.read_bytes(), policy=policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body and body.get_content_type() == "text/html":
        from bs4 import BeautifulSoup
        text = BeautifulSoup(text, "html.parser").get_text("\n")
    atts = [a.get_filename() for a in msg.iter_attachments()]
    return (f"De : {msg['from']}\nÀ : {msg['to']}\nDate : {msg['date']}\nObjet : {msg['subject']}\n"
            + (f"Pièces jointes : {', '.join(filter(None, atts))}\n" if atts else "") + f"\n{text}")


def _meta(p: Path) -> str:
    if shutil.which("mdls"):
        r = _run(["mdls", "-name", "kMDItemDurationSeconds", "-name", "kMDItemPixelWidth", "-name", "kMDItemPixelHeight",
                  "-name", "kMDItemCodecs", "-name", "kMDItemTitle", "-name", "kMDItemAuthors", "-name", "kMDItemContentCreationDate", str(p)])
        lines = [ln for ln in r.stdout.splitlines() if "(null)" not in ln]
        return "\n".join(lines)
    return ""


def extract(p: Path) -> str:
    ext = p.suffix.lower()
    if p.is_dir() and ext in IWORK:
        pass
    elif p.is_dir():
        return "\n".join(sorted(x.name for x in p.iterdir())[:200])
    if ext == ".docx":
        return _docx(p)
    if ext == ".pptx":
        return _pptx(p)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx(p)
    if ext == ".xls":
        return _xls(p)
    if ext == ".pdf":
        return _pdf(p)
    if ext in IMG:
        return _image(p)
    if ext in TEXTUTIL and shutil.which("textutil"):
        r = _run(["textutil", "-convert", "txt", "-stdout", str(p)])
        if r.returncode == 0:
            return r.stdout
    if ext == ".eml":
        return _email(p)
    if ext in IWORK or (ext in DESIGN and ext != ".svg"):
        kind = IWORK.get(ext) or "graphique"
        vis = visuals(p)
        txt = "\n".join(filter(None, (ocr(v) for v in vis[:4])))
        return (f"[Fichier {kind} {ext} — aperçu {'disponible' if vis else 'indisponible (app non installée ?)'}]\n"
                + (f"Texte visible (OCR de l'aperçu) :\n{txt}\n" if txt else "")
                + ("→ Contenu complet : convert_file vers pdf/docx/pptx/xlsx (Pages/Keynote/Numbers). " if ext in IWORK else "")
                + "→ Aspect visuel : analyze_file.")
    if ext in AV:
        return f"[Fichier audio/vidéo {ext}]\n{_meta(p)}\n(Transcription non disponible ; analyze_file peut décrire une vidéo via son aperçu.)"
    if ext == ".zip":
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
        return f"[Archive ZIP · {len(names)} éléments]\n" + "\n".join(names[:300]) + "\n→ Décompresse avec run_shell `unzip -o …` pour lire le contenu."
    data = p.read_bytes()[:4_000_000]
    if b"\x00" in data[:4096]:
        return f"[fichier binaire de {p.stat().st_size} octets]\n{_meta(p)}"
    text = data.decode("utf-8", errors="replace")
    if ext == ".json":
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    return text


def is_untrusted(p: Path) -> bool:
    ws = Ctx.workspace()
    roots = [config.HOME / "Downloads", config.HOME / "Library" / "Mail",
             config.HOME / "Library" / "Containers" / "com.apple.mail", ws / "Fichiers reçus"]
    rp = security.resolve(p)
    return any(security.under(rp, security.resolve(r)) for r in roots)


# ====================================================================== outils
def _risk_read(path, **k):
    return security.path_level(P(path), False, Ctx.workspace())


@tool("analyze_file",
      "Analyse VISUELLE d'un fichier avec le modèle vision local + OCR : photo, capture, maquette, affiche, PDF (pages), "
      "diapositives, Pixelmator (.pxd), Photoshop (.psd), Keynote, exports Canva… Pose une question précise.",
      {"path": S("Chemin du fichier"), "question": S("Ce que tu veux savoir (ex. « décris la mise en page et les couleurs »)"),
       "pages": {"type": "array", "items": {"type": "integer"}, "description": "Pages PDF à analyser (1 = première), facultatif"}},
      ["path"], category="read", risk=_risk_read, untrusted=True)
def analyze_file(path: str, question: str = "Décris précisément ce fichier.", pages: list | None = None):
    p = P(path)
    if not p.exists():
        return __import__("tools").not_found(p)
    vis = visuals(p, [int(x) - 1 for x in pages] if pages else None)
    if not vis:
        return f"[erreur] impossible de produire un aperçu de {p.name} (format non pris en charge par Quick Look ?)"
    vb = Ctx.router.vision_backend if Ctx.router else None
    out = [f"[{p.name} · {len(vis)} aperçu(s)]"]
    for i, v in enumerate(vis[:6], 1):
        label = f"Page/vue {pages[i - 1] if pages and i <= len(pages) else i}"
        txt = ocr(v)
        desc = ""
        if vb:
            try:
                desc = vb.vision(f"{question}\nRéponds en français, de façon précise et structurée.", str(v))
            except Exception as e:
                desc = f"(vision indisponible : {e})"
        out.append(f"--- {label} ---" + (f"\n{desc}" if desc else "") + (f"\n[Texte OCR]\n{txt[:3000]}" if txt else ""))
    if not vb:
        out.append("(Pas de modèle vision installé : seul le texte OCR est disponible. Réglages › Modèle vision.)")
    return trunc("\n".join(out), 16000)


CONV_IMG = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "heic": "heic", "tiff": "tiff", "tif": "tiff", "gif": "gif",
            "bmp": "bmp", "pdf": "pdf"}
CONV_TXT = {"txt", "html", "rtf", "rtfd", "doc", "docx", "odt", "wordml", "webarchive"}
IWORK_EXPORT = {"pdf": "PDF", "docx": "Microsoft Word", "pptx": "Microsoft PowerPoint", "xlsx": "Microsoft Excel",
                "png": "slide images", "jpg": "slide images", "epub": "EPUB"}


def _out_path(src: Path, fmt: str, out: str) -> Path:
    if out:
        return P(out)
    d = src.parent if security.path_level(src.parent / "x", True, Ctx.workspace())[0] == NORMAL else Ctx.workspace() / "Conversions"
    d.mkdir(parents=True, exist_ok=True)
    o = d / f"{src.stem}.{fmt}"
    i = 2
    while o.exists():
        o = d / f"{src.stem} ({i}).{fmt}"
        i += 1
    return o


def _risk_convert(path, to, out="", **k):
    src = P(path)
    lvl, why = security.path_level(src, False, Ctx.workspace())
    if lvl == BLOCKED:
        return lvl, why
    dst = _out_path(src, to.lower().lstrip("."), out) if out else (src.parent / f"{src.stem}.{to}")
    return max(NORMAL, security.path_level(dst, True, Ctx.workspace())[0]), "écriture du fichier converti"


@tool("convert_file",
      "Convertit un fichier : images (png, jpg, heic, tiff, gif, pdf…), documents (docx, doc, rtf, odt, html, txt), "
      "PDF → images (png), Keynote/Pages/Numbers ↔ pptx/docx/xlsx/pdf, PowerPoint/Word/Excel → pdf (via Keynote/Pages/Numbers, "
      "gratuits), et aperçu PNG de tout fichier (Pixelmator .pxd, .psd…).",
      {"path": S("Fichier source"), "to": S("Format cible : pdf, png, jpg, docx, pptx, xlsx, txt, html…"),
       "out": S("Chemin de sortie (facultatif)")}, ["path", "to"], category="write", risk=_risk_convert)
def convert_file(path: str, to: str, out: str = ""):
    src = P(path)
    if not src.exists():
        return f"[erreur] introuvable : {src}"
    fmt = to.lower().lstrip(".")
    ext = src.suffix.lower()
    dst = _out_path(src, "jpg" if fmt == "jpeg" else fmt, out)
    with path_lock(dst):
        backup(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # PDF → images
        if ext == ".pdf" and fmt in ("png", "jpg", "jpeg"):
            pages = pdf_pages(src, limit=200)
            folder = dst.with_suffix("")
            folder.mkdir(parents=True, exist_ok=True)
            for pg in pages:
                target = folder / (pg.stem + (".png" if fmt == "png" else ".jpg"))
                if fmt == "png":
                    shutil.copy(pg, target)
                else:
                    from PIL import Image
                    Image.open(pg).convert("RGB").save(target, quality=90)
            return f"{len(pages)} page(s) exportée(s) dans {folder}"
        # images (sips)
        if (ext in IMG or ext == ".pdf") and fmt in CONV_IMG:
            r = _run(["sips", "-s", "format", CONV_IMG[fmt], str(src), "--out", str(dst)])
            return f"Converti : {dst}" if r.returncode == 0 else f"[erreur] sips : {r.stderr.strip()[:300]}"
        # iWork / Office via Keynote, Pages, Numbers
        app = IWORK.get(ext) or {".pptx": "Keynote", ".ppt": "Keynote", ".docx": "Pages", ".doc": "Pages",
                                 ".xlsx": "Numbers", ".xls": "Numbers", ".csv": "Numbers"}.get(ext)
        if app and fmt in IWORK_EXPORT and not (ext in TEXTUTIL and fmt in CONV_TXT):
            if not Path(f"/Applications/{app}.app").exists():
                return f"[erreur] {app} n'est pas installé (gratuit sur l'App Store)."
            script = (f'set src to POSIX file "{src}"\nset dst to POSIX file "{dst}"\n'
                      f'tell application "{app}"\n  set d to open src\n  delay 1\n'
                      f'  export d to dst as {IWORK_EXPORT[fmt]}\n  close d saving no\nend tell')
            r = _run(["osascript", "-e", script], timeout=300)
            if r.returncode == 0 and dst.exists():
                return f"Converti avec {app} : {dst}"
            return f"[erreur] {app} : {(r.stderr or r.stdout).strip()[:300]} (autorise Jarvis à piloter {app} si macOS le demande)"
        # documents texte (textutil)
        if fmt in CONV_TXT and (ext in TEXTUTIL or ext in (".docx", ".txt", ".md")):
            r = _run(["textutil", "-convert", fmt, str(src), "-output", str(dst)])
            return f"Converti : {dst}" if r.returncode == 0 else f"[erreur] textutil : {r.stderr.strip()[:300]}"
        # aperçu PNG de n'importe quoi
        if fmt in ("png", "jpg", "jpeg"):
            v = visuals(src)
            if v:
                if fmt == "png":
                    shutil.copy(v[0], dst)
                else:
                    from PIL import Image
                    Image.open(v[0]).convert("RGB").save(dst, quality=92)
                return f"Aperçu exporté : {dst}"
    return f"[erreur] conversion {ext} → {fmt} non prise en charge"
