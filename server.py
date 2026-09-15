import os
import time
import asyncio
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from google import genai
import uvicorn

# .env 파일 수동 로드 (환경변수 보조)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip("\"'")
            if k and not os.environ.get(k):
                os.environ[k] = v

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Google GenAI Client 초기화
client = genai.Client(
    api_key=GEMINI_API_KEY,
)

# 사용자 요청에 명시된 도구 목록 (Code execution, Google search, URL context)
TOOLS = [
    {
        'type': 'code_execution',
    },
    {
        'type': 'google_search',
    },
    {
        'type': 'url_context',
    },
]

SUPPORTED_MODELS = [
    {
        "id": "gemini-3.8-flash",
        "name": "Gemini 3.8 Flash",
        "label": "사고 모델 (3.8 Flash)",
        "description": "최신 플래그십 사고 모델 (도구 지원: 구글 검색, 코드 실행, 웹 컨텍스트)",
        "isDefault": True,
        "isAgent": False
    },
    {
        "id": "gemini-3.7-flash",
        "name": "Gemini 3.7 Flash",
        "label": "사고 모델 (3.7 Flash)",
        "description": "고속 사고 모델 (균형 잡힌 추론 및 신속한 반응 속도)",
        "isDefault": False,
        "isAgent": False
    },
    {
        "id": "antigravity-preview-05-2026",
        "name": "Antigravity Preview",
        "label": "연구 에이전트 모델",
        "description": "심층 연구 및 원격 격리 환경 자율 추론 에이전트 모델",
        "isDefault": False,
        "isAgent": True
    }
]

app = FastAPI(title="Gemini Chatbot API", version="2.0.0")

class ChatRequest(BaseModel):
    input: str
    model: Optional[str] = "gemini-3.8-flash"
    previousInteractionId: Optional[str] = None

@app.get("/api/status")
async def get_status():
    return {
        "status": "ok",
        "defaultModel": "gemini-3.8-flash",
        "models": SUPPORTED_MODELS,
        "hasApiKey": bool(GEMINI_API_KEY and len(GEMINI_API_KEY) > 5),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    user_input = req.input.strip()
    if not user_input:
        raise HTTPException(status_code=400, detail="질문 내용을 입력해주세요.")
    if len(user_input) > 10000:
        raise HTTPException(status_code=400, detail="질문 길이는 최대 10,000자까지 가능합니다.")

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="서버에 GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다.")

    selected_model_id = req.model or "gemini-3.8-flash"
    model_info = next((m for m in SUPPORTED_MODELS if m["id"] == selected_model_id), SUPPORTED_MODELS[0])

    try:
        # 1. Interaction 생성 파라미터 구성 (사용자 코드 참조)
        kwargs: Dict[str, Any] = {
            "input": user_input,
            "background": True,
            "tools": TOOLS,
        }

        if model_info.get("isAgent"):
            kwargs["agent"] = selected_model_id
            kwargs["environment"] = {
                'type': 'remote',
                'network': 'disabled',
            }
        else:
            kwargs["model"] = selected_model_id

        if req.previousInteractionId:
            kwargs["previous_interaction_id"] = req.previousInteractionId

        # 2. Interactions create 호출
        interaction = client.interactions.create(**kwargs)
        interaction_id = interaction.id

        # 3. 비동기 폴링 루프 (사용자 코드 참조: status == 'completed' / 'failed' 대기)
        start_time = time.time()
        timeout_seconds = 60.0
        poll_interval = 1.0

        while True:
            interaction = client.interactions.get(interaction_id)
            if interaction.status == "completed":
                break
            elif interaction.status == "failed":
                err_msg = str(getattr(interaction, "error", "Interaction execution failed"))
                raise HTTPException(status_code=502, detail=f"Gemini 처리 실패: {err_msg}")

            if time.time() - start_time > timeout_seconds:
                raise HTTPException(status_code=504, detail="Gemini 모델 응답 시간 초과 (60초)")

            await asyncio.sleep(poll_interval)
            # 폴링 주기를 점진적으로 조절
            poll_interval = min(poll_interval + 0.3, 3.0)

        reply_text = interaction.output_text or ""
        
        # steps 분석 (사고 과정 및 사용된 도구 파악)
        steps = getattr(interaction, "steps", []) or []
        step_types = [getattr(s, "type", "") for s in steps]
        has_thought = "thought" in step_types
        has_search = any("google_search" in st for st in step_types)
        has_code = any("code_execution" in st for st in step_types)

        return {
            "reply": reply_text,
            "interactionId": interaction.id,
            "model": selected_model_id,
            "hasThought": has_thought,
            "toolsUsed": {
                "googleSearch": has_search,
                "codeExecution": has_code
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Interaction error [{selected_model_id}]:", e)
        raise HTTPException(status_code=500, detail=f"API 처리 중 오류가 발생했습니다: {str(e)}")

# 정적 파일 서빙 (public 디렉터리)
public_dir = Path(__file__).parent / "public"
if public_dir.exists():
    app.mount("/", StaticFiles(directory=str(public_dir), html=True), name="static")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    print("=========================================")
    print(" Gemini Python GenAI Chatbot Server")
    print(f" URL: http://127.0.0.1:{port}")
    print(" Engine: google-genai client.interactions")
    print(" Tools: code_execution, google_search, url_context")
    print(f" API Key Loaded: {bool(GEMINI_API_KEY)}")
    print("=========================================")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
