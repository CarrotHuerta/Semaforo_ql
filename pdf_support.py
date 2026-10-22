"""Text handling for the built-in PDF fonts used by the reports."""


def pdf_text(value):
    # Helvetica supports Latin-1. Keep accented names and readable equivalents
    # for common UI symbols; JSON/XLSX retain the original Unicode text.
    text = str(value).translate(str.maketrans({
        "→": "->", "←": "<-", "—": "-", "–": "-", "€": "EUR",
        "≥": ">=", "≤": "<=", "…": "...", "“": '"', "”": '"', "’": "'",
    }))
    return text.encode("latin-1", "replace").decode("latin-1")
