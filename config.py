from dotenv import load_dotenv
from urllib.parse import quote_plus
import os

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

DATABASE_URL = (
    f"postgresql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

SECRET_KEY = os.getenv("SECRET_KEY")

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

MAX_FILE_SIZE = 5 * 1024 * 1024 

ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png"]