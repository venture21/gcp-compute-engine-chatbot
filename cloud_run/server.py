"""Cloud Run용 Gemini 챗봇: HTTP 요청 안에서 비동기로 생성 및 폴링한다."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from google import genai
from pydantic import BaseModel, Field
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("uvicorn.error")


def load_env_file():
    """로컬 .env는 보조로만 사용하며 Cloud Run이 주입한 환경변수를 우선한다."""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                os.environ.setdefault(key, value.strip().strip("\"'"))


load_env_file()

DEFAULT_MODEL = "gemini-3.8-flash"
CHAT_TIMEOUT_SECONDS = float(os.environ.get("CHAT_TIMEOUT_SECONDS", "240"))
if not 0 < CHAT_TIMEOUT_SECONDS < 3600:
    raise ValueError("CHAT_TIMEOUT_SECONDS는 0초보다 크고 3600초보다 작아야 합니다.")

TOOLS = [
    {"type": "code_execution"},
    {"type": "google_search"},
    {"type": "url_context"},
]
SUPPORTED_MODELS = [
    {
        "id": DEFAULT_MODEL,
        "name": "Gemini 3.8 Flash",
        "label": "사고 모델 (3.8 Flash)",
        "description": "구글 검색, 코드 실행, URL 컨텍스트를 지원하는 사고 모델",
        "isDefault": True,
        "isAgent": False,
    },
    {
        "id": "gemini-3.7-flash",
        "name": "Gemini 3.7 Flash",
        "label": "사고 모델 (3.7 Flash)",
        "description": "빠른 응답과 추론을 위한 사고 모델",
        "isDefault": False,
        "isAgent": False,
    },
    {
        "id": "antigravity-preview-05-2026",
        "name": "Antigravity Preview",
        "label": "연구 에이전트 모델",
        "description": "원격 환경에서 작업하는 연구 에이전트",
        "isDefault": False,
        "isAgent": True,
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Secret Manager 접근은 Cloud Run의 환경변수 주입에 맡긴다.
    # 키가 없는 로컬 환경에서도 UI와 상태 확인은 가능하다.
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key == "your_gemini_api_key_here":
        api_key = ""
    client = genai.Client(api_key=api_key) if api_key else None
    app.state.genai_client = client.aio if client else None
    if client is None:
        logger.warning("GEMINI_API_KEY가 설정되지 않았습니다. 채팅 API는 비활성 상태입니다.")
    try:
        yield
    finally:
        if client:
            await client.aio.aclose()
            client.close()


app = FastAPI(title="Gemini Chatbot — Cloud Run", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    input: str = Field(max_length=10000)
    model: str | None = None
    previousInteractionId: str | None = Field(default=None, max_length=512)


def timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@app.get("/healthz")
async def healthcheck():
    return {"status": "ok"}


@app.get("/api/status")
async def get_status(request: Request):
    return {
        "status": "ok",
        "defaultModel": DEFAULT_MODEL,
        "models": SUPPORTED_MODELS,
        "hasApiKey": request.app.state.genai_client is not None,
        "timestamp": timestamp(),
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    user_input = req.input.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="질문 내용을 입력해주세요.")

    selected_model = req.model or DEFAULT_MODEL
    model_info = next((m for m in SUPPORTED_MODELS if m["id"] == selected_model), None)
    if model_info is None:
        raise HTTPException(status_code=400, detail="지원하지 않는 모델입니다.")

    client = request.app.state.genai_client
    if client is None:
        raise HTTPException(status_code=503, detail="서버에 GEMINI_API_KEY를 설정해주세요.")

    kwargs = {"model": selected_model, "input": user_input, "background": True, "tools": TOOLS}
    if model_info["isAgent"]:
        kwargs["environment"] = "remote"
    if req.previousInteractionId:
        kwargs["previous_interaction_id"] = req.previousInteractionId

    try:
        # Cloud Run 요청 제한보다 짧은 전체 제한을 생성 호출부터 적용한다.
        # SDK의 async API를 사용하여 다른 채팅 및 상태 요청을 막지 않는다.
        async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
            interaction = await client.interactions.create(**kwargs)
            poll_interval = 1.0
            while interaction.status in ("in_progress", "queued"):
                await asyncio.sleep(poll_interval)
                interaction = await client.interactions.get(interaction.id)
                poll_interval = min(poll_interval + 0.3, 3.0)

        if interaction.status != "completed":
            logger.warning("Gemini interaction ended with status %s", interaction.status)
            raise HTTPException(status_code=502, detail="Gemini 작업이 완료되지 않았습니다. 새 대화에서 다시 시도해주세요.")

        step_types = [getattr(step, "type", "") for step in (getattr(interaction, "steps", None) or [])]
        return {
            "reply": interaction.output_text or "",
            "interactionId": interaction.id,
            "model": selected_model,
            "hasThought": "thought" in step_types,
            "toolsUsed": {
                "googleSearch": any("google_search" in step for step in step_types),
                "codeExecution": any("code_execution" in step for step in step_types),
            },
            "timestamp": timestamp(),
        }
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"Gemini 응답 시간이 {CHAT_TIMEOUT_SECONDS:g}초를 초과했습니다.") from None
    except HTTPException:
        raise
    except Exception as exc:
        # SDK 오류에는 요청 정보가 포함될 수 있으므로 원문을 사용자/로그에 노출하지 않는다.
        logger.error("Gemini request failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Gemini API 요청에 실패했습니다. 잠시 후 다시 시도해주세요.") from None


app.mount("/", StaticFiles(directory=str(BASE_DIR / "public"), html=True), name="static")


if __name__ == "__main__":
    # Cloud Run은 PORT를 주입한다. TLS는 Cloud Run 프런트엔드에서 처리한다.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="info")
