import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Admin(Base):
    __tablename__ = "admin"

    admin_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    expires_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class Device(Base):
    __tablename__ = "device"

    device_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    battery_level: Mapped[Optional[float]] = mapped_column(Float)
    last_seen: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class FireLog(Base):
    __tablename__ = "fire_log"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.device_id"), nullable=False)
    temperature: Mapped[Optional[float]] = mapped_column(Float)
    vision_score: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        Enum("detected", "spraying", "extinguished", "failed"), nullable=False, server_default="detected"
    )
    detected_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    closed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    images: Mapped[list["FireImage"]] = relationship(
        back_populates="event", order_by="FireImage.image_id", passive_deletes=True
    )
    sprays: Mapped[list["SprayLog"]] = relationship(
        back_populates="event", order_by="SprayLog.spray_id", passive_deletes=True
    )


class FireImage(Base):
    __tablename__ = "fire_image"

    image_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("fire_log.event_id", ondelete="CASCADE"), nullable=False)
    img_type: Mapped[str] = mapped_column(Enum("before", "after"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    taken_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    event: Mapped[FireLog] = relationship(back_populates="images")


class SprayLog(Base):
    __tablename__ = "spray_log"

    spray_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("fire_log.event_id", ondelete="CASCADE"), nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    temp_after: Mapped[Optional[float]] = mapped_column(Float)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    event: Mapped[FireLog] = relationship(back_populates="sprays")


class DeviceStatusLog(Base):
    __tablename__ = "device_status_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.device_id"), nullable=False)
    level: Mapped[str] = mapped_column(Enum("normal", "warning", "error"), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(30))
    message: Mapped[Optional[str]] = mapped_column(String(100))
    logged_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class WaterLog(Base):
    __tablename__ = "water_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.device_id"), nullable=False)
    water_level: Mapped[Optional[float]] = mapped_column(Float)
    action: Mapped[Optional[str]] = mapped_column(Enum("low", "homing", "refilled", "homing_failed"))
    logged_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
