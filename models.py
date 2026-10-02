from typing import Optional
import datetime

from sqlalchemy import CHAR, DateTime, ForeignKeyConstraint, Index, Numeric, String, text
from sqlalchemy.dialects.mysql import INTEGER, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = 'device'

    device_seq: Mapped[int] = mapped_column(INTEGER(11), primary_key=True, autoincrement=True)
    device_name: Mapped[str] = mapped_column(String(50), nullable=False)
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(CHAR(5), nullable=False, server_default=text("'OFF'"))
    ip_address: Mapped[Optional[str]] = mapped_column(CHAR(16))
    location: Mapped[Optional[str]] = mapped_column(String(20))
    create_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    modify_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    delete_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)


class SensorLog(Base):
    __tablename__ = 'sensor_log'
    __table_args__ = (
        ForeignKeyConstraint(['device_seq'], ['device.device_seq'], name='sensor_log_ibfk_1'),
        Index('device_seq', 'device_seq'),
    )

    log_seq: Mapped[int] = mapped_column(INTEGER(11), primary_key=True, autoincrement=True)
    device_seq: Mapped[int] = mapped_column(INTEGER(11), nullable=False)
    value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)


class User(Base):
    __tablename__ = 'user'
    __table_args__ = (
        Index('email', 'email', unique=True),
    )

    user_seq: Mapped[int] = mapped_column(INTEGER(11), primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    user_name: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(INTEGER(11), nullable=False)
    status: Mapped[int] = mapped_column(TINYINT(4), nullable=False, server_default=text('0'))
    create_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320))
    phone: Mapped[Optional[str]] = mapped_column(CHAR(13))
    modify_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    delete_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
