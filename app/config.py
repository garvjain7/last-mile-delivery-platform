
import os
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"

if not REDIS_URL:
    raise ValueError("REDIS_URL is missing from .env")

if not JWT_SECRET:
    raise ValueError("JWT_SECRET is missing from .env")
