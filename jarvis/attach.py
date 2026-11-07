"""Pièces jointes : types de fichiers, tailles, bloc transmis à l'agent."""
from __future__ import annotations

from pathlib import Path

KINDS = {
    "pdf": {".pdf"}, "word": {".docx", ".doc", ".rtf", ".odt", ".pages"},
    "excel": {".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".numbers", ".ods"},
    "slides": {".pptx", ".ppt", ".key", ".odp"},
    "image": {".png", ".jpg", ".jpeg", ".heic", ".heif", ".gif", ".webp", ".tif", ".tiff", ".bmp", ".svg"},
    "design": {".pxd", ".pxm", ".psd", ".ai", ".sketch", ".fig", ".af", ".afdesign", ".afphoto", ".afpub", ".eps", ".indd", ".canva"},
    "audio": {".mp3", ".m4a", ".wav", ".aac", ".flac", ".aiff"}, "video": {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"},
    "archive": {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"},
    "code": {".py", ".swift", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".cpp", ".c", ".h", ".hpp", ".qml",
             ".java", ".kt", ".go", ".rs", ".sh", ".md", ".txt", ".yaml", ".yml", ".xml", ".sql"},
}
KIND_LABEL = {"pdf": "PDF", "word": "document", "excel": "tableur", "slides": "présentation", "image": "image",
              "design": "fichier graphique", "audio": "audio", "video": "vidéo", "archive": "archive", "code": "texte/code",
              "other": "fichier"}


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    return next((k for k, exts in KINDS.items() if ext in exts), "other")


def human_size(n: int) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


def attachments_block(files: list[dict]) -> str:
    if not files:
        return ""
    lines = [f"- {f['path']}  ({KIND_LABEL.get(f.get('kind', 'other'), 'fichier')}, {human_size(f.get('size', 0))})" for f in files]
    return ("\n\n[Pièces jointes envoyées par l'utilisateur]\n" + "\n".join(lines) +
            "\nLis-les avant de répondre : `read_file` (texte, tableaux, OCR des scans et images) ou `analyze_file` "
            "(aspect visuel : photos, maquettes, diapositives, graphiques). Elles sont dans l'espace de travail.")
