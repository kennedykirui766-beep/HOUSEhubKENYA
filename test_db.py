import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()
db_url = os.environ.get("DATABASE_URL") or "sqlite:///app.db"
engine = create_engine(db_url)

try:
    with engine.connect() as connection:
        print("✅ Connected to the database successfully.")
except Exception as e:
    print(f"❌ Failed to connect: {e}")