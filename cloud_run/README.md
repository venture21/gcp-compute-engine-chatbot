# Cloud Run용 Gemini 챗봇

기존 챗봇의 한국어 UI, 모델 선택, 음성 입력, 마크다운 응답 및 대화 문맥 유지를
Cloud Run에서 사용할 수 있도록 구성한 독립 실행형 Python 앱입니다.

## 구성

- `server.py`: FastAPI, 비동기 Google GenAI SDK, 정적 파일 제공
- `public/`: HTML/CSS/JavaScript UI. API 요청은 같은 호스트의 `/api/*`를 사용합니다.
- `Dockerfile`: Python 3.12 컨테이너. 일반 사용자로 `0.0.0.0:$PORT`에서 실행합니다.
- `deploy/deploy.sh`: API 활성화, 서비스 계정/권한 구성 및 Cloud Run 소스 배포
- `.gcloudignore`, `.dockerignore`: 실행에 필요한 파일만 업로드/이미지에 포함
- `tests/`: 외부 Gemini 호출 없이 실행하는 API 및 배포 스크립트 검증

Cloud Run이 HTTPS를 제공하므로 Nginx, Certbot, VM 메타데이터 및 특정 IP 주소 설정이
필요하지 않습니다. 런타임은 Secret Manager에서 주입된 `GEMINI_API_KEY` 환경변수를 사용합니다.
포트와 TLS 처리 방식은 [Cloud Run 컨테이너 규약](https://docs.cloud.google.com/run/docs/container-contract)을 따릅니다.

## 1. 로컬 실행

저장소 루트에서 실행합니다. Python 3.11 이상이 필요합니다.

```bash
cd cloud_run
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# .env의 GEMINI_API_KEY를 실제 키로 수정
python server.py
```

접속: [http://localhost:8080](http://localhost:8080)

| 환경변수 | 기본값 | 용도 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 없음 | Gemini API 키. 시스템 환경변수가 `.env`보다 우선합니다. |
| `PORT` | `8080` | 로컬 포트. Cloud Run에서는 플랫폼이 주입합니다. |
| `CHAT_TIMEOUT_SECONDS` | `240` | API 생성 호출부터 폴링 완료까지의 전체 시간 제한 |

키가 없으면 웹 UI와 상태 확인은 가능하고 채팅 API는 `503`을 반환합니다.
`/api/status`의 `hasApiKey`는 키 설정 여부이며 실제 Gemini 인증 성공 여부는 아닙니다.

## 2. Docker로 실행

아래 명령은 `cloud_run/`에서 실행합니다.

```bash
docker build -t gemini-chatbot-cloud-run .
docker run --rm --env-file .env -p 8080:8080 gemini-chatbot-cloud-run
```

환경변수 `PORT`를 변경했다면 컨테이너 포트 매핑도 같은 값으로 변경합니다.
`.env`는 이미지에 복사되지 않습니다.

## 3. Cloud Run 배포

### 사전 준비

1. 결제가 연결된 Google Cloud 프로젝트와 Google Cloud CLI를 준비합니다.
2. `gcloud auth login`으로 배포할 계정에 로그인합니다.
3. 프로젝트의 Secret Manager에 `GEMINI_API_KEY` 시크릿과 활성 버전을 준비합니다.
   기존 Compute Engine과 같은 프로젝트라면 기존 시크릿을 재사용할 수 있습니다.
4. 배포 계정에는 API 활성화, 서비스 계정 생성/사용, IAM 정책 변경,
   Secret Manager 메타데이터 조회/권한 변경 및 Cloud Run 배포 권한이 필요합니다.
   조직에서 권한을 관리하는 경우 관리자에게 계정과 IAM 설정을 요청합니다.

스크립트는 런타임 계정(`gemini-chatbot-run`)에 해당 시크릿의
`roles/secretmanager.secretAccessor`만 부여하고, 빌드 계정(`gemini-chatbot-build`)에는
프로젝트의 `roles/run.builder`를 부여합니다. 배포자는 두 계정에 대한
`iam.serviceAccounts.actAs` 권한이 필요합니다.
[소스 배포 권한 안내](https://docs.cloud.google.com/run/docs/deploying-source-code),
[Secret Manager 연동 안내](https://docs.cloud.google.com/run/docs/configuring/services/secrets)를 참고하세요.

### 실행할 명령 미리 확인

저장소 루트에서 실행합니다. `--dry-run`은 클라우드를 조회하거나 변경하지 않습니다.

```bash
PROJECT_ID=your-project-id \
SECRET_VERSION=1 \
bash cloud_run/deploy/deploy.sh --dry-run
```

`SECRET_VERSION`은 실제 활성 버전 번호로 변경합니다. 기본값은 `1`입니다.
환경변수 시크릿은 인스턴스 시작 시 읽히므로, 키를 교체한 뒤 새 버전 번호로 재배포합니다.

### 배포 실행

```bash
PROJECT_ID=your-project-id \
REGION=us-central1 \
SERVICE_NAME=gemini-chatbot \
SECRET_VERSION=1 \
bash cloud_run/deploy/deploy.sh
```

기본 배포는 IAM 인증이 필요합니다. 로그인한 배포 계정에 Cloud Run Invoker 권한이 있으면
다음 프록시를 통해 브라우저에서 접속할 수 있습니다.

```bash
gcloud run services proxy gemini-chatbot \
  --project=your-project-id --region=us-central1 --port=8080
```

일반 브라우저에서 서비스 URL로 직접 접속할 공개 챗봇은 배포 명령에
`ALLOW_UNAUTHENTICATED=true`를 추가합니다. 이 경우 누구나 채팅 API를 호출할 수 있으며
Cloud Run과 Gemini 사용 요금은 프로젝트/API 키 소유자에게 청구됩니다.

스크립트는 Dockerfile을 이용해 Cloud Build에서 이미지를 빌드한 뒤 배포합니다.
로컬 Docker 설치는 소스 배포에 필요하지 않습니다. 완료 시 HTTPS 서비스 URL을 출력합니다.
IAM 권한을 처음 부여한 직후 전파 지연으로 빌드가 실패하면 잠시 후 같은 명령을 재실행합니다.

기본 리소스 설정은 CPU 1개, 메모리 512MiB, 동시 요청 20개, 최소 인스턴스 0개,
최대 인스턴스 3개, 요청 제한 300초입니다. `MAX_INSTANCES`,
`CHAT_TIMEOUT_SECONDS`, `REQUEST_TIMEOUT_SECONDS`로 필요한 값을 변경할 수 있습니다.
전체 옵션은 `bash cloud_run/deploy/deploy.sh --help`에서 확인합니다.

## API와 대화 상태

- `GET /healthz`: 컨테이너 시작 확인용 상태 응답
- `GET /api/status`: 모델 목록, 기본 모델, API 키 설정 여부
- `POST /api/chat`: `input`, `model`, `previousInteractionId`를 받고
  `reply`, `interactionId`, `model`, `hasThought`, `toolsUsed`, `timestamp`를 반환

UI와 모델 목록은 Compute Engine 버전의 Gemini 3.8 Flash, Gemini 3.7 Flash,
Antigravity Preview를 유지합니다. 사용 가능한 모델/도구는 연결한 Gemini API 계정에 따릅니다.
[Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview)를 사용하며,
Cloud Run 버전은 최신 SDK의 `model`과 `environment="remote"` 형식을 사용합니다.

대화 ID는 브라우저가 보관하고 Gemini의 `previous_interaction_id`에 전달합니다.
서버 메모리나 로컬 파일에 대화를 저장하지 않으므로 다른 인스턴스가 다음 요청을 받아도
문맥을 이어갈 수 있습니다. 페이지를 새로 고치면 브라우저의 현재 대화는 초기화됩니다.

Gemini의 백그라운드 작업을 생성하되 폴링은 HTTP 요청이 열린 동안에만 수행합니다.
서버의 응답 제한은 Cloud Run 요청 제한보다 짧아야 합니다. 긴 연구 작업은
시간 제한을 넘으면 `504`를 반환하며, 이미 생성된 Gemini 작업은 원격에서 계속 실행될 수 있습니다.
추가 사용자 입력이 필요한 `requires_action` 작업은 이 UI에서 지원하지 않아 `502`를 반환합니다.

## 테스트

`cloud_run/`에서 실행합니다. API 키나 GCP 리소스 없이 검증할 수 있습니다.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```
