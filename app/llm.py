"""Обращение к модели OpenAI: текст, картинки и PDF на вход, текст или JSON на выход."""
import base64
import json
import mimetypes
import time
import urllib.error
import urllib.request
from pathlib import Path

import config

URL = "https://api.openai.com/v1/responses"


def _file_part(path: Path):
    data = base64.b64encode(path.read_bytes()).decode()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".pdf":
        return {"type": "input_file", "filename": path.name, "file_data": f"data:application/pdf;base64,{data}"}
    return {"type": "input_image", "image_url": f"data:{mime};base64,{data}"}


def ask(prompt: str, files=(), schema: dict = None, system: str = None):
    """Возвращает текст ответа, а если передана схема — разобранный JSON."""
    if not config.OPENAI_API_KEY:
        raise RuntimeError("Нет ключа OpenAI: впиши OPENAI_API_KEY в файл .env")
    content = [{"type": "input_text", "text": prompt}] + [_file_part(Path(f)) for f in files]
    body = {"model": config.OPENAI_MODEL, "input": [{"role": "user", "content": content}]}
    if system:
        body["instructions"] = system
    if schema:
        body["text"] = {"format": {"type": "json_schema", "name": "result", "schema": schema, "strict": True}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}",
                                          "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                raise RuntimeError("Ключ OpenAI не подходит (неверный или отозван)") from e
            if e.code == 429 and "quota" in detail:
                raise RuntimeError("На ключе OpenAI кончились деньги или лимит") from e
            if attempt == 2 or e.code < 500 and e.code != 429:
                raise RuntimeError(f"OpenAI ответил ошибкой {e.code}: {detail}") from e
            time.sleep(3 * (attempt + 1))
    text = "".join(c.get("text", "") for o in data.get("output", []) if o.get("type") == "message"
                   for c in o.get("content", []) if c.get("type") == "output_text").strip()
    return json.loads(text) if schema else text
