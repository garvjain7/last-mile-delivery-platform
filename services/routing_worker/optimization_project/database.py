
import os
import pg8000
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return pg8000.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "last_mile_delivery"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD")
    )

if __name__ == "__main__":
    try:
        connection = get_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT current_database();")
        print("Connected to database:", cursor.fetchone()[0])
        cursor.close()
        connection.close()
    except Exception as error:
        print("Database connection failed:", error)
