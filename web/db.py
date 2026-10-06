from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config

engine = create_engine(
    config.SQLALCHEMY_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"connect_timeout": 3},
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
