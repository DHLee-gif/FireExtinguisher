from flask import Flask, render_template, request, jsonify, redirect, session
from db import get_db_connection
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from models import User, Device, SensorLog
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "myfarm-secret-key"

engine = create_engine("mysql+pymysql://ktech:ktech1234@172.30.1.65:3306/myfarm")

@app.before_request
def login_required() :
    
    #로그인 없이 접근 가능한 페이지 목록(ex: 로그인 화면)
    public_endpoints = ["login", "static", "signup"]
    if request.endpoint in public_endpoints : return
    
    if session.get("user_id") is None :
        return redirect("/login")


@app.route("/")
@app.route("/home")
def index() :
    return "Hello Flask"

@app.route("/login", methods=["GET", "POST"])
def login() :
    
    if request.method == "POST" :
        user_id = request.form.get("user_id")
        password = request.form.get("password")
        
        with Session(engine) as db_session :
            
            stmt = select(User).where(User.user_id == user_id)
            query_result = db_session.execute(stmt)
            row = query_result.first()

            if row != None and check_password_hash(row[0].password, password) :
                # 로그인 성공 시에 session에 유저 정보를 담음
                session["user_id"] = row[0].user_id
                session["user_name"] = row[0].user_name
                return render_template("welcome.html", user_name = row[0].user_name)
            
            else :
                return redirect("/login")
        
    return render_template("login.html")

@app.route("/logout")
def logout() :
    session.clear()
    return redirect("/logout")

@app.route("/user")
def users() :

    with Session(engine) as session :

        stmt = select(User)
        query_result = session.execute(stmt)

        users = query_result.scalars().all()

        return render_template("users.html", users = users)
        

@app.route("/for")  
def for_exam() :
    students = []
    students.append("kim")
    students.append("lee")
    students.append("park")
    students.append("choi")
    return render_template("for.html", students = students)

@app.route("/adduser", methods=["GET", "POST"])
def adduser() :
    
    if request.method == "GET" :
        return render_template("adduser.html")
    
    if request.method == "POST" :
        
        user = User(
            user_id = request.form.get("user_id"),
            password = request.form.get("password"),
            user_name = request.form.get("user_name"),
            email = request.form.get("email"),
            phone = request.form.get("phone"),
            level = request.form.get("level"),
            create_at = datetime.now()
        )
        
        with Session(engine) as db_session :
            db_session.add(user)
            db_session.commit()
            
        return redirect("/user")

@app.route("/device")
def device() :

    with Session(engine) as session :

        stmt = select(Device)
        query_result = session.execute(stmt)

        devices = query_result.scalars().all()

        return render_template("device.html", devices = devices)

@app.route("/adddevice", methods=["GET", "POST"])
def adddevice() :

    if request.method == "GET" :
        return render_template("adddevice.html")

    if request.method == "POST" :

        device = Device(
            device_name = request.form.get("device_name"),
            device_type = request.form.get("device_type"),
            status = request.form.get("status") or "OFF",
            ip_address = request.form.get("ip_address"),
            location = request.form.get("location"),
            create_at = datetime.now()
        )

        with Session(engine) as db_session :
            db_session.add(device)
            db_session.commit()

        return redirect("/device")

@app.route("/dashboard")
def dashboard() :

    with Session(engine) as db_session :

        stmt = select(SensorLog).order_by(SensorLog.recorded_at)
        query_result = db_session.execute(stmt)

        logs = query_result.scalars().all()

        labels = [log.recorded_at.strftime("%Y-%m-%d %H:%M:%S") for log in logs]
        data = [float(log.value) for log in logs]
        title = "온도"

    return render_template("dashboard.html", labels=labels, data=data, title=title)

if __name__ == "__main__" :
    app.run(debug = True)
    