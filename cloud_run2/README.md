# Cloud Run ADC 챗봇

`cloud_run2`는 Cloud Run에 연결된 서비스 계정의 Application Default Credentials
(ADC)로 Gemini Enterprise Agent Platform(이전 Vertex AI)을 호출합니다.
`cloud_run`의 API 키 버전과 별도로 실행하고 배포할 수 있습니다.

실제 IDE 화면과 단계별 명령은 [ADC 배포 실습 HTML](../Antigravity_IDE_Cloud_Run2_ADC_배포_실습가이드.html)에 정리합니다.

## 이번 실습의 공개 서비스

- **[챗봇 바로 열기](https://gemini-chatbot-adc-902882112756.us-central1.run.app)** — 별도 로그인 없이 접속합니다.
- 배포일: 2026년 9월 16일, 프로젝트 `sesac-dev-400904`, 리전 `us-central1`.
- 최종 리비전: `gemini-chatbot-adc-00002-bkq`, 트래픽 100%.
- 사용자 승인으로 전용 실행·빌드 계정과 IAM 역할을 생성하고 공개 호출을 허용했습니다.
- 실제 확인: `/api/health` 정상, `/api/status`의 ADC 설정, Gemini 3.8 Flash 응답과 후속 질문의 대화 문맥 유지.
- **서비스를 유지 중입니다.** 삭제하거나 자동 삭제 일정을 등록하지 않았습니다.

아래 스크립트의 기본값은 비공개입니다. 이번처럼 공개 상태로 재배포하려면 다음 명령을 사용합니다.

```bash
PROJECT_ID=sesac-dev-400904 ALLOW_UNAUTHENTICATED=true bash cloud_run2/deploy/deploy.sh
```

## 인증의 흐름

1. **배포하는 사람**: Antigravity IDE 통합 터미널의 `gcloud auth login` 계정으로 배포합니다.
2. **Cloud Run 앱 → Gemini**: 연결한 실행 서비스 계정의 ADC로 인증합니다.
   `google.auth.default()`가 메타데이터 서버에서 자격 증명을 얻고 SDK가 토큰을 갱신합니다.
3. **사용자 → 챗봇**: Cloud Run 호출 인증은 별개입니다. 이번 서비스는 공개로 배포했습니다.
   스크립트 기본값인 비공개로 배포했다면 `gcloud run services proxy`로 테스트합니다.

서비스 계정 JSON 키, Gemini API 키, Secret Manager 시크릿 주입은 필요하지 않습니다.
Cloud Run 컨테이너에서 `gcloud auth application-default login`을 실행하지 않습니다.
첨부 화면의 ADC 설정 스크립트는 개발 환경 설정을 돕는 방법이며,
Cloud Run에서는 연결된 서비스 계정이 ADC의 출처입니다.

```python
credentials, adc_project = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
client = genai.Client(
    enterprise=True,
    credentials=credentials,
    project="your-project-id",
    location="global",
)
```

## 로컬 실행

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
cd cloud_run2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# .env의 GOOGLE_CLOUD_PROJECT를 실제 프로젝트 ID로 수정
python server.py
```

브라우저: <http://localhost:8080>. 로컬 사용자에게도 모델 호출 IAM 권한이 필요합니다.
ADC를 찾지 못하거나 프로젝트가 없으면 시작 시 오류를 내어 잘못된 설정을 알립니다.
환경변수는 `.env`보다 우선합니다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `GOOGLE_CLOUD_PROJECT` | ADC의 프로젝트 | 모델 호출 및 할당량 프로젝트. 배포 시 명시합니다. |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini API 호출 위치. Cloud Run 배포 리전과 별도입니다. |
| `PORT` | `8080` | Cloud Run이 주입하는 컨테이너 포트 |
| `CHAT_TIMEOUT_SECONDS` | `240` | 생성부터 폴링까지의 전체 시간 제한 |

## Cloud Run 배포

프로젝트 루트에서 실행합니다. `--dry-run`은 명령만 출력합니다.

```bash
PROJECT_ID=sesac-dev-400904 bash cloud_run2/deploy/deploy.sh --dry-run
PROJECT_ID=sesac-dev-400904 bash cloud_run2/deploy/deploy.sh
```

스크립트의 기본 리소스:

| 항목 | 값 |
| --- | --- |
| 서비스 | `gemini-chatbot-adc` |
| 리전 | `us-central1` |
| 실행 서비스 계정 | `gemini-chatbot-adc-run@PROJECT_ID.iam.gserviceaccount.com` |
| 실행 계정 권한 | 프로젝트의 `roles/aiplatform.user` |
| 빌드 서비스 계정 | `gemini-chatbot-adc-build@PROJECT_ID.iam.gserviceaccount.com` |
| 빌드 계정 권한 | 프로젝트의 `roles/run.builder` |
| 리소스 | 1 vCPU, 512 MiB, 동시 요청 20, 최소 0 / 최대 3 인스턴스 |
| 요청 제한 | 300초 |
| 웹 접속 | IAM 인증 필요 |

배포 계정에는 API 활성화, 서비스 계정 생성·사용, 프로젝트 IAM 변경,
Cloud Run 소스 배포 권한이 필요합니다. 스크립트는 필요한 API를 활성화하고,
두 계정을 준비한 뒤 역할을 부여합니다. IAM 전파에는 시간이 걸릴 수 있습니다.

Cloud Build가 `cloud_run2/Dockerfile`로 이미지를 빌드하고 Artifact Registry에 저장합니다.
Cloud Run은 일반 사용자로 `0.0.0.0:$PORT`에서 앱을 실행합니다.
`.gcloudignore`와 `.dockerignore`는 실행에 필요한 파일만 포함합니다.
기존 서비스에 재배포할 경우 시크릿 바인딩 및 API 키/자격 증명 파일 경로 환경변수를 제거합니다.

옵션은 `bash cloud_run2/deploy/deploy.sh --help`에서 확인합니다.
공개 웹 URL이 필요한 경우에만 `ALLOW_UNAUTHENTICATED=true`로 배포합니다.
공개 상태에서는 다른 사람도 모델 호출을 할 수 있고 해당 프로젝트에 사용량이 발생합니다.

## 배포 후 테스트

이번 공개 배포는 위의 챗봇 링크를 브라우저에서 바로 엽니다.

```bash
curl -fsS https://gemini-chatbot-adc-902882112756.us-central1.run.app/api/health
curl -fsS https://gemini-chatbot-adc-902882112756.us-central1.run.app/api/status
```

서비스 상태 조회 및 **비공개로 배포한 경우에만** 사용하는 접속 방법:

```bash
gcloud run services describe gemini-chatbot-adc \
  --project=sesac-dev-400904 --region=us-central1 \
  --format='yaml(status.url,status.latestReadyRevisionName,status.conditions)'

gcloud run services proxy gemini-chatbot-adc \
  --project=sesac-dev-400904 --region=us-central1 --port=8080
```

프록시 실행 중 <http://127.0.0.1:8080>에서 실제 Cloud Run 챗봇을 테스트합니다.
사용한 gcloud 계정에는 서비스 호출 권한이 필요합니다.
프록시를 Ctrl+C로 종료해도 Cloud Run 서비스는 유지됩니다.
배포 스크립트에 삭제 작업이나 자동 정리 일정은 없습니다.
최소 인스턴스 0은 유휴 상태의 컨테이너를 줄이는 설정이며 서비스 삭제가 아닙니다.

- `/api/health`: 외부 접속 및 컨테이너 시작 확인. `/healthz`는 호환 경로이며 이 실습에서 외부 요청은 Google 404 응답을 받았습니다.
- `/api/status`: `authMode: "ADC"`, 프로젝트, 위치, `credentialsConfigured` 확인.
  이 값은 클라이언트 준비 상태이며 실제 IAM 권한·모델 호출 성공을 보장하지 않습니다.
- `/api/chat`: 실제 모델 호출. 기존 UI의 질문, 모델 선택, 음성 입력, 대화 문맥 기능을 유지합니다.

기본 모델은 Gemini 3.8 Flash입니다. 3.7 Flash와 Antigravity Preview도 선택할 수 있습니다.
일반 모델은 `models.generate_content`를 호출하고, 관리형 에이전트는 `agent`와 `environment`를 사용하는
Interactions API를 호출합니다. 실제 검증에서 Agent Platform의 Gemini 3.8 모델 Interactions 요청은
`Unsupported model interaction`으로 거절되어, 성공한 generateContent 방식으로 수정했습니다.
일반 모델의 문맥은 브라우저가 최근 20개 메시지를 요청마다 전달하며 각 메시지는 최대 10,000자입니다.
페이지 새로고침 시 문맥이 초기화됩니다. 에이전트의 환경 ID와 대화 ID도 브라우저에서 보관하며,
모델 변경이나 새 대화 시 초기화합니다. 긴 에이전트 작업은 앱의 240초 제한을 넘을 수 있습니다.
사용 가능한 모델과 에이전트는 프로젝트의 활성화·권한·할당량에 따라 달라집니다.
이번 실제 브라우저 검증은 기본 모델 3.8 Flash로 진행했습니다. 3.7 Flash와 관리형 에이전트의
실제 응답은 이 실습에서 검증하지 않았습니다.

## 검증

```bash
python -m pip install -r cloud_run2/requirements-dev.txt
python -m unittest discover -s cloud_run2/tests -v
node --check cloud_run2/public/app.js
```

테스트에서는 ADC와 외부 응답을 모의 처리하며 클라우드 자격 증명을 읽거나 모델을 호출하지 않습니다.

## 공식 자료

- [Agent Platform 시작 및 ADC](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Cloud Run 서비스 신원](https://docs.cloud.google.com/run/docs/securing/service-identity)
- [Cloud Run 소스 배포](https://docs.cloud.google.com/run/docs/deploying-source-code)
- [관리형 에이전트 호출](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/interact-with-agents)
