import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// .env 파일 수동 파싱 (외부 의존성 dotenv 없이 내장 기능 지원)
function loadEnvFile() {
  const envPath = path.join(__dirname, '.env');
  if (fs.existsSync(envPath)) {
    try {
      const content = fs.readFileSync(envPath, 'utf8');
      for (const line of content.split('\n')) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) continue;
        const eqIdx = trimmed.indexOf('=');
        if (eqIdx > 0) {
          const key = trimmed.slice(0, eqIdx).trim();
          const val = trimmed.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, '');
          if (!process.env[key]) {
            process.env[key] = val;
          }
        }
      }
    } catch (e) {
      console.warn('Failed to parse .env file:', e.message);
    }
  }
}
loadEnvFile();

const PORT = parseInt(process.env.PORT || '3000', 10);
const HOST = '127.0.0.1';
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || '';

const SUPPORTED_MODELS = [
  {
    id: 'gemini-3.8-flash',
    name: 'Gemini 3.8 Flash',
    label: '사고 모델 (3.8 Flash)',
    description: '최신 플래그십 사고 모델 (기본 / 최고 수준 지능 및 응답)',
    isDefault: true
  },
  {
    id: 'gemini-3.7-flash',
    name: 'Gemini 3.7 Flash',
    label: '사고 모델 (3.7 Flash)',
    description: '고속 사고 모델 (균형 잡힌 추론 및 민첩한 응답 속도)',
    isDefault: false
  }
];

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

const PUBLIC_DIR = path.join(__dirname, 'public');

// JSON 파싱 헬퍼 (UTF-8 버퍼 수집 및 한글 멀티바이트 보존, 용량 제한 1MB)
function parseJsonBody(req, maxBytes = 1024 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let receivedBytes = 0;

    req.on('data', (chunk) => {
      receivedBytes += chunk.length;
      if (receivedBytes > maxBytes) {
        reject(new Error('PAYLOAD_TOO_LARGE'));
        return;
      }
      chunks.push(chunk);
    });

    req.on('end', () => {
      try {
        const raw = Buffer.concat(chunks).toString('utf8').trim();
        if (!raw) {
          resolve({});
          return;
        }
        const data = JSON.parse(raw);
        if (data === null || typeof data !== 'object' || Array.isArray(data)) {
          reject(new Error('INVALID_JSON_OBJECT'));
          return;
        }
        resolve(data);
      } catch (err) {
        reject(new Error('INVALID_JSON_SYNTAX'));
      }
    });

    req.on('error', (err) => reject(err));
  });
}

// JSON 응답 전송 헬퍼
function sendJson(res, statusCode, data) {
  const jsonStr = JSON.stringify(data);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(jsonStr, 'utf8'),
    'Cache-Control': 'no-store'
  });
  res.end(jsonStr);
}

// 정적 파일 서빙 헬퍼
function serveStaticFile(res, reqPath) {
  let targetFile = reqPath === '/' ? '/index.html' : reqPath;
  const safePath = path.normalize(path.join(PUBLIC_DIR, targetFile));

  // Directory Traversal 차단
  if (!safePath.startsWith(PUBLIC_DIR)) {
    sendJson(res, 403, { error: '접근이 거부되었습니다.' });
    return;
  }

  fs.stat(safePath, (err, stats) => {
    if (err || !stats.isFile()) {
      sendJson(res, 404, { error: '파일을 찾을 수 없습니다.' });
      return;
    }

    const ext = path.extname(safePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';

    res.writeHead(200, {
      'Content-Type': contentType,
      'Content-Length': stats.size,
      'Cache-Control': 'no-cache'
    });

    fs.createReadStream(safePath).pipe(res);
  });
}

// HTTP 서버 인스턴스 생성
const server = http.createServer(async (req, res) => {
  const parsedUrl = new URL(req.url, `http://${req.headers.host || '127.0.0.1'}`);
  const pathname = parsedUrl.pathname;

  // 1. 서버 상태 조회
  if (req.method === 'GET' && pathname === '/api/status') {
    return sendJson(res, 200, {
      status: 'ok',
      defaultModel: 'gemini-3.8-flash',
      models: SUPPORTED_MODELS,
      hasApiKey: Boolean(GEMINI_API_KEY && GEMINI_API_KEY.length > 5),
      timestamp: new Date().toISOString()
    });
  }

  // 2. 챗봇 대화 질의 API
  if (req.method === 'POST' && pathname === '/api/chat') {
    const contentType = req.headers['content-type'] || '';
    if (!contentType.includes('application/json')) {
      return sendJson(res, 415, { error: 'Content-Type은 application/json이어야 합니다.' });
    }

    let body;
    try {
      body = await parseJsonBody(req);
    } catch (err) {
      if (err.message === 'PAYLOAD_TOO_LARGE') {
        return sendJson(res, 413, { error: '요청 크기가 너무 큽니다 (최대 1MB 허용).' });
      }
      return sendJson(res, 400, { error: '요청 본문이 올바른 JSON 객체 형식이 아닙니다.' });
    }

    const input = typeof body.input === 'string' ? body.input.trim() : '';
    if (!input) {
      return sendJson(res, 400, { error: '질문 내용을 입력해주세요.' });
    }

    if (input.length > 8000) {
      return sendJson(res, 400, { error: '질문 내용은 최대 8,000자까지 입력 가능합니다.' });
    }

    // 모델 유효성 검사 (기본값 gemini-3.8-flash)
    let selectedModel = 'gemini-3.8-flash';
    if (body.model && SUPPORTED_MODELS.some((m) => m.id === body.model)) {
      selectedModel = body.model;
    }

    const previousInteractionId =
      typeof body.previousInteractionId === 'string' && body.previousInteractionId.trim()
        ? body.previousInteractionId.trim()
        : null;

    if (!GEMINI_API_KEY) {
      return sendJson(res, 500, {
        error: '서버에 GEMINI_API_KEY 환경변수가 설정되어 있지 않습니다.'
      });
    }

    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), 45000);

    try {
      const payload = {
        model: selectedModel,
        input: input
      };
      if (previousInteractionId) {
        payload.previous_interaction_id = previousInteractionId;
      }

      const apiResponse = await fetch('https://generativelanguage.googleapis.com/v1beta/interactions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-goog-api-key': GEMINI_API_KEY
        },
        body: JSON.stringify(payload),
        signal: abortController.signal
      });

      clearTimeout(timeoutId);

      if (!apiResponse.ok) {
        const errorText = await apiResponse.text().catch(() => '');
        console.error(`Gemini API Error [${apiResponse.status}]:`, errorText.slice(0, 300));

        let userMsg = 'Gemini API 호출 중 오류가 발생했습니다.';
        if (apiResponse.status === 429) {
          userMsg = 'API 호출 한도(Quota)를 초과했습니다. 잠시 후 다시 시도해주세요.';
        } else if (apiResponse.status === 401 || apiResponse.status === 403) {
          userMsg = '유효하지 않은 Gemini API 키입니다. 환경변수를 확인해주세요.';
        } else if (apiResponse.status === 404) {
          userMsg = `선택한 모델(${selectedModel})을 찾을 수 없습니다.`;
        }

        return sendJson(res, apiResponse.status >= 500 ? 502 : apiResponse.status, {
          error: userMsg
        });
      }

      const data = await apiResponse.json();
      const steps = Array.isArray(data.steps) ? data.steps : [];

      // 텍스트 추출
      const modelOutputs = steps.filter((s) => s.type === 'model_output');
      const textParts = [];

      for (const output of modelOutputs) {
        if (Array.isArray(output.content)) {
          for (const item of output.content) {
            if (item && item.type === 'text' && typeof item.text === 'string') {
              textParts.push(item.text);
            }
          }
        }
      }

      const reply = textParts.join('\n').trim();
      const hasThought = steps.some((s) => s.type === 'thought');

      if (!reply) {
        return sendJson(res, 502, {
          error: 'Gemini 모델로부터 응답 텍스트를 받지 못했습니다. 다시 시도해주세요.'
        });
      }

      return sendJson(res, 200, {
        reply: reply,
        interactionId: data.id || null,
        model: selectedModel,
        hasThought: hasThought,
        timestamp: new Date().toISOString()
      });
    } catch (fetchErr) {
      clearTimeout(timeoutId);
      if (fetchErr.name === 'AbortError') {
        return sendJson(res, 504, { error: 'Gemini 응답 시간 초과 (45초)가 발생했습니다.' });
      }
      console.error('Fetch exception:', fetchErr.message);
      return sendJson(res, 500, { error: '네트워크 연결 또는 서버 내부 오류가 발생했습니다.' });
    }
  }

  // 3. 정적 웹 파일 서빙
  if (req.method === 'GET' || req.method === 'HEAD') {
    return serveStaticFile(res, pathname);
  }

  // 그 외 지원하지 않는 HTTP 메서드
  sendJson(res, 405, { error: '지원하지 않는 HTTP 메소드입니다.' });
});

// 서버 바인딩 및 시작
server.listen(PORT, HOST, () => {
  console.log(`=========================================`);
  console.log(` Gemini Chatbot Server Started!`);
  console.log(` URL: http://${HOST}:${PORT}`);
  console.log(` Default Model: gemini-3.8-flash`);
  console.log(` Alternate Model: gemini-3.7-flash`);
  console.log(` API Key Loaded: ${Boolean(GEMINI_API_KEY)}`);
  console.log(`=========================================`);
});
