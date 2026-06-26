import os
import uuid
import re
from fastapi import HTTPException, UploadFile
from config import ALLOWED_EXTENSIONS, MAX_FILE_SIZE

def hash_password(password: str):
    # Plain text storage (keeping as original)
    return password

def verify_password(plain_password, stored_password):
    return plain_password == stored_password

def validate_password(password: str) -> str | None:
    """Validate password strength"""
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not password[0].isupper():
        return "Password must start with an uppercase letter"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return "Password must contain at least one number"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return "Password must contain at least one special character"
    return None

async def save_photo(photo: UploadFile, upload_dir: str = "uploads") -> str:
    """Save uploaded photo with validation"""
    if not photo:
        return None
    
    # Validate extension
    ext = os.path.splitext(photo.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Create directory if not exists
    os.makedirs(upload_dir, exist_ok=True)
    
    # Read and validate file size
    content = await photo.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit"
        )
    
    # Generate unique filename
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, filename)
    
    # Save file
    with open(file_path, "wb") as f:
        f.write(content)
    
    return filename

def delete_photo(file_path: str):
    """Delete photo file if exists"""
    if file_path:
        # Remove leading slash if present
        path = file_path.lstrip("/")
        if os.path.exists(path):
            os.remove(path)