from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png"]