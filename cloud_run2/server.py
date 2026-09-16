"""Cloud Run 서비스 계정의 ADC로 Gemini Enterprise Agent Platform을 호출한다."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from google import genai
import google.auth
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
ADC_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
CHAT_TIMEOUT_SECONDS = float(os.environ.get("CHAT_TIMEOUT_SECONDS", "240"))
if not 0 < CHAT_TIMEOUT_SECONDS < 3600:
    raise ValueError("CHAT_TIMEOUT_SECONDS는 0초보다 크고 3600초보다 작아야 합니다.")

MODEL_TOOLS = [
    {"code_execution": {}},
    {"google_search": {}},
    {"url_context": {}},
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
    # Cloud Run에서는 연결된 서비스 계정을 메타데이터 서버에서 자동으로 찾는다.
    # 로컬에서는 gcloud auth application-default login으로 만든 ADC를 사용한다.
    credentials, adc_project = await asyncio.to_thread(google.auth.default, scopes=ADC_SCOPES)
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or adc_project
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT를 설정해주세요.")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global").strip() or "global"
    client = genai.Client(
        enterprise=True, credentials=credentials, project=project, location=location,
    )
    app.state.genai_client = client.aio
    app.state.project = project
    app.state.location = location
    logger.info("Gemini client configured with ADC (project=%s, location=%s)", project, location)
    try:
        yield
    finally:
        await client.aio.aclose()
        client.close()


app = FastAPI(title="Gemini Chatbot — Cloud Run ADC", version="2.0.0", lifespan=lifespan)


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=10000)


class ChatRequest(BaseModel):
    input: str = Field(max_length=10000)
    model: str | None = None
    previousInteractionId: str | None = Field(default=None, max_length=512)
    environmentId: str | None = Field(default=None, max_length=512)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


def timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@app.get("/healthz")
@app.get("/api/health")
async def healthcheck():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/api/status")
async def get_status(request: Request):
    return {
        "status": "ok",
        "defaultModel": DEFAULT_MODEL,
        "models": SUPPORTED_MODELS,
        "authMode": "ADC",
        "credentialsConfigured": request.app.state.genai_client is not None,
        "project": request.app.state.project,
        "location": request.app.state.location,
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
        raise HTTPException(status_code=503, detail="서버 인증 설정을 확인해주세요.")

    try:
        # 일반 Gemini 모델은 Agent Platform의 generateContent를 사용한다.
        # 문맥은 브라우저에서 전달받아 Cloud Run 인스턴스 간에도 이어진다.
        if not model_info["isAgent"]:
            contents = [
                {"role": turn.role, "parts": [{"text": turn.text}]}
                for turn in req.history
            ]
            contents.append({"role": "user", "parts": [{"text": user_input}]})
            async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
                max_retries = 3
                retry_delay = 1.5
                for attempt in range(max_retries + 1):
                    try:
                        response = await client.models.generate_content(
                            model=selected_model, contents=contents, config={"tools": MODEL_TOOLS},
                        )
                        break
                    except Exception as e:
                        err_code = getattr(e, "code", None) or getattr(e, "status_code", None)
                        if (err_code == 429 or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < max_retries:
                            logger.warning("Gemini 429 Rate limit hit, retrying in %.1fs (attempt %d/%d)", retry_delay, attempt + 1, max_retries)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                        raise

            reply = response.text or ""
            if not reply.strip():
                raise HTTPException(status_code=502, detail="Gemini가 텍스트 응답을 반환하지 않았습니다. 질문을 바꿔 다시 시도해주세요.")
            candidates = response.candidates or []
            candidate = candidates[0] if candidates else None
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            grounding = getattr(candidate, "grounding_metadata", None)
            usage = getattr(response, "usage_metadata", None)
            return {
                "reply": reply, "interactionId": None, "environmentId": None,
                "model": selected_model,
                "hasThought": bool(getattr(usage, "thoughts_token_count", 0)),
                "toolsUsed": {
                    "googleSearch": bool(getattr(grounding, "web_search_queries", None)),
                    "codeExecution": any(getattr(p, "executable_code", None) or getattr(p, "code_execution_result", None) for p in parts),
                },
                "timestamp": timestamp(),
            }

        # 관리형 에이전트는 Interactions API와 원격 환경을 사용한다.
        kwargs = {"agent": selected_model, "input": user_input, "background": True,
                  "environment": req.environmentId or {"type": "remote"}}
        if req.previousInteractionId:
            kwargs["previous_interaction_id"] = req.previousInteractionId
        async with asyncio.timeout(CHAT_TIMEOUT_SECONDS):
            max_retries = 3
            retry_delay = 1.5
            for attempt in range(max_retries + 1):
                try:
                    interaction = await client.interactions.create(**kwargs)
                    break
                except Exception as e:
                    err_code = getattr(e, "code", None) or getattr(e, "status_code", None)
                    if (err_code == 429 or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and attempt < max_retries:
                        logger.warning("Gemini interactions 429 hit, retrying in %.1fs (attempt %d/%d)", retry_delay, attempt + 1, max_retries)
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    raise

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
            "environmentId": getattr(interaction, "environment_id", None),
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
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        logger.error("Gemini request failed (%s, code=%s)", type(exc).__name__, code if isinstance(code, int) else "unknown")
        if code == 429 or "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            raise HTTPException(status_code=429, detail="일시적으로 요청이 몰려 할당량(Rate Limit)을 초과했습니다. 몇 초 후 다시 시도해주세요.") from None
        raise HTTPException(status_code=502, detail="Gemini API 요청에 실패했습니다. 잠시 후 다시 시도해주세요.") from None


app.mount("/", StaticFiles(directory=str(BASE_DIR / "public"), html=True), name="static")


if __name__ == "__main__":
    # Cloud Run은 PORT를 주입한다. TLS는 Cloud Run 프런트엔드에서 처리한다.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_level="info")
