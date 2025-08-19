from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String
from typing import List
import base64
import requests
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
from io import BytesIO
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Set up allowed origins for CORS
origins = [
    "http://localhost",
    "http://localhost:3000",
    "https://portal.shriijeesmartabacus.com",
    "https://portal.shriijeesmartmaths.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Configuration
DB_PATH = "/app/data/cache.db"  # Persistent path for SQLite database
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"
engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


# Define the Cache Table
class Cache(Base):
    __tablename__ = "cache"

    key = Column(String, primary_key=True, index=True)
    value = Column(String)


# Initialize the database
async def initialize_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("startup")
async def on_startup():
    # Ensure the persistent directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    await initialize_db()


# Dependency to get DB session
async def get_db():
    async with SessionLocal() as session:
        yield session


class TextItem(BaseModel):
    text: str


class TextList(BaseModel):
    texts: List[str]


class TTS:
    URL = os.getenv("TTS_BASE_URL")
    VOICE = "Microsoft Server Speech Text to Speech Voice (en-US, ZiraPro)"
    session = requests.Session()

    @staticmethod
    async def get_tts(text: str, db: AsyncSession):
        text = text.lower().strip()

        # Check SQLite cache via ORM
        cached_audio = await db.get(Cache, text)
        if cached_audio:
            return base64.b64decode(cached_audio.value)

        # Fetch audio from TTS service
        response = TTS.session.get(
            TTS.URL, params={"text": text, "voiceName": TTS.VOICE}
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code, detail="TTS request failed"
            )
        audio_content = response.content
        trimmed_audio = TTS.remove_silence(audio_content)

        # Cache result in SQLite
        new_cache = Cache(key=text, value=base64.b64encode(trimmed_audio).decode("utf-8"))
        db.add(new_cache)
        await db.commit()

        return trimmed_audio

    @staticmethod
    def remove_silence(audio_content: bytes):
        audio = AudioSegment.from_file(BytesIO(audio_content), format="wav")
        nonsilent_intervals = detect_nonsilent(
            audio, min_silence_len=500, silence_thresh=-40
        )

        if nonsilent_intervals:
            start, end = nonsilent_intervals[0][0], nonsilent_intervals[-1][1]
            trimmed_audio = audio[start:end]
            buffer = BytesIO()
            trimmed_audio.export(buffer, format="wav")
            return buffer.getvalue()
        return audio_content

    @staticmethod
    async def get_tts_base64(text: str, db: AsyncSession):
        audio_content = await TTS.get_tts(text, db)
        return base64.b64encode(audio_content).decode("utf-8")


@app.post("/get_tts_base64")
async def get_tts_base64(item: TextItem, db: AsyncSession = Depends(get_db)):
    audio_base64 = await TTS.get_tts_base64(item.text, db)
    headers = {"Cache-Control": "max-age=3600"}
    return JSONResponse(content={"audio_base64": audio_base64}, headers=headers)


@app.post("/get_multiple_tts")
async def get_multiple_tts(items: TextList, db: AsyncSession = Depends(get_db)):
    audio_contents = [
        {"text": text, "base64": await TTS.get_tts_base64(text, db)}
        for text in items.texts
    ]
    headers = {"Cache-Control": "max-age=3600"}
    return JSONResponse(content=audio_contents, headers=headers)


@app.get("/get_tts_base64")
async def get_tts_base64_query(text: str = Query(...), db: AsyncSession = Depends(get_db)):
    audio_base64 = await TTS.get_tts_base64(text, db)
    headers = {"Cache-Control": "max-age=3600"}
    return JSONResponse(content={"audio_base64": audio_base64}, headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3000)
