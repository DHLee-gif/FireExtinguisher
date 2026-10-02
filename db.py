import pymysql

def get_db_connection():
    return pymysql.connect(
        host='127.0.0.1',
        port=13306,
        user='ktech',
        password='ktech1234',
        database='myfarm',
        cursorclass=pymysql.cursors.DictCursor        
    )