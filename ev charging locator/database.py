import mysql.connector

def get_database_connection():
    try:
        connection = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="ev_charging_db"
        )
        return connection
    except mysql.connector.Error as error:
        print(f"Failed to connect to database: {error}")
        return None