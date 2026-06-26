from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,  # ADD THIS
    ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func  # ADD THIS
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserMaster(Base):
    __tablename__ = "tbl_usermaster"

    id = Column(Integer, primary_key=True)
    fullname = Column(String(100))
    username = Column(String(100), unique=True, nullable=False)
    emailid = Column(String(255), unique=True, nullable=False)
    contactno = Column(String(100))
    usertype_id = Column(Integer, ForeignKey("tbl_usertype.id"))
    sitemaster_id = Column(Integer)
    theme = Column(String(50))
    photo = Column(String(255))
    password = Column(String(255), nullable=False)
    
    # Relationship
    usertype = relationship("UserType", back_populates="users")

class UserType(Base):
    __tablename__ = "tbl_usertype"
    id = Column(Integer, primary_key=True)
    usertype = Column(String(255))
    
    # Relationship
    users = relationship("UserMaster", back_populates="usertype")

class Theme(Base):
    __tablename__ = "tbl_theme"
    id = Column(Integer, primary_key=True)
    themename = Column(String(255))

class SiteMaster(Base):
    __tablename__ = "tbl_sitemaster"
    id = Column(Integer, primary_key=True)
    siteid = Column(Integer)
    sitename = Column(String(50))
    state = Column(String(20))
    totalturbines = Column(Integer)
    sitecapacity = Column(String)
    sitead = Column(String)
    datafilename = Column(String)
    meandatafile = Column(String)
    lat = Column(String)
    lon = Column(String)

class OTPStore(Base):
    __tablename__ = "otp_store"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True)
    otp = Column(String)
    expires = Column(String)

class IPSession(Base):
    __tablename__ = "ip_sessions"
    id = Column(Integer, primary_key=True)
    session_id = Column(String)
    username = Column(String)
    email = Column(String)
    role = Column(String)
    ip = Column(String)
    country = Column(String)
    region = Column(String)
    city = Column(String)
    browser = Column(String)
    os = Column(String)
    user_agent = Column(Text)


class TypeMaster(Base):
    __tablename__ = "tbl_typemaster"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), nullable=False, unique=True)

class AlarmMaster(Base):
    __tablename__ = "tbl_alarmmaster"

    id = Column(Integer, primary_key=True, index=True)
    errorcode = Column(Integer, nullable=False, unique=True)
    description = Column(Text, nullable=False)
    risktype = Column(Text, nullable=True)

class WTGEntry(Base):
    __tablename__ = "tbl_wtg_entries"

    id = Column(Integer, primary_key=True, index=True)
    wtg_name = Column(String(100), nullable=False)
    wtg_type = Column(String(100), nullable=False)
    alarm_code = Column(String(50), nullable=True)
    alarm_description = Column(String(500), nullable=True)
    initial_observation = Column(Text, nullable=True)  # NEW
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    ack_by = Column(String(100), nullable=True)
    ack_by_userid = Column(Integer, nullable=True)
    ack_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class FeederEntry(Base):
    __tablename__ = "tbl_feeder_entries"

    id = Column(Integer, primary_key=True, index=True)
    feedername = Column(String(100), nullable=False)
    type = Column(String(50), nullable=False)
    errorcode = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    initial_observation = Column(Text, nullable=True)  
    starttime = Column(DateTime, nullable=False)
    endtime = Column(DateTime, nullable=True)
    ack_by = Column(String(100), nullable=True)
    ack_by_userid = Column(Integer, nullable=True)
    ack_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())