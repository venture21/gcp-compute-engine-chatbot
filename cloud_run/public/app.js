/**
 * Google Gemini Web Chatbot Frontend Logic
 * Supports Gemini 3.8 Flash (Default) & Gemini 3.7 Flash selection,
 * Multi-turn memory, Voice recognition (Web Speech API), Korean IME safety,
 * and elegant markdown rendering.
 */

(() => {
  // State variables
  let activeModel = 'gemini-3.8-flash';
  let previousInteractionId = null;
  let isGenerating = false;
  let speechRecognizer = null;
  let isListening = false;

  const MODEL_META = {
    'gemini-3.8-flash': {
      label: '사고 모델',
      badge: '3.8 Flash'
    },
    'gemini-3.7-flash': {
      label: '사고 모델 (3.7)',
      badge: '3.7 Flash'
    },
    'antigravity-preview-05-2026': {
      label: '연구 에이전트',
      badge: 'Agent'
    }
  };

  // DOM Elements
  const geminiApp = document.getElementById('geminiApp');
  const landingView = document.getElementById('landingView');
  const inputAnchor = document.getElementById('inputAnchor');
  const chatView = document.getElementById('chatView');
  const chatMessages = document.getElementById('chatMessages');
  const inputSection = document.getElementById('inputSection');
  const promptInput = document.getElementById('promptInput');
  const sendBtn = document.getElementById('sendBtn');
  const attachBtn = document.getElementById('attachBtn');
  const micBtn = document.getElementById('micBtn');
  const newChatBtn = document.getElementById('newChatBtn');
  const brandBtn = document.getElementById('brandBtn');
  const apiStatusChip = document.getElementById('apiStatusChip');
  const statusText = document.getElementById('statusText');
  const headerModelBadge = document.getElementById('headerModelBadge');

  // Model Selector Elements
  const modelSelectBtn = document.getElementById('modelSelectBtn');
  const modelDropdownMenu = document.getElementById('modelDropdownMenu');
  const activeModelLabel = document.getElementById('activeModelLabel');
  const optionModel38 = document.getElementById('optionModel38');
  const optionModel37 = document.getElementById('optionModel37');
  const optionModelAgent = document.getElementById('optionModelAgent');

  // Voice Toast
  const voiceToast = document.getElementById('voiceToast');
  const voiceStopBtn = document.getElementById('voiceStopBtn');

  // Suggestion Chips
  const suggestionChips = document.querySelectorAll('.suggestion-chip');

  // --------------------------------------------------------------------------
  // 1. Initial Status Check
  // --------------------------------------------------------------------------
  async function checkServerStatus() {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        apiStatusChip.classList.remove('offline');
        apiStatusChip.classList.add('online');
        statusText.textContent = data.hasApiKey ? 'API 연결됨' : 'API 키 필요';
      } else {
        throw new Error('Status check failed');
      }
    } catch (e) {
      apiStatusChip.classList.remove('online');
      apiStatusChip.classList.add('offline');
      statusText.textContent = '서버 오프라인';
    }
  }

  // --------------------------------------------------------------------------
  // 2. Model Selector Handling
  // --------------------------------------------------------------------------
  function toggleModelDropdown(e) {
    e.stopPropagation();
    const isExpanded = modelDropdownMenu.classList.toggle('show');
    modelSelectBtn.setAttribute('aria-expanded', isExpanded);
  }

  function closeModelDropdown() {
    if (modelDropdownMenu.classList.contains('show')) {
      modelDropdownMenu.classList.remove('show');
      modelSelectBtn.setAttribute('aria-expanded', 'false');
    }
  }

  function selectModel(modelId) {
    if (activeModel === modelId) {
      closeModelDropdown();
      return;
    }

    activeModel = modelId;
    const meta = MODEL_META[modelId] || { label: '사고 모델', badge: 'Flash' };

    activeModelLabel.textContent = meta.label;
    headerModelBadge.textContent = meta.badge;

    optionModel38.classList.toggle('active', modelId === 'gemini-3.8-flash');
    optionModel37.classList.toggle('active', modelId === 'gemini-3.7-flash');
    if (optionModelAgent) {
      optionModelAgent.classList.toggle('active', modelId === 'antigravity-preview-05-2026');
    }

    closeModelDropdown();
  }

  // --------------------------------------------------------------------------
  // 3. Textarea Auto-resize & Send State
  // --------------------------------------------------------------------------
  function updateInputState() {
    const val = promptInput.value.trim();
    if (val.length > 0 && !isGenerating) {
      sendBtn.classList.add('active');
      sendBtn.removeAttribute('disabled');
    } else {
      sendBtn.classList.remove('active');
      sendBtn.setAttribute('disabled', 'true');
    }

    // Auto-height
    promptInput.style.height = 'auto';
    promptInput.style.height = Math.min(promptInput.scrollHeight, 140) + 'px';
  }

  // --------------------------------------------------------------------------
  // 4. Safe Markdown Rendering
  // --------------------------------------------------------------------------
  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function parseMarkdown(mdText) {
    if (!mdText) return '';

    // 1. Code blocks (```lang ... ```)
    const codeBlocks = [];
    let text = mdText.replace(/```([a-zA-Z0-9_\-+]*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const id = `__CODE_BLOCK_${codeBlocks.length}__`;
      const language = lang.trim() || 'code';
      const escapedCode = escapeHtml(code.trim());
      const blockHtml = `
        <div class="code-block-wrapper">
          <div class="code-block-header">
            <span>${language}</span>
            <button class="code-copy-btn" onclick="copyCode(this)">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
              <span>복사</span>
            </button>
          </div>
          <pre><code>${escapedCode}</code></pre>
        </div>
      `;
      codeBlocks.push(blockHtml);
      return id;
    });

    // 2. Escape other HTML
    text = escapeHtml(text);

    // 3. Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 4. Headings
    text = text.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    text = text.replace(/^# (.*$)/gim, '<h1>$1</h1>');

    // 5. Bold & Italic
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // 6. Bullet lists
    text = text.replace(/^\s*[\-\*]\s+(.*)$/gim, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>)/gim, '<ul>$1</ul>');
    // Fix nested adjacent ul tags
    text = text.replace(/<\/ul>\s*<ul>/g, '');

    // 7. Numbered lists
    text = text.replace(/^\s*(\d+)\.\s+(.*)$/gim, '<li>$2</li>');

    // 8. Paragraphs / Linebreaks
    const lines = text.split('\n\n');
    text = lines
      .map((seg) => {
        seg = seg.trim();
        if (!seg) return '';
        if (seg.startsWith('<h') || seg.startsWith('<ul>') || seg.startsWith('__CODE_BLOCK_')) {
          return seg;
        }
        return `<p>${seg.replace(/\n/g, '<br>')}</p>`;
      })
      .join('');

    // Restore Code blocks
    codeBlocks.forEach((blockHtml, i) => {
      text = text.replace(`__CODE_BLOCK_${i}__`, blockHtml);
      text = text.replace(`<p>__CODE_BLOCK_${i}__</p>`, blockHtml);
    });

    return text;
  }

  // --------------------------------------------------------------------------
  // 5. Chat Interaction Logic
  // --------------------------------------------------------------------------
  function enterChatMode() {
    if (!geminiApp.classList.contains('in-chat')) {
      geminiApp.classList.add('in-chat');
      landingView.classList.add('hidden');
      landingView.style.display = 'none';
      chatView.classList.remove('hidden');
      chatView.style.display = 'flex';
      geminiApp.appendChild(inputSection);
    }
  }

  function resetChat() {
    previousInteractionId = null;
    isGenerating = false;
    chatMessages.innerHTML = '';
    geminiApp.classList.remove('in-chat');
    chatView.classList.add('hidden');
    chatView.style.display = 'none';
    landingView.classList.remove('hidden');
    landingView.classList.remove('fade-out');
    landingView.style.display = 'flex';
    if (inputAnchor) {
      inputAnchor.appendChild(inputSection);
    }
    promptInput.value = '';
    updateInputState();
    promptInput.focus();
  }

  function scrollToBottom(smooth = true) {
    requestAnimationFrame(() => {
      chatView.scrollTo({
        top: chatView.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto'
      });
    });
  }

  function appendUserMessage(text) {
    const row = document.createElement('div');
    row.className = 'message-row user';

    const bubble = document.createElement('div');
    bubble.className = 'user-bubble';
    bubble.textContent = text;

    row.appendChild(bubble);
    chatMessages.appendChild(row);
    scrollToBottom(false);
    return row;
  }

  function appendAssistantPlaceholder(modelName) {
    const row = document.createElement('div');
    row.className = 'message-row assistant';

    const avatar = document.createElement('div');
    avatar.className = 'assistant-avatar';
    avatar.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M12 2C12 7.52285 7.52285 12 2 12C7.52285 12 12 16.4771 12 22C12 16.4771 16.4771 12 22 12C16.4771 12 12 7.52285 12 2Z" fill="url(#geminiGradInner)"/>
        <defs>
          <linearGradient id="geminiGradInner" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
            <stop stop-color="#1A73E8"/>
            <stop offset="0.5" stop-color="#8AB4F8"/>
            <stop offset="1" stop-color="#C58AF9"/>
          </linearGradient>
        </defs>
      </svg>
    `;

    const contentWrapper = document.createElement('div');
    contentWrapper.className = 'assistant-content-wrapper';

    // Model pill tag
    const meta = document.createElement('div');
    meta.className = 'assistant-meta';
    meta.innerHTML = `<span class="assistant-model-pill">${modelName}</span>`;

    // Thinking Box (사고 모델)
    const thoughtCard = document.createElement('div');
    thoughtCard.className = 'thought-card';
    thoughtCard.innerHTML = `
      <div class="thought-header">
        <div class="thought-title-group">
          <span class="thought-sparkle">✦</span>
          <span class="thought-title-text">사고 과정 추론 중...</span>
        </div>
        <button class="thought-toggle-btn" type="button">숨기기</button>
      </div>
      <div class="thought-body">
        사용자의 질문을 다각도로 분석하고 최적의 답변 구조를 구성하고 있습니다.
      </div>
    `;

    // Toggle thought
    const toggleBtn = thoughtCard.querySelector('.thought-toggle-btn');
    const thoughtBody = thoughtCard.querySelector('.thought-body');
    toggleBtn.addEventListener('click', () => {
      const isHidden = thoughtBody.classList.toggle('hidden');
      toggleBtn.textContent = isHidden ? '펼치기' : '숨기기';
    });

    // Content container
    const body = document.createElement('div');
    body.className = 'assistant-body';
    body.innerHTML = `
      <div class="loading-dots">
        <span class="loading-dot"></span>
        <span class="loading-dot"></span>
        <span class="loading-dot"></span>
      </div>
    `;

    contentWrapper.appendChild(meta);
    contentWrapper.appendChild(thoughtCard);
    contentWrapper.appendChild(body);

    row.appendChild(avatar);
    row.appendChild(contentWrapper);
    chatMessages.appendChild(row);
    scrollToBottom();

    return { row, thoughtCard, body };
  }

  async function handleSend() {
    const text = promptInput.value.trim();
    if (!text || isGenerating) return;

    isGenerating = true;
    updateInputState();
    promptInput.value = '';
    promptInput.style.height = 'auto';

    enterChatMode();
    appendUserMessage(text);

    let modelDisplayName = 'Gemini 3.8 Flash';
    if (activeModel === 'gemini-3.7-flash') modelDisplayName = 'Gemini 3.7 Flash';
    if (activeModel === 'antigravity-preview-05-2026') modelDisplayName = 'Antigravity Agent';
    const { thoughtCard, body } = appendAssistantPlaceholder(modelDisplayName);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input: text,
          model: activeModel,
          previousInteractionId: previousInteractionId
        })
      });

      const data = await response.json();

      if (!response.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : null;
        throw new Error(detail || data.error || '답변을 생성하지 못했습니다. 질문은 10,000자 이내로 입력해주세요.');
      }

      // Update multi-turn interaction ID
      if (data.interactionId) {
        previousInteractionId = data.interactionId;
      }

      // Update thought card
      const thoughtTitle = thoughtCard.querySelector('.thought-title-text');
      thoughtTitle.textContent = '사고 과정 완료';
      const thoughtBody = thoughtCard.querySelector('.thought-body');

      let toolsText = '';
      if (data.toolsUsed) {
        const used = [];
        if (data.toolsUsed.googleSearch) used.push('🔍 구글 실시간 검색');
        if (data.toolsUsed.codeExecution) used.push('💻 코드 실행 엔진');
        if (used.length > 0) {
          toolsText = `<br><span style="display:inline-block; margin-top:4px; font-size:0.78rem; color:#1a73e8;">연동 도구: ${used.join(', ')}</span>`;
        }
      }

      thoughtBody.innerHTML = `${modelDisplayName} 모델이 맥락과 최신 정보를 분석하고 답변 생성을 마쳤습니다.${toolsText}`;

      // Render answer
      body.innerHTML = parseMarkdown(data.reply);

      // Add copy button action
      const actionRow = document.createElement('div');
      actionRow.className = 'assistant-actions';
      actionRow.innerHTML = `
        <button class="action-icon-btn copy-reply-btn" title="답변 복사">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          <span>복사</span>
        </button>
      `;

      actionRow.querySelector('.copy-reply-btn').addEventListener('click', () => {
        navigator.clipboard.writeText(data.reply).then(() => {
          const span = actionRow.querySelector('span');
          span.textContent = '복사됨!';
          setTimeout(() => (span.textContent = '복사'), 2000);
        });
      });

      body.parentElement.appendChild(actionRow);
    } catch (err) {
      body.innerHTML = `
        <div style="color: #d93025; font-size: 0.95rem; padding: 6px 0;">
          ⚠️ ${escapeHtml(err.message)}
        </div>
      `;
      thoughtCard.style.display = 'none';
    } finally {
      isGenerating = false;
      updateInputState();
      scrollToBottom();
      promptInput.focus();
    }
  }

  // --------------------------------------------------------------------------
  // 6. Global Copy Helper for Code Blocks
  // --------------------------------------------------------------------------
  window.copyCode = function (btn) {
    const pre = btn.closest('.code-block-wrapper').querySelector('pre code');
    if (!pre) return;
    navigator.clipboard.writeText(pre.innerText).then(() => {
      const span = btn.querySelector('span');
      if (span) {
        const orig = span.textContent;
        span.textContent = '복사됨!';
        setTimeout(() => (span.textContent = orig), 2000);
      }
    });
  };

  // --------------------------------------------------------------------------
  // 7. Web Speech API (Microphone Voice Input)
  // --------------------------------------------------------------------------
  function initSpeechRecognition() {
    const SpeechClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechClass) {
      micBtn.title = '이 브라우저는 음성 인식을 지원하지 않습니다.';
      return;
    }

    speechRecognizer = new SpeechClass();
    speechRecognizer.lang = 'ko-KR';
    speechRecognizer.continuous = false;
    speechRecognizer.interimResults = true;

    speechRecognizer.onstart = () => {
      isListening = true;
      micBtn.classList.add('listening');
      voiceToast.classList.remove('hidden');
    };

    speechRecognizer.onresult = (event) => {
      let transcript = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      promptInput.value = transcript;
      updateInputState();
    };

    speechRecognizer.onerror = (event) => {
      console.warn('Speech recognition error:', event.error);
      stopSpeechRecognition();
    };

    speechRecognizer.onend = () => {
      stopSpeechRecognition();
    };
  }

  function toggleSpeechRecognition() {
    if (!speechRecognizer) {
      alert('현재 브라우저 환경에서는 Web Speech API 음성 인식을 지원하지 않습니다. Chrome 브라우저 사용을 권장합니다.');
      return;
    }

    if (isListening) {
      speechRecognizer.stop();
    } else {
      try {
        speechRecognizer.start();
      } catch (e) {
        console.warn('Speech start error:', e);
      }
    }
  }

  function stopSpeechRecognition() {
    isListening = false;
    micBtn.classList.remove('listening');
    voiceToast.classList.add('hidden');
  }

  // --------------------------------------------------------------------------
  // 8. Event Listeners Setup
  // --------------------------------------------------------------------------
  // Input Typing & Korean IME Enter Handler
  promptInput.addEventListener('input', updateInputState);

  promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      // 한글 IME 조합 중(e.isComposing 또는 keyCode 229) 엔터 중복 발송 방지
      if (e.isComposing || e.keyCode === 229) {
        return;
      }
      e.preventDefault();
      handleSend();
    }
  });

  // Send Button Click
  sendBtn.addEventListener('click', handleSend);

  // Attachment Button
  attachBtn.addEventListener('click', () => {
    promptInput.focus();
    alert('이미지 및 문서 첨부 기능은 향후 업데이트될 예정입니다. 질문 텍스트를 바로 입력해 보세요!');
  });

  // Model Dropdown
  modelSelectBtn.addEventListener('click', toggleModelDropdown);
  optionModel38.addEventListener('click', () => selectModel('gemini-3.8-flash'));
  optionModel37.addEventListener('click', () => selectModel('gemini-3.7-flash'));
  if (optionModelAgent) {
    optionModelAgent.addEventListener('click', () => selectModel('antigravity-preview-05-2026'));
  }

  document.addEventListener('click', (e) => {
    if (!modelSelectBtn.contains(e.target) && !modelDropdownMenu.contains(e.target)) {
      closeModelDropdown();
    }
  });

  // Mic Button
  micBtn.addEventListener('click', toggleSpeechRecognition);
  voiceStopBtn.addEventListener('click', () => {
    if (speechRecognizer) speechRecognizer.stop();
  });

  // New Chat & Brand Click
  newChatBtn.addEventListener('click', resetChat);
  brandBtn.addEventListener('click', resetChat);

  // Suggestion Chips Click
  suggestionChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      const prompt = chip.getAttribute('data-prompt');
      if (prompt) {
        promptInput.value = prompt;
        updateInputState();
        handleSend();
      }
    });
  });

  // --------------------------------------------------------------------------
  // 9. Initial Load
  // --------------------------------------------------------------------------
  if (inputAnchor && inputSection) {
    inputAnchor.appendChild(inputSection);
  }
  checkServerStatus();
  initSpeechRecognition();
  updateInputState();
  promptInput.focus();
})();
