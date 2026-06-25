import os
import random
import string
import time
import uuid
import smtplib
from email.mime.text import MIMEText
from typing import Optional
from fastapi import (
    FastAPI, Depends, HTTPException, 
    UploadFile, File, Form, Request
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware  # ADD THIS
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, EmailStr
from models import (
    Base, engine, SessionLocal, UserMaster,
    UserType, Theme, SiteMaster, OTPStore, IPSession
)
from utils import validate_password, save_photo, delete_photo
from config import SMTP_EMAIL, SMTP_PASSWORD, UPLOAD_DIR

# Initialize FastAPI FIRST
app = FastAPI(title="Downtime API", version="1.0")

# ===== CORS MIDDLEWARE =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development - allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ===== END CORS =====

# Mount static files AFTER app initialization
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Create tables
Base.metadata.create_all(bind=engine)

# In-memory stores
captcha_store = {}
verified_otp_store = {}

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============ PYDANTIC MODELS ============
class DGRRegister(BaseModel):
    fullName: str
    userName: str
    emailId: EmailStr
    contactNo: str
    userType: int
    siteName: Optional[int] = None
    theme: str
    password: str
    confirmPassword: str

class LoginModel(BaseModel):
    identifier: str
    password: str
    captcha_id: Optional[str] = None
    captcha_text: Optional[str] = None

class ForgotPassword(BaseModel):
    email: str

class VerifyOTP(BaseModel):
    email: str
    otp: str

class ResetPassword(BaseModel):
    email: str
    new_password: str
    confirm_password: str

class SetPassword(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str
    confirm_password: str

class UpdateProfile(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    fullName: Optional[str] = None
    userName: Optional[str] = None
    contactNo: Optional[str] = None
    theme: Optional[str] = None

# ============ EMAIL FUNCTION ============
def send_otp_email(to_email: str, otp: str):
    """Send OTP via email using SMTP"""
    try:
        msg = MIMEText(f"Your OTP is {otp}\n\nValid for 10 minutes.")
        msg["Subject"] = "Password Reset OTP"
        msg["From"] = SMTP_EMAIL
        msg["To"] = to_email

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ============ ENDPOINTS ============

@app.get("/")
def root():
    return {"status": "running", "message": "Downtime API is active"}

@app.get("/sites")
def get_sites(db: Session = Depends(get_db)):
    return db.query(SiteMaster).all()

@app.get("/themes")
def get_themes(db: Session = Depends(get_db)):
    return db.query(Theme).all()

@app.get("/usertypes")
def get_usertypes(db: Session = Depends(get_db)):
    return db.query(UserType).all()

@app.post("/register")
async def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    usertype_id: int = Form(...),
    fullname: str = Form(None),
    contactno: str = Form(None),
    theme: str = Form(None),
    sitemaster_id: int = Form(None),
    captcha_id: Optional[str] = Form(None),
    captcha_text: Optional[str] = Form(None),
    photo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    # Check if usertype exists
    usertype = db.query(UserType).filter(UserType.id == usertype_id).first()
    if not usertype:
        raise HTTPException(status_code=400, detail="Invalid usertype")
    
    # Check if user exists
    existing = db.query(UserMaster).filter(
        or_(UserMaster.username == username, UserMaster.emailid == email)
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Username or Email already exists")
    
    # Validate captcha ONLY for Vendor (usertype_id = 1)
    if usertype_id == 1:  # Vendor
        if not captcha_id or not captcha_text:
            raise HTTPException(status_code=400, detail="Captcha required for vendor registration")
        
        captcha_data = captcha_store.get(captcha_id)
        if not captcha_data:
            raise HTTPException(status_code=400, detail="Invalid captcha ID")
        
        if time.time() > captcha_data["expires"]:
            del captcha_store[captcha_id]
            raise HTTPException(status_code=400, detail="Captcha expired")
        
        if captcha_data["text"].upper() != captcha_text.upper():
            raise HTTPException(status_code=400, detail="Invalid captcha text")
        
        # Remove used captcha
        del captcha_store[captcha_id]
    else:
        # For other usertypes, remove captcha if provided (optional)
        if captcha_id and captcha_id in captcha_store:
            del captcha_store[captcha_id]
    
    # Validate password
    error = validate_password(password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    # Save photo if provided
    photo_path = None
    if photo and photo.filename:
        try:
            photo_path = await save_photo(photo, UPLOAD_DIR)
        except HTTPException as e:
            raise e
    
    # Create user
    new_user = UserMaster(
        username=username,
        emailid=email,
        password=password,  # Plain text (as per original)
        fullname=fullname,
        contactno=contactno,
        usertype_id=usertype_id,
        theme=theme,
        sitemaster_id=sitemaster_id,
        photo=photo_path
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "message": "User registered successfully",
        "user_id": new_user.id,
        "username": new_user.username,
        "usertype": usertype.usertype
    }

@app.get("/captcha")
def get_captcha():
    """Generate captcha"""
    captcha_text = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    captcha_id = str(random.randint(100000, 999999))
    
    captcha_store[captcha_id] = {
        "text": captcha_text,
        "expires": time.time() + 120
    }
    
    return {
        "captcha_id": captcha_id,
        "captcha_text": captcha_text
    }

@app.post("/login")
async def login(
    data: LoginModel,
    request: Request,
    db: Session = Depends(get_db)
):
    """Login endpoint with conditional captcha validation"""
    # Find user by username or email
    user = db.query(UserMaster).filter(
        or_(UserMaster.username == data.identifier, UserMaster.emailid == data.identifier)
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get usertype
    usertype = db.query(UserType).filter(UserType.id == user.usertype_id).first()
    
    # Validate captcha ONLY for Vendor (usertype_id = 1)
    if usertype and usertype.id == 1:
        if not data.captcha_id or not data.captcha_text:
            raise HTTPException(status_code=400, detail="Captcha required for vendor login")
        
        captcha_data = captcha_store.get(data.captcha_id)
        if not captcha_data:
            raise HTTPException(status_code=400, detail="Invalid captcha ID")
        
        if time.time() > captcha_data["expires"]:
            del captcha_store[data.captcha_id]
            raise HTTPException(status_code=400, detail="Captcha expired")
        
        if captcha_data["text"].upper() != data.captcha_text.upper():
            raise HTTPException(status_code=400, detail="Invalid captcha text")
        
        del captcha_store[data.captcha_id]
    
    # Verify password
    if user.password != data.password:
        raise HTTPException(status_code=401, detail="Invalid password")
    
    # ===== SAVE IP SESSION =====
    ip = request.client.host if request.client else "Unknown"
    user_agent = request.headers.get("user-agent", "Unknown")
    
    # Simple browser detection
    browser = "Unknown"
    if "Chrome" in user_agent:
        browser = "Chrome"
    elif "Firefox" in user_agent:
        browser = "Firefox"
    elif "Safari" in user_agent:
        browser = "Safari"
    elif "Edge" in user_agent:
        browser = "Edge"
    
    os_name = "Unknown"
    if "Windows" in user_agent:
        os_name = "Windows"
    elif "Mac" in user_agent:
        os_name = "macOS"
    elif "Linux" in user_agent:
        os_name = "Linux"
    elif "Android" in user_agent:
        os_name = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        os_name = "iOS"
    
    new_session = IPSession(
        session_id=str(uuid.uuid4()),
        username=user.username,
        email=user.emailid,
        role=usertype.usertype if usertype else "user",
        ip=ip,
        country="Unknown",
        region="Unknown",
        city="Unknown",
        browser=browser,
        os=os_name,
        user_agent=user_agent
    )
    db.add(new_session)
    db.commit()
    # ===== END SAVE =====
    
    return {
        "success": True,
        "message": "Login successful",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.emailid,
            "fullname": user.fullname,
            "usertype": usertype.usertype if usertype else None,
            "usertype_id": user.usertype_id
        }
    }

@app.post("/get_otp")
def get_otp(
    data: ForgotPassword,
    db: Session = Depends(get_db)
):
    """Send OTP for password reset"""
    user = db.query(UserMaster).filter(UserMaster.emailid == data.email).first()
    if not user:
        raise HTTPException(404, "Email not found")
    
    otp = str(random.randint(1000, 9999))
    
    # Delete existing OTP
    db.query(OTPStore).filter(OTPStore.email == data.email).delete()
    
    # Store new OTP
    db.add(OTPStore(
        email=data.email,
        otp=otp,
        expires=str(time.time() + 600)  # 10 minutes
    ))
    db.commit()
    
    # Send email
    if send_otp_email(data.email, otp):
        return {"success": True, "message": "OTP sent to your email"}
    else:
        raise HTTPException(500, "Failed to send OTP email")

@app.post("/verify_otp")
def verify_otp(
    data: VerifyOTP,
    db: Session = Depends(get_db)
):
    """Verify OTP"""
    otp_data = db.query(OTPStore).filter(OTPStore.email == data.email).first()
    
    if not otp_data:
        raise HTTPException(status_code=400, detail="OTP not found")
    
    if time.time() > float(otp_data.expires):
        db.delete(otp_data)
        db.commit()
        raise HTTPException(status_code=400, detail="OTP expired")
    
    if otp_data.otp != data.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    # Mark as verified
    verified_otp_store[data.email] = True
    
    # Delete OTP
    db.delete(otp_data)
    db.commit()
    
    return {"success": True, "message": "OTP Verified Successfully"}

@app.post("/reset_password")
def reset_password(
    data: ResetPassword,
    db: Session = Depends(get_db)
):
    """Reset password after OTP verification"""
    if not verified_otp_store.get(data.email):
        raise HTTPException(status_code=400, detail="Please verify OTP first")
    
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    error = validate_password(data.new_password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    user = db.query(UserMaster).filter(UserMaster.emailid == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update password
    user.password = data.new_password
    db.commit()
    
    # Clear verification
    verified_otp_store.pop(data.email, None)
    
    return {"success": True, "message": "Password Reset Successfully"}

@app.post("/set_password")
def set_password(
    data: SetPassword,
    db: Session = Depends(get_db)
):
    """Set password for existing user"""
    if not data.username and not data.email:
        raise HTTPException(status_code=400, detail="Username or Email required")
    
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    error = validate_password(data.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    user = db.query(UserMaster).filter(
        or_(
            UserMaster.username == data.username,
            UserMaster.emailid == data.email
        )
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.password = data.password
    db.commit()
    
    return {"success": True, "message": "Password Set Successfully"}

@app.put("/update_profile")
def update_profile(
    data: UpdateProfile,
    db: Session = Depends(get_db)
):
    """Update user profile"""
    if not data.username and not data.email:
        raise HTTPException(status_code=400, detail="Username or Email required")
    
    user = db.query(UserMaster).filter(
        or_(
            UserMaster.username == data.username,
            UserMaster.emailid == data.email
        )
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update fields
    if data.fullName:
        user.fullname = data.fullName
    if data.userName:
        # Check if username already taken
        existing = db.query(UserMaster).filter(
            UserMaster.username == data.userName,
            UserMaster.id != user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = data.userName
    if data.contactNo:
        user.contactno = data.contactNo
    if data.theme:
        user.theme = data.theme
    
    db.commit()
    db.refresh(user)
    
    return {
        "success": True,
        "message": "Profile Updated Successfully",
        "user": {
            "id": user.id,
            "fullname": user.fullname,
            "username": user.username,
            "email": user.emailid,
            "contactno": user.contactno,
            "theme": user.theme,
            "photo": user.photo
        }
    }

@app.get("/get_liveip")
async def get_liveip(request: Request):
    """Get client IP address"""
    ip = request.client.host if request.client else "Unknown"
    return {"success": True, "ip": ip}

@app.get("/ip_history")
def ip_history(
    username: str,
    db: Session = Depends(get_db)
):
    """Get IP history for user"""
    sessions = db.query(IPSession).filter(IPSession.username == username).all()
    
    data = []
    for row in sessions:
        data.append({
            "id": row.id,
            "session_id": row.session_id,
            "username": row.username,
            "email": row.email,
            "ip": row.ip,
            "city": row.city,
            "country": row.country,
            "browser": row.browser,
            "os": row.os,
        })
    
    return {"success": True, "count": len(data), "data": data}

@app.put("/user/update-photo/{username}")
async def update_profile_photo(
    username: str,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Update user profile photo"""
    user = db.query(UserMaster).filter(UserMaster.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Validate file type
    if photo.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Only JPG/PNG allowed")
    
    try:
        # Delete old photo
        if user.photo:
            delete_photo(user.photo)
        
        # Save new photo
        photo_path = await save_photo(photo, UPLOAD_DIR)
        user.photo = photo_path
        
        db.commit()
        db.refresh(user)
        
        return {
            "message": "Profile photo updated successfully",
            "photo": user.photo
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating photo: {str(e)}")