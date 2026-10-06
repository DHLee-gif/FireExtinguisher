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
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=func.now())


class Device(Base):
    __tablename__ = "device"

    device_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[Optional[str]] = mapped_column(String(50))
    last_seen: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class FireEvent(Base):
    __tablename__ = "fire_event"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    detected_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=func.now())
    temperature: Mapped[Optional[float]] = mapped_column(Float)
    vision_score: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        Enum("detected", "spraying", "extinguished", "failed"), server_default="detected"
    )
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
    event_id: Mapped[int] = mapped_column(ForeignKey("fire_event.event_id", ondelete="CASCADE"), nullable=False)
    img_type: Mapped[str] = mapped_column(Enum("before", "after"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    taken_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=func.now())

    event: Mapped[FireEvent] = relationship(back_populates="images")


class SprayLog(Base):
    __tablename__ = "spray_log"

    spray_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("fire_event.event_id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=func.now())
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    temp_after: Mapped[Optional[float]] = mapped_column(Float)

    event: Mapped[FireEvent] = relationship(back_populates="sprays")


class StatusLog(Base):
    __tablename__ = "status_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    logged_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=func.now())
    level: Mapped[str] = mapped_column(Enum("normal", "warning", "error"), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(30))
    message: Mapped[Optional[str]] = mapped_column(String(100))
    resolved_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class WaterLog(Base):
    __tablename__ = "water_log"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    logged_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, server_default=func.now())
    water_level: Mapped[Optional[float]] = mapped_column(Float)
    action: Mapped[Optional[str]] = mapped_column(Enum("low", "homing", "refilled", "homing_failed"))
