# GCP Gemini 웹 챗봇

배포 환경별로 독립적으로 실행할 수 있는 한국어 Gemini 챗봇입니다.

| 디렉터리 | 실행 환경 | 구성 및 가이드 |
| --- | --- | --- |
| [`compute_engine/`](compute_engine/README.md) | Compute Engine VM | 기존 Python/Node.js 서버, 웹 UI, VM 프로비저닝, Nginx/HTTPS 설정, 실습 노트북 |
| [`cloud_run/`](cloud_run/README.md) | Cloud Run 컨테이너 | 비동기 Python 서버, 웹 UI, Dockerfile, Secret Manager 연동 배포 스크립트 |
| [`cloud_run2/`](cloud_run2/README.md) | Cloud Run 컨테이너 · ADC | 서비스 계정 ADC로 Gemini Enterprise Agent Platform 호출, API 키 없이 배포 |

```text
gcp-compute-engine-chatbot/
├── compute_engine/
│   ├── deploy/
│   ├── public/
│   ├── .env.example
│   ├── compute_engine_example.ipynb
│   ├── package.json
│   ├── requirements.txt
│   ├── server.mjs
│   ├── server.py
│   └── README.md
├── cloud_run/
│   ├── deploy/deploy.sh
│   ├── public/
│   ├── tests/
│   ├── .dockerignore
│   ├── .gcloudignore
│   ├── .env.example
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── server.py
│   └── README.md
├── .gitignore
└── README.md
```

## 로컬 실행

저장소 루트에서 원하는 환경의 폴더로 이동한 뒤 실행합니다. Python 3.11 이상을 사용합니다.

```bash
cd compute_engine  # Cloud Run 버전은 cd cloud_run
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# .env의 GEMINI_API_KEY를 실제 키로 수정
python server.py
```

- Compute Engine 버전: [http://localhost:3000](http://localhost:3000)
- Cloud Run 버전: [http://localhost:8080](http://localhost:8080)

기존 루트의 실행 파일과 배포 스크립트는 `compute_engine/`으로 이동했습니다.
기존 `python3 server.py`, `npm start`, `python3 deploy/provision_and_deploy.py` 명령은
이제 `compute_engine/` 안에서 실행합니다. 환경변수 파일도 해당 폴더의 `.env`를 사용합니다.

`cloud_run2/`는 `cloud_run/`과 같은 파일 구조를 가지며 ADC 인증을 사용합니다.
각 폴더는 상대 폴더를 참조하지 않으므로 단독으로 복사하거나 배포할 수 있습니다.
UI를 공통으로 수정하려면 각 `public/`에 반영해야 합니다.

## 배포

- VM 배포 및 HTTPS 설정: [Compute Engine 가이드](compute_engine/README.md)
- 컨테이너 실행 및 소스 배포: [Cloud Run 가이드](cloud_run/README.md)
- API 키 없이 서비스 계정으로 배포: [Cloud Run ADC 가이드](cloud_run2/README.md)
- 실제 IDE 캡처와 ADC 배포 절차: [Cloud Run2 ADC 실습 문서](Antigravity_IDE_Cloud_Run2_ADC_배포_실습가이드.html)
