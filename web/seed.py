import argparse
import getpass
import os
import re

import pymysql
from sqlalchemy import select
from werkzeug.security import generate_password_hash

import config


def run_schema():
    path = os.path.join(config.BASE_DIR, "schema.sql")
    with open(path, encoding="utf-8") as f:
        sql = re.sub(r"--[^\n]*", "", f.read())
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    conn = pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD, charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    print(f"[schema] {len(statements)}개 SQL 실행 완료 (DB: {config.DB_NAME})")


def seed(login_id, name, password):
    from db import SessionLocal
    from models import Admin, Device

    with SessionLocal() as db:
        admin = db.scalar(select(Admin).where(Admin.login_id == login_id))
        if admin:
            print(f"[seed] 관리자 '{login_id}' 이미 존재 - 건너뜀")
        else:
            db.add(Admin(login_id=login_id, name=name, password_hash=generate_password_hash(password)))
            print(f"[seed] 관리자 '{login_id}' ({name}) 생성")

        if db.get(Device, config.DEVICE_ID):
            print(f"[seed] device {config.DEVICE_ID} 이미 존재 - 건너뜀")
        else:
            db.add(Device(device_id=config.DEVICE_ID, name=config.DEVICE_NAME))
            print(f"[seed] device {config.DEVICE_ID} ({config.DEVICE_NAME}) 생성")

        db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FireCar 초기 데이터 입력")
    parser.add_argument("--schema", action="store_true", help="schema.sql 을 먼저 실행 (DB/테이블 생성)")
    parser.add_argument("--login-id", default="admin")
    parser.add_argument("--name", default="관리자")
    parser.add_argument("--password", help="생략하면 입력 프롬프트가 뜸")
    args = parser.parse_args()

    if args.schema:
        run_schema()

    password = args.password or getpass.getpass(f"'{args.login_id}' 비밀번호: ")
    if not password:
        parser.error("비밀번호가 비어 있습니다.")
    seed(args.login_id, args.name, password)
