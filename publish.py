import base64
import hashlib
import io
import os
from pathlib import Path
import re
import sys
import urllib.parse
import wave

import boto3
import ffmpeg
from dotenvx import load_dotenvx
import requests
from mypy_boto3_s3 import S3Client
from pydantic import BaseModel
from markdown import markdown

load_dotenvx()

CLOUDFLARE_ACCOUNT_ID = os.environ["CLOUDFLARE_ACCOUNT_ID"]
CLOUDFLARE_R2_BUCKET_NAME = os.environ["CLOUDFLARE_R2_BUCKET_NAME"]
CLOUDFLARE_R2_ACCESS_KEY_ID = os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"]
CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"]
CLOUDFLARE_R2_PUBLIC_BASE_URL = os.environ["CLOUDFLARE_R2_PUBLIC_BASE_URL"]


class Scrap(BaseModel):
    path: str
    text: str
    mp3: str
    hash: str


if __name__ == "__main__":
    articles_dir = Path(__file__).parent / "articles"
    files = sorted(articles_dir.glob("*.md"))

        # r2: S3Client = boto3.client(
        #     "s3",
        #     endpoint_url=f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com",
        #     aws_access_key_id=CLOUDFLARE_R2_ACCESS_KEY_ID,
        #     aws_secret_access_key=CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        #     region_name="auto",
        # )

    items: list[Scrap] = []
    for file in files:
        md = file.read_text("utf-8")

        filename = file.name

        object_key = f"scraps/{re.sub(r'\.md$', '.mp3', filename)}"

        h2_match = re.search(r'^##\s+(.+)$', md, re.MULTILINE)
        if h2_match:
            title_text = h2_match.group(1).strip()
            body_text = re.sub(r"<[^>]+>", "", markdown(md[h2_match.end():].strip()))
        else:
            title_text = None
            body_text = re.sub(r"<[^>]+>", "", markdown(md))

        print(f"Processing: {filename} (title={bool(title_text)}, body={len(body_text)} chars)", file=sys.stderr)

        sections: list[tuple[bool, str]] = []
        if title_text:
            sections.append((True, title_text))
        current = ""
        for line in body_text.splitlines(keepends=True):
            if len(current) + len(line) <= 500:
                current += line
            else:
                if current:
                    sections.append((False, current))
                current = line
        if current:
            sections.append((False, current))
        sections = [(is_title, c) for is_title, c in sections if c.strip()]

        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wav_out:
            for i, (is_title, chunk) in enumerate(sections):
                query = requests.post(
                    f"http://localhost:50021/audio_query"
                    f"?text={urllib.parse.quote(chunk)}&speaker=1"
                )
                query.raise_for_status()
                query_json = query.json()
                query_json["speedScale"] = 1.5
                synth = requests.post(
                    "http://localhost:50021/synthesis?speaker=1",
                    headers={"Content-Type": "application/json"},
                    json=query_json,
                )
                synth.raise_for_status()
                with wave.open(io.BytesIO(synth.content)) as w:
                    if i == 0:
                        wav_out.setparams(w.getparams())
                    wav_out.writeframes(w.readframes(w.getnframes()))
                    if is_title:
                        wav_out.writeframes(b"\x00" * w.getsampwidth() * w.getframerate())

        mp3, _ = (
            ffmpeg
            .input("pipe:", format="wav")
            .output("pipe:", format="mp3", audio_bitrate="128k", qscale=2)
            .run(input=wav_buf.getvalue(), capture_stdout=True, capture_stderr=True)
        )

        mp3_path = Path(__file__).parent / object_key
        mp3_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path.write_bytes(mp3)
        print(f"Saved: {mp3_path}", file=sys.stderr)

        # r2.put_object(
        #     Bucket=CLOUDFLARE_R2_BUCKET_NAME,
        #     Key=object_key,
        #     Body=mp3,
        #     ContentType="audio/mpeg",
        # )

        # items.append(Scrap(
        #     path=f"scraps/{filename}",
        #     text=text,
        #     mp3=f"{CLOUDFLARE_R2_PUBLIC_BASE_URL}/{object_key}",
        #     hash=hashlib.sha256(md.encode()).hexdigest(),
        # ))

    # username = os.environ['BASIC_AUTH_USERNAME']
    # password = os.environ['BASIC_AUTH_PASSWORD']
    # token = base64.b64encode(f"{username}:{password}".encode()).decode()

    # requests.post(
    #     f"https://hrkmtsmt.me/api/scraps:bulk",
    #     headers={
    #         "Authorization": f"Basic {token}",
    #         "Content-Type": "application/json",
    #     },
    #     json=[item.model_dump(mode="json") for item in items],
    # ).raise_for_status()
