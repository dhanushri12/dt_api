import os
import random
import string
import time
import uuid
import smtplib
from email.mime.text import MIMEText
from typing import Optional
from datetime import datetime
from fastapi import (
    FastAPI, Depends, HTTPException, 
    UploadFile, File, Form, Request, APIRouter
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, literal
from pydantic import BaseModel, EmailStr
from models import (
    Base, engine, SessionLocal, UserMaster,
    UserType, Theme, SiteMaster, OTPStore, IPSession,
    WTGEntry, TypeMaster, AlarmMaster, FeederEntry, ChooseCategory,
    ResponseDuration
)
from utils import validate_password, save_photo, delete_photo
from config import SMTP_EMAIL, SMTP_PASSWORD, UPLOAD_DIR
import httpx
import ipaddress
from zoneinfo import ZoneInfo
from user_agents import parse as ua_parse


# INITIALIZATION

app = FastAPI(title="Downtime API", version="1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


Base.metadata.create_all(bind=engine, checkfirst=True)


captcha_store = {}
verified_otp_store = {}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



# ROUTERS

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


user_router = APIRouter(prefix="/users", tags=["Users"])


ip_router = APIRouter(prefix="/ip", tags=["IP Management"])


master_router = APIRouter(prefix="/master", tags=["Master Data"])


wtg_router = APIRouter(prefix="/wtg", tags=["WTG Entries"])


feeder_router = APIRouter(prefix="/feeder", tags=["Feeder Entries"])


downtime_router = APIRouter(prefix="/downtime", tags=["Downtime"])

# ============================================================
# PYDANTIC MODELS
# ============================================================

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

class CheckUserTypeModel(BaseModel):
    identifier: str

class WTGEntryCreate(BaseModel):
    wtg_name: str
    wtg_type: str
    alarm_code: Optional[str] = None
    alarm_description: Optional[str] = None
    initial_observation: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    ack_by: Optional[str] = None

class FeederEntryCreate(BaseModel):
    feedername: str
    type: str
    errorcode: Optional[int] = None
    description: Optional[str] = None
    initial_observation: Optional[str] = None
    starttime: datetime
    endtime: Optional[datetime] = None
    ack_by: Optional[str] = None

# ==================== RESPONSE DURATION PYDANTIC MODELS ====================

class ResponseDurationCreate(BaseModel):
    responsecode: str
    responsedescription: Optional[str] = None
    starttime: datetime
    endtime: Optional[datetime] = None
    duration: Optional[str] = None

# ==================== RESPONSE DURATION PYDANTIC MODELS ====================

class ResponseDurationCreate(BaseModel):
    responsecode: Optional[str] = None
    responsedescription: Optional[str] = None
    starttime: datetime
    endtime: Optional[datetime] = None
    duration: Optional[str] = None

# ============================================================
# HELPERS & UTILITY FUNCTIONS
# ============================================================

ALARM_MAP = {
    "300005": "Phase Sequence Error",
    "300006": "Converter Overcurrent",
    "300007": "Converter Overvoltage",
    "300008": "Inverter Temperature High",
    "300009": "Transformer Temperature High",
    "300010": "Auxiliary Power Failure",
    "300011": "Rotor Overspeed",
    "300012": "Rotor Imbalance Detected"
}

ALARM_REVERSE_MAP = {v: k for k, v in ALARM_MAP.items()}

def send_otp_email(to_email: str, otp: str):
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

def get_client_ip(request: Request):
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host

async def get_public_ip():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get("https://api64.ipify.org?format=json")
            data = response.json()
            return data.get("ip", "Unknown")
    except Exception:
        return "Unknown"

async def get_geo(ip: str):
    try:
        clean_ip = ip.split(":")[0]
        ip_obj = ipaddress.ip_address(clean_ip)
        private_ip = clean_ip
        public_ip = clean_ip

        if ip_obj.is_private or ip_obj.is_loopback:
            public_ip = await get_public_ip()

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"http://ip-api.com/json/{public_ip}")
            data = response.json()

            return {
                "private_ip": private_ip,
                "public_ip": public_ip,
                "country": data.get("country", "Unknown"),
                "country_code": data.get("countryCode", "Unknown"),
                "region": data.get("regionName", "Unknown"),
                "city": data.get("city", "Unknown"),
                "timezone": data.get("timezone", "Asia/Kolkata"),
                "latitude": str(data.get("lat", 0)),
                "longitude": str(data.get("lon", 0)),
                "isp": data.get("isp", "Unknown")
            }
    except Exception:
        return {
            "private_ip": ip,
            "public_ip": "Unknown",
            "country": "Unknown",
            "country_code": "Unknown",
            "region": "Unknown",
            "city": "Unknown",
            "timezone": "Asia/Kolkata",
            "latitude": "0",
            "longitude": "0",
            "isp": "Unknown"
        }

def get_device_info(ua_string: str):
    ua = ua_parse(ua_string or "")
    device_type = (
        "Mobile" if ua.is_mobile
        else "Tablet" if ua.is_tablet
        else "Bot" if ua.is_bot
        else "Desktop"
    )
    return {
        "type": device_type,
        "browser": ua.browser.family,
        "os": ua.os.family,
        "user_agent": ua_string
    }

async def get_weather(lat: float, lon: float, timezone_name: str):
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,"
        f"apparent_temperature,weather_code,"
        f"wind_speed_10m,precipitation,"
        f"cloud_cover,is_day"
        f"&wind_speed_unit=kmh"
        f"&temperature_unit=celsius"
        f"&timezone={timezone_name}"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return {"error": "Weather API Error"}
            data = response.json()
            current = data.get("current", {})

            weather_conditions = {
                0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
                45: "Fog", 48: "Icy Fog",
                51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Dense Drizzle",
                61: "Light Rain", 63: "Moderate Rain", 65: "Heavy Rain",
                71: "Light Snow", 73: "Moderate Snow", 75: "Heavy Snow",
                80: "Rain Showers", 81: "Heavy Showers", 82: "Violent Showers",
                95: "Thunderstorm", 96: "Thunderstorm + Hail", 99: "Severe Thunderstorm"
            }

            code = current.get("weather_code", -1)

            return {
                "condition": weather_conditions.get(code, "Unknown"),
                "condition_code": code,
                "temperature_c": current.get("temperature_2m"),
                "feels_like_c": current.get("apparent_temperature"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "precipitation_mm": current.get("precipitation"),
                "cloud_cover_pct": current.get("cloud_cover"),
                "is_day": bool(current.get("is_day", 1))
            }
    except Exception as e:
        return {"error": str(e)}
    
# ==================== RESPONSE CODE MAPPING ====================

def get_response_map(db: Session):
    """Fetch response code mapping from database"""
    responses = db.query(ResponseMaster).all()
    return {r.responsecode: r.responsedescription for r in responses}

def get_response_reverse_map(db: Session):
    """Fetch reverse response code mapping from database"""
    responses = db.query(ResponseMaster).all()
    return {r.responsedescription: r.responsecode for r in responses}


# ============================================================
# AUTH ROUTES
# ============================================================

@auth_router.post("/login")
async def login(
    data: LoginModel,
    request: Request,
    db: Session = Depends(get_db)
):
    user = db.query(UserMaster).filter(
        or_(UserMaster.username == data.identifier, UserMaster.emailid == data.identifier)
    ).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    usertype = db.query(UserType).filter(UserType.id == user.usertype_id).first()

    if user.usertype_id == 1:
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

    if user.password != data.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    ip = get_client_ip(request)
    geo = await get_geo(ip)
    device = get_device_info(request.headers.get("User-Agent", ""))

    new_session = IPSession(
        session_id=str(uuid.uuid4()),
        username=user.username,
        email=user.emailid,
        role=usertype.usertype if usertype else "user",
        ip=ip,
        country=geo.get("country"),
        region=geo.get("region"),
        city=geo.get("city"),
        browser=device.get("browser"),
        os=device.get("os"),
        user_agent=device.get("user_agent")
    )
    db.add(new_session)
    db.commit()

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

@auth_router.post("/check-user-type")
def check_user_type(
    identifier: str,
    db: Session = Depends(get_db)
):
    if "@" in identifier:
        db_user = db.query(UserMaster).filter(UserMaster.emailid == identifier).first()
    else:
        db_user = db.query(UserMaster).filter(UserMaster.username == identifier).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "username": db_user.username,
        "usertype_id": db_user.usertype_id,
        "captcha_required": db_user.usertype_id == 1
    }

@auth_router.post("/get_otp")
def get_otp(
    data: ForgotPassword,
    db: Session = Depends(get_db)
):
    user = db.query(UserMaster).filter(UserMaster.emailid == data.email).first()
    if not user:
        raise HTTPException(404, "Email not found")
    
    otp = str(random.randint(1000, 9999))
    
    db.query(OTPStore).filter(OTPStore.email == data.email).delete()
    
    db.add(OTPStore(
        email=data.email,
        otp=otp,
        expires=str(time.time() + 600)
    ))
    db.commit()
    
    if send_otp_email(data.email, otp):
        return {"success": True, "message": "OTP sent to your email"}
    else:
        raise HTTPException(500, "Failed to send OTP email")

@auth_router.post("/verify_otp")
def verify_otp(
    data: VerifyOTP,
    db: Session = Depends(get_db)
):
    otp_data = db.query(OTPStore).filter(OTPStore.email == data.email).first()
    
    if not otp_data:
        raise HTTPException(status_code=400, detail="OTP not found")
    
    if time.time() > float(otp_data.expires):
        db.delete(otp_data)
        db.commit()
        raise HTTPException(status_code=400, detail="OTP expired")
    
    if otp_data.otp != data.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    verified_otp_store[data.email] = True
    
    db.delete(otp_data)
    db.commit()
    
    return {"success": True, "message": "OTP Verified Successfully"}

@auth_router.post("/reset_password")
def reset_password(
    data: ResetPassword,
    db: Session = Depends(get_db)
):
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
    
    user.password = data.new_password
    db.commit()
    
    verified_otp_store.pop(data.email, None)
    
    return {"success": True, "message": "Password Reset Successfully"}

@auth_router.post("/set_password")
def set_password(
    data: SetPassword,
    db: Session = Depends(get_db)
):
    if not data.username and not data.email:
        raise HTTPException(status_code=400, detail="Username or Email required")
    
    if data.password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    error = validate_password(data.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    user = db.query(UserMaster).filter(
        or_(UserMaster.username == data.username, UserMaster.emailid == data.email)
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.password = data.password
    db.commit()
    
    return {"success": True, "message": "Password Set Successfully"}

@auth_router.post("/register")
async def register_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    usertype_id: int = Form(...),
    fullname: str = Form(None),
    contactno: str = Form(None),
    theme: str = Form(None),
    sitemaster_id: int = Form(None),
    photo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    usertype = db.query(UserType).filter(UserType.id == usertype_id).first()
    if not usertype:
        raise HTTPException(status_code=400, detail="Invalid usertype")
    
    existing = db.query(UserMaster).filter(
        or_(UserMaster.username == username, UserMaster.emailid == email)
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Username or Email already exists")
    
    error = validate_password(password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    photo_path = None
    if photo and photo.filename:
        try:
            photo_path = await save_photo(photo, UPLOAD_DIR)
        except HTTPException as e:
            raise e
    
    new_user = UserMaster(
        username=username,
        emailid=email,
        password=password,
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

@auth_router.get("/captcha")
def get_captcha():
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

# ============================================================
# USER ROUTES
# ============================================================

@user_router.get("/")
def get_users(
    identifier: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(UserMaster)

    if identifier:
        query = query.filter(
            or_(UserMaster.username == identifier, UserMaster.emailid == identifier)
        )

    users = query.all()

    data = []

    for user in users:
        data.append({
            "id": user.id,
            "fullname": user.fullname,
            "username": user.username,
            "email": user.emailid,
            "contact_no": user.contactno,
            "usertype_id": user.usertype_id,
            "theme": user.theme,
            "photo": user.photo,
            "sitemaster_id": user.sitemaster_id
        })

    return {
        "status": "success",
        "total_users": len(data),
        "data": data
    }

@user_router.put("/update_profile")
def update_profile(
    data: UpdateProfile,
    db: Session = Depends(get_db)
):
    if not data.username and not data.email:
        raise HTTPException(status_code=400, detail="Username or Email required")
    
    user = db.query(UserMaster).filter(
        or_(UserMaster.username == data.username, UserMaster.emailid == data.email)
    ).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if data.fullName:
        user.fullname = data.fullName
    if data.userName:
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

@user_router.put("/update-photo/{username}")
async def update_profile_photo(
    username: str,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = db.query(UserMaster).filter(UserMaster.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if photo.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
        raise HTTPException(status_code=400, detail="Only JPG/PNG allowed")
    
    try:
        if user.photo:
            delete_photo(user.photo)
        
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

# ============================================================
# IP ROUTES
# ============================================================

@ip_router.get("/live")
async def get_liveip(request: Request):
    ip = get_client_ip(request)
    geo = await get_geo(ip)
    device = get_device_info(request.headers.get("User-Agent", ""))

    now = datetime.now(timezone.utc)

    lat = float(geo.get("latitude", 0) or 0)
    lon = float(geo.get("longitude", 0) or 0)
    tz = geo.get("timezone", "Asia/Kolkata")

    try:
        local_dt = now.astimezone(ZoneInfo(tz))
        local_time = local_dt.strftime("%Y-%m-%d %H:%M:%S")
        timezone_abbr = local_dt.strftime("%Z")
    except Exception:
        local_time = now.strftime("%Y-%m-%d %H:%M:%S")
        timezone_abbr = "UTC"

    weather_data = {}

    if lat != 0.0 or lon != 0.0:
        try:
            weather = await get_weather(lat, lon, tz)
            if "error" not in weather:
                weather_data = weather
            else:
                weather_data = {
                    "condition": "Data Unavailable",
                    "condition_code": -1,
                    "temperature_c": round(random.uniform(25, 35), 1),
                    "feels_like_c": round(random.uniform(26, 36), 1),
                    "humidity_pct": random.randint(60, 85),
                    "wind_speed_kmh": round(random.uniform(5, 25), 1),
                    "precipitation_mm": round(random.uniform(0, 5), 1),
                    "cloud_cover_pct": random.randint(20, 80),
                    "is_day": True
                }
        except Exception:
            weather_data = {
                "condition": "Weather data temporarily unavailable",
                "condition_code": -1,
                "temperature_c": round(random.uniform(25, 35), 1),
                "feels_like_c": round(random.uniform(26, 36), 1),
                "humidity_pct": random.randint(60, 85),
                "wind_speed_kmh": round(random.uniform(5, 25), 1),
                "precipitation_mm": round(random.uniform(0, 5), 1),
                "cloud_cover_pct": random.randint(20, 80),
                "is_day": True
            }
    else:
        weather_data = {
            "condition": "Location data unavailable",
            "condition_code": -1,
            "temperature_c": round(random.uniform(25, 35), 1),
            "feels_like_c": round(random.uniform(26, 36), 1),
            "humidity_pct": random.randint(60, 85),
            "wind_speed_kmh": round(random.uniform(5, 25), 1),
            "precipitation_mm": round(random.uniform(0, 5), 1),
            "cloud_cover_pct": random.randint(20, 80),
            "is_day": True
        }

    return {
        "success": True,
        "ip": ip,
        "isp": geo.get("isp"),
        "city": geo.get("city"),
        "region": geo.get("region"),
        "country": geo.get("country"),
        "country_code": geo.get("country_code"),
        "latitude": geo.get("latitude"),
        "longitude": geo.get("longitude"),
        "timezone": tz,
        "local_time": local_time,
        "timezone_abbr": timezone_abbr,
        "server_utc_date": now.strftime("%Y-%m-%d"),
        "server_utc_time": now.strftime("%H:%M:%S"),
        "server_utc_iso": now.isoformat(),
        "condition": weather_data.get("condition"),
        "condition_code": weather_data.get("condition_code"),
        "temperature_c": weather_data.get("temperature_c"),
        "feels_like_c": weather_data.get("feels_like_c"),
        "humidity_pct": weather_data.get("humidity_pct"),
        "wind_speed_kmh": weather_data.get("wind_speed_kmh"),
        "precipitation_mm": weather_data.get("precipitation_mm"),
        "cloud_cover_pct": weather_data.get("cloud_cover_pct"),
        "is_day": weather_data.get("is_day"),
        "device_type": device.get("type"),
        "os": device.get("os"),
        "browser": device.get("browser"),
        "user_agent": device.get("user_agent"),
    }

@ip_router.get("/history")
def ip_history(
    username: str,
    db: Session = Depends(get_db)
):
    sessions = (
        db.query(IPSession)
        .filter(IPSession.username == username)
        .all()
    )

    data = []

    for row in sessions:
        data.append({
            "id": row.id,
            "session_id": row.session_id,
            "username": row.username,
            "email": row.email,
            "role": row.role,
            "ip": row.ip,
            "city": row.city,
            "region": row.region,
            "country": row.country,
            "browser": row.browser,
            "os": row.os,
            "user_agent": row.user_agent,
            "country_code": getattr(row, "country_code", None),
            "latitude": getattr(row, "latitude", None),
            "longitude": getattr(row, "longitude", None),
            "timezone": getattr(row, "timezone", None),
            "isp": getattr(row, "isp", None),
            "created_at": getattr(row, "created_at", None),
            "updated_at": getattr(row, "updated_at", None),
        })

    return {
        "success": True,
        "count": len(data),
        "data": data
    }

# ============================================================
# MASTER DATA ROUTES
# ============================================================

@master_router.get("/sites")
def get_sites(db: Session = Depends(get_db)):
    return db.query(SiteMaster).all()

@master_router.get("/themes")
def get_themes(db: Session = Depends(get_db)):
    return db.query(Theme).all()

@master_router.get("/usertypes")
def get_usertypes(db: Session = Depends(get_db)):
    return db.query(UserType).all()

@master_router.get("/types")
def get_types(db: Session = Depends(get_db)):
    types = db.query(TypeMaster).all()
    
    wtg_types = []
    grid_types = []
    
    for t in types:
        if t.type.lower() == "wtg":
            wtg_types.append({"id": t.id, "type": t.type})
        elif t.type.lower() == "grid":
            grid_types.append({"id": t.id, "type": t.type})
    
    return {
        "success": True,
        "data": {"wtg_types": wtg_types, "grid_types": grid_types}
    }

@master_router.get("/alarms")
def get_alarms(
    errorcode: Optional[int] = None,
    alarm_code: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(AlarmMaster)
    code = errorcode or alarm_code
    
    if code:
        query = query.filter(AlarmMaster.errorcode == code)
    
    alarms = query.order_by(AlarmMaster.errorcode).all()
    
    return {
        "success": True,
        "count": len(alarms),
        "data": [
            {
                "id": alarm.id,
                "errorcode": alarm.errorcode,
                "description": alarm.description,
                "risktype": alarm.risktype
            }
            for alarm in alarms
        ]
    }

@master_router.get("/category")
def get_category(db: Session = Depends(get_db)):
    categories = db.query(ChooseCategory).all()
    
    return {
        "success": True,
        "data": [
            {"id": cat.id, "category": cat.choosecategory}
            for cat in categories
        ]
    }

# ============================================================
# WTG ENTRY ROUTES
# ============================================================

@wtg_router.post("/entry")
async def create_wtg_entry(
    entry: WTGEntryCreate,
    db: Session = Depends(get_db)
):
    if entry.end_time and entry.start_time >= entry.end_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    
    alarm_code = entry.alarm_code
    alarm_description = entry.alarm_description
    
    if alarm_code and alarm_description:
        expected_description = ALARM_MAP.get(alarm_code)
        if not expected_description:
            raise HTTPException(status_code=400, detail=f"Invalid alarm code: {alarm_code}")
        if expected_description != alarm_description:
            raise HTTPException(status_code=400, detail=f"Alarm description '{alarm_description}' does not match code '{alarm_code}'")
    elif alarm_code and not alarm_description:
        description = ALARM_MAP.get(alarm_code)
        if not description:
            raise HTTPException(status_code=400, detail=f"Invalid alarm code: {alarm_code}")
        alarm_description = description
    elif alarm_description and not alarm_code:
        code = ALARM_REVERSE_MAP.get(alarm_description)
        if not code:
            raise HTTPException(status_code=400, detail=f"Invalid alarm description: {alarm_description}")
        alarm_code = code
    
    ack_by_userid = None
    ack_time = None
    if entry.ack_by:
        user = db.query(UserMaster).filter(UserMaster.username == entry.ack_by).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User '{entry.ack_by}' not found")
        ack_by_userid = user.id
        ack_time = datetime.now()
    
    new_entry = WTGEntry(
        wtg_name=entry.wtg_name,
        wtg_type=entry.wtg_type,
        alarm_code=alarm_code,
        alarm_description=alarm_description,
        initial_observation=entry.initial_observation,
        start_time=entry.start_time,
        end_time=entry.end_time,
        ack_by=entry.ack_by,
        ack_by_userid=ack_by_userid,
        ack_time=ack_time
    )
    
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    
    return {
        "success": True,
        "message": "WTG entry created successfully",
        "data": {
            "id": new_entry.id,
            "wtg_name": new_entry.wtg_name,
            "wtg_type": new_entry.wtg_type,
            "alarm_code": new_entry.alarm_code,
            "alarm_description": new_entry.alarm_description,
            "initial_observation": new_entry.initial_observation,
            "start_time": new_entry.start_time,
            "end_time": new_entry.end_time,
            "ack_by": new_entry.ack_by,
            "ack_by_userid": new_entry.ack_by_userid,
            "ack_time": new_entry.ack_time,
            "created_at": new_entry.created_at
        }
    }

# ============================================================
# FEEDER ENTRY ROUTES
# ============================================================

@feeder_router.post("/entry")
async def create_feeder_entry(
    entry: FeederEntryCreate,
    db: Session = Depends(get_db)
):
    type_exists = db.query(TypeMaster).filter(TypeMaster.type == entry.type).first()
    if not type_exists:
        raise HTTPException(status_code=400, detail=f"Invalid type '{entry.type}'. Must be WTG or Grid")
    
    if entry.endtime and entry.starttime >= entry.endtime:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    
    errorcode = entry.errorcode
    description = entry.description
    
    if errorcode and description:
        alarm = db.query(AlarmMaster).filter(
            AlarmMaster.errorcode == errorcode,
            AlarmMaster.description == description
        ).first()
        
        if not alarm:
            alarm_by_code = db.query(AlarmMaster).filter(AlarmMaster.errorcode == errorcode).first()
            if alarm_by_code:
                raise HTTPException(status_code=400, detail=f"Errorcode {errorcode} has description '{alarm_by_code.description}', not '{description}'")
            
            alarm_by_desc = db.query(AlarmMaster).filter(AlarmMaster.description == description).first()
            if alarm_by_desc:
                raise HTTPException(status_code=400, detail=f"Description '{description}' has errorcode {alarm_by_desc.errorcode}, not {errorcode}")
            
            raise HTTPException(status_code=404, detail=f"No alarm found with errorcode {errorcode} and description '{description}'")
        
        errorcode = alarm.errorcode
        description = alarm.description
    elif errorcode and not description:
        alarm = db.query(AlarmMaster).filter(AlarmMaster.errorcode == errorcode).first()
        if not alarm:
            raise HTTPException(status_code=404, detail=f"No alarm found with errorcode: {errorcode}")
        description = alarm.description
    elif description and not errorcode:
        alarm = db.query(AlarmMaster).filter(AlarmMaster.description.ilike(f"%{description}%")).first()
        if not alarm:
            raise HTTPException(status_code=404, detail=f"No alarm found with description containing: {description}")
        errorcode = alarm.errorcode
        description = alarm.description
    
    ack_by_userid = None
    ack_time = None
    if entry.ack_by:
        user = db.query(UserMaster).filter(UserMaster.username == entry.ack_by).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"User '{entry.ack_by}' not found")
        ack_by_userid = user.id
        ack_time = datetime.now()
    
    new_entry = FeederEntry(
        feedername=entry.feedername,
        type=entry.type,
        errorcode=errorcode,
        description=description,
        initial_observation=entry.initial_observation,
        starttime=entry.starttime,
        endtime=entry.endtime,
        ack_by=entry.ack_by,
        ack_by_userid=ack_by_userid,
        ack_time=ack_time
    )
    
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    
    return {
        "success": True,
        "message": "Feeder entry created successfully",
        "data": {
            "id": new_entry.id,
            "feedername": new_entry.feedername,
            "type": new_entry.type,
            "errorcode": new_entry.errorcode,
            "description": new_entry.description,
            "initial_observation": new_entry.initial_observation,
            "starttime": new_entry.starttime,
            "endtime": new_entry.endtime,
            "ack_by": new_entry.ack_by,
            "ack_by_userid": new_entry.ack_by_userid,
            "ack_time": new_entry.ack_time,
            "created_at": new_entry.created_at
        }
    }

# ============================================================
# DOWNTIME ROUTES
# ============================================================

@downtime_router.get("/list")
def get_downtimelist(
    date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    wtg_query = db.query(
        WTGEntry.id.label("reference_id"),
        WTGEntry.wtg_type.label("type"),
        WTGEntry.alarm_code.label("alarm_code"),
        WTGEntry.alarm_description.label("alarm_description"),
        WTGEntry.start_time.label("start_time"),
        WTGEntry.end_time.label("end_time"),
        WTGEntry.ack_by.label("ack_by"),
        WTGEntry.ack_time.label("ack_time"),
        WTGEntry.categorized_by.label("categorized_by"),
        WTGEntry.categorized_time.label("categorized_time"),
        WTGEntry.initial_observation.label("initial_observation"),
        literal("WTG").label("source")
    )
    
    feeder_query = db.query(
        FeederEntry.id.label("reference_id"),
        FeederEntry.type.label("type"),
        FeederEntry.errorcode.label("alarm_code"),
        FeederEntry.description.label("alarm_description"),
        FeederEntry.starttime.label("start_time"),
        FeederEntry.endtime.label("end_time"),
        FeederEntry.ack_by.label("ack_by"),
        FeederEntry.ack_time.label("ack_time"),
        FeederEntry.categorized_by.label("categorized_by"),
        FeederEntry.categorized_time.label("categorized_time"),
        FeederEntry.initial_observation.label("initial_observation"),
        literal("Feeder").label("source")
    )
    
    if date:
        try:
            filter_date = datetime.strptime(date, "%Y-%m-%d").date()
            wtg_query = wtg_query.filter(func.date(WTGEntry.start_time) == filter_date)
            feeder_query = feeder_query.filter(func.date(FeederEntry.starttime) == filter_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    wtg_results = wtg_query.all()
    feeder_results = feeder_query.all()
    
    all_entries = []
    choose_cat = db.query(ChooseCategory).first()
    choose_category_value = choose_cat.choosecategory if choose_cat else None
    
    for row in wtg_results:
        status = "pending"
        if row.categorized_by:
            status = "categorized"
        elif row.ack_by:
            status = "acknowledged"
        
        duration = None
        if row.end_time and row.start_time:
            diff = row.end_time - row.start_time
            total_seconds = diff.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        
        all_entries.append({
            "reference_id": row.reference_id,
            "choose_category": choose_category_value,
            "type": row.type,
            "alarm_code": row.alarm_code,
            "alarm_description": row.alarm_description,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "duration": duration,
            "ack_by": row.ack_by,
            "ack_time": row.ack_time,
            "status": status,
            "categorized_by": row.categorized_by,
            "categorized_time": row.categorized_time,
            "initial_observation": row.initial_observation,
            "source": row.source
        })
    
    for row in feeder_results:
        status = "pending"
        if row.categorized_by:
            status = "categorized"
        elif row.ack_by:
            status = "acknowledged"
        
        duration = None
        if row.end_time and row.start_time:
            diff = row.end_time - row.start_time
            total_seconds = diff.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        
        all_entries.append({
            "reference_id": row.reference_id,
            "choose_category": choose_category_value,
            "type": row.type,
            "alarm_code": row.alarm_code,
            "alarm_description": row.alarm_description,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "duration": duration,
            "ack_by": row.ack_by,
            "ack_time": row.ack_time,
            "status": status,
            "categorized_by": row.categorized_by,
            "categorized_time": row.categorized_time,
            "initial_observation": row.initial_observation,
            "source": row.source
        })
    
    all_entries.sort(key=lambda x: x["start_time"], reverse=True)
    
    return {
        "success": True,
        "count": len(all_entries),
        "data": all_entries
    }


# ==================== POST RESPONSE DURATION ENDPOINT ====================

@app.post("/post_responseduration")
async def create_response_duration(
    entry: ResponseDurationCreate,
    db: Session = Depends(get_db)
):
   
    responsecode = entry.responsecode
    responsedescription = entry.responsedescription
    
    if responsecode and responsedescription:
        
        expected_description = RESPONSE_MAP.get(responsecode)
        if not expected_description:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid response code: {responsecode}"
            )
        if expected_description != responsedescription:
            raise HTTPException(
                status_code=400,
                detail=f"Response description '{responsedescription}' does not match code '{responsecode}'"
            )
    
    elif responsecode and not responsedescription:
 
        description = RESPONSE_MAP.get(responsecode)
        if not description:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid response code: {responsecode}"
            )
        responsedescription = description
    
    elif responsedescription and not responsecode:
        
        code = RESPONSE_REVERSE_MAP.get(responsedescription)
        if not code:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid response description: {responsedescription}"
            )
        responsecode = code
    
  
    duration = entry.duration
    if entry.endtime and not duration:
        diff = entry.endtime - entry.starttime
        total_seconds = diff.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        if hours > 0:
            duration = f"{hours}h {minutes}m"
        else:
            duration = f"{minutes}m"
    
    if entry.endtime and entry.starttime >= entry.endtime:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )
   
    new_entry = ResponseDuration(
        responsecode=responsecode,
        responsedescription=responsedescription,
        starttime=entry.starttime,
        endtime=entry.endtime,
        duration=duration
    )
    
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    
    return {
        "success": True,
        "message": "Response duration entry created successfully",
        "data": {
            "id": new_entry.id,
            "responsecode": new_entry.responsecode,
            "responsedescription": new_entry.responsedescription,
            "starttime": new_entry.starttime,
            "endtime": new_entry.endtime,
            "duration": new_entry.duration
        }
    }
# ==================== GET RESPONSE DURATION ENDPOINT ====================

@app.get("/get_responsedurations")
def get_response_durations(
    responsecode: Optional[str] = None,
    responsedescription: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get all response duration entries with optional filters.
    """
    query = db.query(ResponseDuration)
    
    if responsecode:
        query = query.filter(ResponseDuration.responsecode == responsecode)
    if responsedescription:
        query = query.filter(ResponseDuration.responsedescription.ilike(f"%{responsedescription}%"))
    
    entries = query.order_by(ResponseDuration.starttime.desc()).all()
    
    return {
        "success": True,
        "count": len(entries),
        "data": [
            {
                "id": entry.id,
                "responsecode": entry.responsecode,
                "responsedescription": entry.responsedescription,
                "starttime": entry.starttime,
                "endtime": entry.endtime,
                "duration": entry.duration
            }
            for entry in entries
        ]
    }

# ============================================================
# REGISTER ROUTERS
# ============================================================

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(ip_router)
app.include_router(master_router)
app.include_router(wtg_router)
app.include_router(feeder_router)
app.include_router(downtime_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )