from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import base64
import requests
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
from io import BytesIO
import os
from dotenv import load_dotenv
import redis.asyncio as redis

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:3000",
    "https://portal.shriijeesmartabacus.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TextItem(BaseModel):
    text: str


class TextList(BaseModel):
    texts: List[str]


class TTS:
    URL = os.getenv("TTS_BASE_URL")
    VOICE = "Microsoft Server Speech Text to Speech Voice (en-US, ZiraPro)"
    session = requests.Session()

    @staticmethod
    async def get_tts(text: str, redis_conn):
        text = text.lower().strip()
        cached_audio = await redis_conn.get(text)
        if cached_audio:
            return base64.b64decode(cached_audio)

        response = TTS.session.get(
            TTS.URL, params={"text": text, "voiceName": TTS.VOICE}
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code, detail="TTS request failed"
            )
        audio_content = response.content
        trimmed_audio = TTS.remove_silence(audio_content)
        await redis_conn.set(text, base64.b64encode(trimmed_audio).decode("utf-8"))
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
    async def get_tts_base64(text: str, redis_conn):
        audio_content = await TTS.get_tts(text, redis_conn)
        return base64.b64encode(audio_content).decode("utf-8")


async def get_redis():
    redis_conn = redis.from_url(
        f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}",
        encoding="utf-8",
        decode_responses=True,
    )
    return redis_conn


@app.post("/get_tts_base64")
async def get_tts_base64(item: TextItem, redis_conn=Depends(get_redis)):
    audio_base64 = await TTS.get_tts_base64(item.text, redis_conn)
    headers = {"Cache-Control": "max-age=3600"}
    return JSONResponse(content={"audio_base64": audio_base64}, headers=headers)


@app.post("/get_multiple_tts")
async def get_multiple_tts(items: TextList, redis_conn=Depends(get_redis)):
    audio_contents = [
        {"text": text, "base64": await TTS.get_tts_base64(text, redis_conn)}
        for text in items.texts
    ]
    headers = {"Cache-Control": "max-age=3600"}
    return JSONResponse(content=audio_contents, headers=headers)


@app.get("/get_tts_base64")
async def get_tts_base64_query(text: str = Query(...), redis_conn=Depends(get_redis)):
    audio_base64 = await TTS.get_tts_base64(text, redis_conn)
    headers = {"Cache-Control": "max-age=3600"}
    return JSONResponse(content={"audio_base64": audio_base64}, headers=headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=3000)
