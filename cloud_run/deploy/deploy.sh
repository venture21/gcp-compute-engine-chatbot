#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Cloud Run 소스 배포 (저장소 내 어느 디렉터리에서도 실행 가능)

  PROJECT_ID=my-project bash cloud_run/deploy/deploy.sh [--dry-run]

필수: PROJECT_ID, 프로젝트 내 기존 Secret Manager 시크릿 및 활성 버전
선택 환경변수:
  REGION=us-central1                SERVICE_NAME=gemini-chatbot
  SERVICE_ACCOUNT_ID=gemini-chatbot-run
  BUILD_SERVICE_ACCOUNT_ID=gemini-chatbot-build
  SECRET_NAME=GEMINI_API_KEY         SECRET_VERSION=1
  ALLOW_UNAUTHENTICATED=false       MAX_INSTANCES=3
  CHAT_TIMEOUT_SECONDS=240         REQUEST_TIMEOUT_SECONDS=300

--dry-run은 클라우드를 조회/변경하지 않고 실행할 명령을 출력합니다.
공개 웹 서비스로 배포하려면 ALLOW_UNAUTHENTICATED=true를 지정합니다.
EOF
}

DRY_RUN=false
case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --dry-run) DRY_RUN=true ;;
    "") ;;
    *) usage >&2; exit 1 ;;
esac
if (( $# > 1 )); then usage >&2; exit 1; fi

: "${PROJECT_ID:?PROJECT_ID 환경변수를 지정해주세요.}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-gemini-chatbot}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-gemini-chatbot-run}"
BUILD_SERVICE_ACCOUNT_ID="${BUILD_SERVICE_ACCOUNT_ID:-gemini-chatbot-build}"
SECRET_NAME="${SECRET_NAME:-GEMINI_API_KEY}"
SECRET_VERSION="${SECRET_VERSION:-1}"
ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-false}"
MAX_INSTANCES="${MAX_INSTANCES:-3}"
CHAT_TIMEOUT_SECONDS="${CHAT_TIMEOUT_SECONDS:-240}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-300}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_SA="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="${BUILD_SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

if [[ "$ALLOW_UNAUTHENTICATED" != true && "$ALLOW_UNAUTHENTICATED" != false ]]; then
    echo 'ALLOW_UNAUTHENTICATED는 true 또는 false여야 합니다.' >&2
    exit 1
fi
for value in "$CHAT_TIMEOUT_SECONDS" "$REQUEST_TIMEOUT_SECONDS" "$MAX_INSTANCES"; do
    if [[ ! "$value" =~ ^[1-9][0-9]{0,3}$ ]]; then
        echo '시간 제한과 MAX_INSTANCES는 1~9999 범위의 정수여야 합니다.' >&2
        exit 1
    fi
done
if (( CHAT_TIMEOUT_SECONDS >= REQUEST_TIMEOUT_SECONDS || REQUEST_TIMEOUT_SECONDS > 3600 )); then
    echo 'CHAT_TIMEOUT_SECONDS < REQUEST_TIMEOUT_SECONDS <= 3600이어야 합니다.' >&2
    exit 1
fi
if [[ "$RUNTIME_SA" == "$BUILD_SA" ]]; then
    echo '런타임 서비스 계정과 빌드 서비스 계정은 서로 다르게 지정해주세요.' >&2
    exit 1
fi
if [[ "$DRY_RUN" == false ]] && ! command -v gcloud >/dev/null 2>&1; then
    echo 'Google Cloud CLI(gcloud)를 설치하고 gcloud auth login을 먼저 실행해주세요.' >&2
    exit 1
fi

run() {
    if [[ "$DRY_RUN" == true ]]; then
        printf '%q ' "$@"
        printf '\n'
    else
        "$@"
    fi
}

ensure_service_account() {
    local account_id="$1" account_email="$2" existing=""
    if [[ "$DRY_RUN" == false ]]; then
        existing="$(gcloud iam service-accounts list --project="$PROJECT_ID" \
            --filter="email=${account_email}" --format='value(email)')"
    fi
    if [[ -z "$existing" ]]; then
        run gcloud iam service-accounts create "$account_id" --project="$PROJECT_ID" --quiet
    fi
}

run gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com \
    --project="$PROJECT_ID" --quiet

# 키 값은 읽거나 출력하지 않고 시크릿 버전의 메타데이터만 확인한다.
run gcloud secrets versions describe "$SECRET_VERSION" --secret="$SECRET_NAME" \
    --project="$PROJECT_ID" --format='value(state)'

ensure_service_account "$SERVICE_ACCOUNT_ID" "$RUNTIME_SA"
ensure_service_account "$BUILD_SERVICE_ACCOUNT_ID" "$BUILD_SA"
run gcloud secrets add-iam-policy-binding "$SECRET_NAME" --project="$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor --quiet
run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${BUILD_SA}" --role=roles/run.builder --condition=None --quiet

AUTH_FLAG=--no-allow-unauthenticated
if [[ "$ALLOW_UNAUTHENTICATED" == true ]]; then AUTH_FLAG=--allow-unauthenticated; fi

run gcloud run deploy "$SERVICE_NAME" \
    --project="$PROJECT_ID" --region="$REGION" --source="$SOURCE_DIR" \
    --service-account="$RUNTIME_SA" \
    --build-service-account="projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA}" \
    --update-secrets="GEMINI_API_KEY=${SECRET_NAME}:${SECRET_VERSION}" \
    --update-env-vars="CHAT_TIMEOUT_SECONDS=${CHAT_TIMEOUT_SECONDS}" \
    --port=8080 --cpu=1 --memory=512Mi --concurrency=20 \
    --min-instances=0 --max-instances="$MAX_INSTANCES" \
    --timeout="${REQUEST_TIMEOUT_SECONDS}s" \
    --startup-probe='httpGet.path=/healthz,httpGet.port=8080' \
    --invoker-iam-check "$AUTH_FLAG" --quiet

run gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" \
    --region="$REGION" --format='value(status.url)'
