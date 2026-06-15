import os


ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".xls",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".markdown",
    ".properties",
    ".vtt",
    ".mdx",
    ".html",
    ".htm",
}

MAX_CHAT_UPLOAD_FILES = 5
MAX_DAILY_CHAT_UPLOADS = 20
MAX_CHAT_UPLOAD_BYTES = 15 * 1024 * 1024


def is_allowed_chat_upload(filename: str) -> bool:
    if not filename:
        return False
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS
