# Google Gemini 3.8 Flash & 3.7 Flash 웹 챗봇 (Python google-genai 기반)

Google Gemini 공식 웹 앱([gemini.google.com](https://gemini.google.com/app?hl=ko))의 최신 디자인을 기반으로 제작된 한국어 대화형 AI 챗봇입니다.  
공식 `google-genai` Python SDK의 **Interactions API**를 활용하며, **Gemini 3.8 Flash**를 기본 사고 모델로 사용합니다. 필요시 **Gemini 3.7 Flash** 및 연구용 **Antigravity Preview 에이전트**를 실시간으로 선택하여 대화할 수 있습니다.

---

## ✨ 주요 기능 및 아키텍처

1. **공식 `google-genai` SDK Interactions API 연동**:
   - `client.interactions.create(..., background=True, tools=tools)` 및 `client.interactions.get()` 비동기 폴링 루프 기반
   - 탑재 도구:
     - `google_search`: 최신 실시간 웹 정보 검색 및 팩트 체크
     - `code_execution`: 파이썬 코드 실행 및 연산 검증
     - `url_context`: 웹 문서 및 URL 컨텍스트 분석
2. **Google Gemini 공식 UI 완벽 재현**:
   - 은은하고 부드러운 스카이블루 오로라 배경 (`radial-gradient`)
   - `"박희진님, 안녕하세요. 어떻게 도와드릴까요?"` 개인화 환영 헤딩
   - 플로팅 알약형(Pill-shaped) 입력창, Gemini 스파클 로고, `+` 첨부 버튼, 마이크(`🎙️`) 음성 인식 버튼
   - `사고 모델 v` 드롭다운 팝오버를 통한 모델 실시간 전환
3. **AI 모델 및 에이전트 선택 지원**:
   - **Gemini 3.8 Flash** (기본): 복잡한 문제 해결 및 심층 추론 역량을 갖춘 최신 플래그십 플래시 사고 모델
   - **Gemini 3.7 Flash**: 빠른 반응성과 신속한 작업 처리에 최적화된 고속 사고 모델
   - **Antigravity Agent (`antigravity-preview-05-2026`)**: 격리 원격 환경에서 심층 연구 및 도구 자율 실행을 지원하는 연구 에이전트
   - 모델별 '사고 과정(Thinking...)' 상태 표시 및 실시간 검색/도구 연동 뱃지 안내
4. **환경변수 API 키 관리**:
   - 서버의 시스템 환경변수 `GEMINI_API_KEY`를 자동 감지하여 안전하게 연동
   - 브라우저 클라이언트에는 API 키를 일절 노출하지 않는 안전한 백엔드 프록시 구조
5. **멀티턴(Multi-turn) 대화 문맥 유지**:
   - Google Interactions API의 `previous_interaction_id`를 활용하여 이전 대화 문맥을 자연스럽게 기억하고 답변
6. **한국어 사용자 경험(UX) 최적화**:
   - 한글 IME 입력 중 Enter 키 중복 발송 방지 (`isComposing`, `keyCode: 229` 처리)
   - Web Speech API 음성 인식 지원 (마이크 클릭 시 한국어 음성을 텍스트로 실시간 변환)
   - 마크다운 서식 지원 (코드 블록, 신택스 강조, 원클릭 복사 버튼 등)

---

## 🚀 빠른 시작 가이드

### 1. 환경변수 확인
시스템 환경변수에 `GEMINI_API_KEY`가 등록되어 있는지 확인합니다:
```bash
echo $GEMINI_API_KEY
```

### 2. 서버 실행
FastAPI 및 `google-genai` 기반 서버를 실행합니다:
```bash
python3 server.py
# 또는
npm start
```

### 3. 브라우저 접속
서버 실행 후 웹 브라우저에서 아래 주소로 접속합니다:
👉 **[http://127.0.0.1:3000](http://127.0.0.1:3000)**

---

## 📁 프로젝트 구조

```text
gcp-compute-engine-chatbot/
├── server.py           # Python GenAI 백엔드 (client.interactions 백그라운드 폴링 및 도구 연동)
├── server.mjs          # Node.js 백엔드 서버 (대체 서버)
├── package.json        # 실행 스크립트 및 메타데이터
├── .env.example        # 환경 변수 템플릿
├── .gitignore          # Git 형상관리 제외 설정
├── README.md           # 프로젝트 안내 문서
└── public/             # 프론트엔드 정적 리소스
    ├── index.html      # Gemini 웹 레이아웃 (헤더, 환영 화면, 채팅 뷰, 플로팅 입력바)
    ├── style.css       # Gemini 공식 스타일 (스카이블루 그라데이션, 알약 컨테이너, 애니메이션)
    └── app.js          # 대화 상태 관리, 모델 전환, IME 제어, 음성 인식, 마크다운 렌더링
```
