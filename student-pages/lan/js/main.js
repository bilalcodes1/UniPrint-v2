'use strict';

const _host   = location.hostname === 'localhost' || location.hostname === '127.0.0.1'
  ? 'http://localhost:5001'
  : `http://${location.hostname}:5001`;
const API_BASE = `${_host}/api`;
const WS_URL   = _host;
const MAX_FILES = 5;
const MAX_SIZE  = 20 * 1024 * 1024; // 20 MB
const ALLOWED   = ['pdf','doc','docx','ppt','pptx','xls','xlsx','jpg','jpeg','png'];

// ── State ────────────────────────────────────────────────────────────────────
const state = {
  nationalId:   '',
  nationalHash: '',
  studentName:  '',
  files: [],          // { file, copies, color, sides }
  requestId:    '',
  verifyCode:   '',
  totalPages:   0,
  filesCount:   0,
  serverOnline: true,
  socket:       null,
  trackingInterval: null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const screen = $(id);
  screen.classList.add('active');
  requestAnimationFrame(() => {
    const first = screen.querySelector('button:not([disabled]), input:not([disabled]), textarea:not([disabled])');
    first?.focus({ preventScroll: true });
  });
  window.scrollTo({ top: 0 });
}

const TOAST_ICONS = { success: '✅', error: '✕', info: 'ℹ️', default: '' };
function showToast(msg, type = 'default', duration = 3000) {
  const c = $('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const icon = TOAST_ICONS[type];
  t.innerHTML = icon ? `<span>${icon}</span> <span>${msg}</span>` : msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

function formatBytes(b) {
  if (b < 1024)       return b + ' B';
  if (b < 1024*1024)  return (b/1024).toFixed(1) + ' KB';
  return (b/1024/1024).toFixed(1) + ' MB';
}

function fileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const map = { pdf:'📄', doc:'📝', docx:'📝', ppt:'📊', pptx:'📊', xls:'📈', xlsx:'📈', jpg:'🖼️', jpeg:'🖼️', png:'🖼️' };
  return map[ext] || '📎';
}

function sha256(str) {
  return crypto.subtle.digest('SHA-256', new TextEncoder().encode(str))
    .then(b => Array.from(new Uint8Array(b)).map(x => x.toString(16).padStart(2,'0')).join(''));
}

function launchConfetti() {
  const colors = ['#2D6BE4','#34C759','#FF9500','#FF3B30','#5AC8FA'];
  for (let i = 0; i < 40; i++) {
    const el = document.createElement('div');
    const size = 4 + Math.random() * 6;
    el.style.cssText = `position:fixed;top:0;left:${Math.random()*100}vw;
      width:${size}px;height:${size*1.5}px;border-radius:2px;pointer-events:none;z-index:9999;
      background:${colors[Math.floor(Math.random()*colors.length)]};
      animation:confetti-fall ${0.8+Math.random()*0.8}s ease-out ${Math.random()*0.5}s both;`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2500);
  }
}

// ── SCREEN 1 — Login / OCR ────────────────────────────────────────────────────
let ocrStream = null;
let ocrWorker = null;
let ocrRunning = false;

$('btn-open-camera').addEventListener('click', startCamera);
$('btn-close-camera').addEventListener('click', stopCamera);
$('btn-manual-submit').addEventListener('click', handleManualSubmit);
$('btn-back-to-login').addEventListener('click', () => showScreen('screen-login'));
$('manual-id').addEventListener('input', () => {
  $('manual-id').value = $('manual-id').value.replace(/\D/g, '');
});

async function startCamera() {
  try {
    ocrStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
    });
    $('video').srcObject = ocrStream;
    $('camera-idle').classList.add('hidden');
    $('camera-wrap').classList.remove('hidden');
    startOCRScan();
  } catch (e) {
    showToast('تعذّر فتح الكاميرا: ' + e.message, 'error');
  }
}

function stopCamera() {
  ocrRunning = false;
  if (ocrStream) { ocrStream.getTracks().forEach(t => t.stop()); ocrStream = null; }
  $('camera-wrap').classList.add('hidden');
  $('camera-idle').classList.remove('hidden');
  $('ocr-progress').classList.add('hidden');
  $('scan-frame').classList.remove('active');
}

async function startOCRScan() {
  ocrRunning = true;
  $('ocr-progress').classList.remove('hidden');

  if (!ocrWorker) {
    try {
      ocrWorker = await Tesseract.createWorker('eng+ara');
    } catch (e) {
      showToast('تعذّر تهيئة OCR', 'error');
      return;
    }
  }

  const canvas = $('scan-canvas');
  const video  = $('video');
  const ctx    = canvas.getContext('2d');

  async function scanFrame() {
    if (!ocrRunning) return;

    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0);

    setProgress(30);
    try {
      const { data } = await ocrWorker.recognize(canvas);
      setProgress(80);
      const digits = data.text.replace(/\D/g, '');
      const match  = digits.match(/\d{12}/);
      if (match) {
        setProgress(100);
        $('scan-frame').classList.add('active');
        $('scan-hint').textContent = '✅ تم التعرف على الرقم!';
        ocrRunning = false;
        if (navigator.vibrate) navigator.vibrate([50, 30, 80]);
        setTimeout(() => goToConfirmId(match[0], ''), 600);
        return;
      }
    } catch (_) {}

    setProgress(0);
    if (ocrRunning) setTimeout(scanFrame, 800);
  }

  function setProgress(pct) {
    $('ocr-progress-bar').style.width = pct + '%';
  }

  await scanFrame();
}

function handleManualSubmit() {
  const id   = $('manual-id').value.trim();
  const name = $('manual-name').value.trim();
  if (id.length !== 12) {
    $('manual-id-error').classList.remove('hidden');
    $('manual-id').focus();
    return;
  }
  $('manual-id-error').classList.add('hidden');
  goToConfirmId(id, name);
}

async function goToConfirmId(nationalId, name) {
  stopCamera();
  state.nationalId   = nationalId;
  state.studentName  = name;
  state.nationalHash = await sha256(nationalId);

  $('identity-name').textContent = name || '(لم يُدخَل اسم)';
  $('identity-id').textContent   = '●●●●●●●● ' + nationalId.slice(-4);

  showScreen('screen-confirm-id');
}

// ── SCREEN 2 — Confirm identity ───────────────────────────────────────────────
$('btn-edit-id').addEventListener('click', () => {
  $('manual-id').value = state.nationalId;
  showScreen('screen-login');
});

$('btn-confirm-id').addEventListener('click', () => {
  $('upload-student-badge').textContent = state.studentName || 'طالب';
  renderFileList();
  showScreen('screen-upload');
});

// ── SCREEN 3 — Upload ─────────────────────────────────────────────────────────
const dropZone  = $('drop-zone');
const fileInput = $('file-input');

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') fileInput.click(); });
fileInput.addEventListener('change', () => addFiles([...fileInput.files]));

dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  addFiles([...e.dataTransfer.files]);
});

$('btn-back-to-id').addEventListener('click', () => showScreen('screen-confirm-id'));
$('btn-to-review').addEventListener('click', goToReview);

function addFiles(newFiles) {
  for (const f of newFiles) {
    if (state.files.length >= MAX_FILES) {
      $('upload-limit-warning').classList.remove('hidden');
      break;
    }
    const ext = f.name.split('.').pop().toLowerCase();
    if (!ALLOWED.includes(ext)) {
      showToast(`نوع غير مدعوم: .${ext} — استخدم PDF أو DOCX`, 'error', 4000);
      continue;
    }
    if (f.size > MAX_SIZE) {
      const mb = (f.size / 1024 / 1024).toFixed(1);
      showToast(`حجم الملف ${mb} MB يتجاوز 20 MB — ضؿطه عبر ilovepdf.com`, 'error', 5000);
      continue;
    }
    state.files.push({ file: f, copies: 1, color: false, sides: 'single', progress: 0, uploaded: false });
  }
  if (state.files.length >= MAX_FILES) $('upload-limit-warning').classList.remove('hidden');
  renderFileList();
  fileInput.value = '';
}

function renderFileList() {
  const list = $('file-list');
  list.innerHTML = '';

  state.files.forEach((item, i) => {
    const el = document.createElement('div');
    el.className = 'file-item animate-slide-up';
    const isUploading = item.progress > 0 && !item.uploaded;
    const progressBar = (item.progress > 0 || item.uploaded)
      ? `<div class="file-progress"><div class="file-progress-bar ${item.uploaded ? 'done' : ''}" style="width:${item.progress}%"></div></div>`
      : '';
    el.innerHTML = `
      <div class="file-icon">${fileIcon(item.file.name)}</div>
      <div class="file-info">
        <div class="file-name">${item.file.name}</div>
        <div class="file-size">${formatBytes(item.file.size)}</div>
        ${progressBar}
        ${!isUploading && !item.uploaded ? `
        <div class="file-options">
          <button class="file-opt ${item.color ? 'active' : ''}" data-i="${i}" data-opt="color">
            ${item.color ? '🎨 ملوّن' : '⬛ أبيض وأسود'}
          </button>
          <button class="file-opt ${item.sides==='double'?'active':''}" data-i="${i}" data-opt="sides">
            ${item.sides==='double'?'📄 وجهين':'📄 وجه'}
          </button>
          <button class="file-opt" data-i="${i}" data-opt="copies-down">−</button>
          <span style="font-size:13px;padding:2px 6px;">${item.copies} نسخة</span>
          <button class="file-opt" data-i="${i}" data-opt="copies-up">+</button>
        </div>` : ''}
      </div>
      ${item.uploaded
        ? '<span class="file-uploaded-check">✅</span>'
        : `<button class="file-remove" data-remove="${i}" aria-label="حذف الملف">✕</button>`
      }
    `;
    list.appendChild(el);
  });

  // Event delegation
  list.querySelectorAll('[data-opt]').forEach(btn => {
    btn.addEventListener('click', () => {
      const i   = +btn.dataset.i;
      const opt = btn.dataset.opt;
      if (opt === 'color')      state.files[i].color = !state.files[i].color;
      if (opt === 'sides')      state.files[i].sides = state.files[i].sides === 'double' ? 'single' : 'double';
      if (opt === 'copies-up')  state.files[i].copies = Math.min(10, state.files[i].copies + 1);
      if (opt === 'copies-down') state.files[i].copies = Math.max(1, state.files[i].copies - 1);
      renderFileList();
    });
  });

  list.querySelectorAll('[data-remove]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.files.splice(+btn.dataset.remove, 1);
      $('upload-limit-warning').classList.add('hidden');
      renderFileList();
    });
  });

  $('file-count').textContent = state.files.length;
  $('btn-to-review').disabled = state.files.length === 0;
}

// ── SCREEN 4 — Review + Submit ────────────────────────────────────────────────
$('btn-back-to-upload').addEventListener('click', () => showScreen('screen-upload'));

document.querySelectorAll('input[name="notif"]').forEach(r => {
  r.addEventListener('change', () => {
    const needsContact = r.value !== 'none';
    $('notif-contact-wrap').classList.toggle('hidden', !needsContact);
    if (needsContact) {
      const input = $('notif-contact');
      const hint  = $('notif-hint');
      if (r.value === 'telegram') {
        input.placeholder = 'أدخل Chat ID الخاص بك';
        input.inputMode   = 'numeric';
        hint.textContent  = '💡 أرسل /start للبوت @UniPrintBot ثم انسخ الرقم الذي يردّ به';
      } else {
        input.placeholder = 'example@gmail.com';
        input.inputMode   = 'email';
        hint.textContent  = '📧 ستصلك رسالة بريد إلكتروني فور جهوز طلبك';
      }
      input.focus();
    }
  });
});

function goToReview() {
  $('review-student').textContent = state.studentName || '(بدون اسم) — ' + '●'.repeat(8) + state.nationalId.slice(-4);

  const rf = $('review-files');
  rf.innerHTML = '';
  state.files.forEach(({ file, copies, color, sides }) => {
    const row = document.createElement('div');
    row.className = 'review-file-row';
    row.innerHTML = `
      <span>${fileIcon(file.name)} ${file.name}</span>
      <span>${copies} نسخة · ${color ? 'ملوّن' : 'أبيض وأسود'} · ${sides === 'double' ? 'وجهين' : 'وجه'}</span>
    `;
    rf.appendChild(row);
  });

  showScreen('screen-review');
}

$('btn-submit').addEventListener('click', submitRequest);

function submitRequest() {
  if (!state.serverOnline) {
    showToast('الخادم غير متاح — تحقّق من اتصال الجهاز بالشبكة', 'error', 4000);
    checkServerConnection();
    return;
  }
  const btn = $('btn-submit');
  btn.disabled = true;
  btn.dataset.uploading = '1';
  btn.innerHTML = '<span class="submit-spinner"></span> جارٍ الإرسال…';
  $('submit-error-wrap').classList.add('hidden');

  const notifMethod = document.querySelector('input[name="notif"]:checked')?.value || 'none';
  const contact     = $('notif-contact').value.trim();
  const notes       = $('order-notes').value.trim();

  const fd = new FormData();
  fd.append('national_id_hash', state.nationalHash);
  fd.append('student_name',     state.studentName);
  fd.append('notification_method', notifMethod);
  if (contact) fd.append('contact', contact);
  if (notes)   fd.append('notes', notes);

  state.files.forEach(({ file, copies, color, sides }) => {
    fd.append('files',    file);
    fd.append('copies[]', copies);
    fd.append('color[]',  color ? '1' : '0');
    fd.append('sides[]',  sides);
  });

  const totalSize = state.files.reduce((s, f) => s + f.file.size, 0);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', `${API_BASE}/submit`);

  const unloadGuard = e => { e.preventDefault(); e.returnValue = ''; };
  window.addEventListener('beforeunload', unloadGuard);

  xhr.upload.addEventListener('progress', e => {
    if (!e.lengthComputable) return;
    const pct = e.loaded / e.total;
    let loaded = e.loaded;
    state.files.forEach((item, i) => {
      const filePct = Math.min(1, loaded / item.file.size);
      loaded = Math.max(0, loaded - item.file.size);
      state.files[i].progress = Math.round(filePct * 100);
      state.files[i].uploaded = state.files[i].progress === 100;
    });
    renderFileList();
    btn.innerHTML = `<span class="submit-spinner"></span> جارٍ… ${Math.round(pct * 100)}%`;
  });

  const releaseGuard = () => window.removeEventListener('beforeunload', unloadGuard);

  xhr.onload = () => {
    releaseGuard();
    try {
      const data = JSON.parse(xhr.responseText);
      if (xhr.status >= 400) throw new Error(data.error || 'خطأ في الإرسال');
      state.requestId  = data.request_id;
      state.verifyCode = data.verification_code;
      state.totalPages = data.total_pages  || 0;
      state.filesCount = data.files_count  || state.files.length;
      showTrackingScreen(data);
      connectSocket(data.request_id);
      showToast('تم إرسال طلبك 🎉', 'success');
    } catch (e) {
      $('submit-error').textContent = e.message;
      $('submit-error-wrap').classList.remove('hidden');
      showToast(e.message, 'error');
    } finally {
      btn.disabled = false;
      delete btn.dataset.uploading;
      btn.textContent = '🚀 إرسال الطلب';
    }
  };

  xhr.onerror = () => {
    releaseGuard();
    $('submit-error').textContent = 'تعذّر الاتصال بالخادم';
    $('submit-error-wrap').classList.remove('hidden');
    showToast('تعذّر الاتصال بالخادم', 'error');
    btn.disabled = false;
    delete btn.dataset.uploading;
    btn.textContent = '🚀 إرسال الطلب';
  };

  xhr.send(fd);
}

// ── SCREEN 5 — Tracking ───────────────────────────────────────────────────────
function showTrackingScreen(data) {
  $('tracking-code').textContent     = data.verification_code;
  $('tracking-order-id').textContent = 'طلب #' + data.request_id.slice(0, 8).toUpperCase();

  const pos = data.queue_position;
  if (pos > 0) {
    $('wait-badge').classList.remove('hidden');
    $('queue-num').textContent = '#' + pos;
    const waitMins = Math.max(1, pos * 3);
    $('wait-time').textContent = waitMins < 60
      ? `~${waitMins} دقيقة`
      : `~${Math.round(waitMins/60)} ساعة`;
  }

  updateTimeline('received');
  showScreen('screen-tracking');
}

function updateTimeline(status) {
  const order = ['received', 'waiting', 'ready', 'delivered'];
  const idx   = order.indexOf(status);
  const msgs  = { received: 'استُلم طلبك…', waiting: 'جارٍ الطباعة…', ready: 'طلبك جاهز!', delivered: 'تم التسليم 🎉' };

  document.querySelectorAll('.tl-step').forEach((step, i) => {
    step.classList.remove('done', 'active');
    if (i < idx)  step.classList.add('done');
    if (i === idx) step.classList.add('active');
  });

  $('tracking-status-msg').textContent = msgs[status] || '';

  if (status === 'delivered') {
    launchConfetti();
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
    setTimeout(() => showCompletionScreen(), 1800);
  }
}

function showCompletionScreen() {
  const firstName = (state.studentName || '').split(/\s+/)[0] || 'طالبنا';
  $('completion-greeting').textContent = `مبروك ${firstName}! 🎊`;
  $('completion-sub').textContent = 'طلبك جاهز للاستلام من مكتب الطباعة';

  const totalCopies = state.files.reduce((s, f) => s + (f.copies || 1), 0);
  const pills = $('completion-stats');
  pills.innerHTML = '';
  const items = [
    { icon: '📁', label: `${state.filesCount || state.files.length} ملف` },
    { icon: '📄', label: `${state.totalPages} صفحة` },
    { icon: '🖨️', label: `${totalCopies} نسخة` },
  ];
  items.forEach(({ icon, label }) => {
    const p = document.createElement('span');
    p.className = 'stat-pill';
    p.innerHTML = `${icon} ${label}`;
    pills.appendChild(p);
  });

  showScreen('screen-completion');
}

function connectSocket(requestId) {
  if (state.socket) state.socket.disconnect();

  try {
    state.socket = io(WS_URL, { transports: ['websocket', 'polling'] });

    state.socket.on('status_update', (data) => {
      if (data.request_id === requestId) {
        updateTimeline(data.status);
        if (data.status === 'ready') {
          showToast('طلبك جاهز — تعال استلم من الكاونتر 🎉', 'success', 6000);
          if (navigator.vibrate) navigator.vibrate([100, 50, 200]);
        } else if (data.status === 'delivered') {
          showToast('طلبك جاهز للاستلام! 🎉', 'success', 5000);
        } else if (data.status === 'rejected') {
          showToast('عذراً — تم رفض طلبك. تواصل مع سعد.', 'error', 6000);
        }
      }
    });

    state.socket.on('closed_state', (data) => {
      const existing = document.getElementById('closed-banner');
      if (data.closed) {
        if (!existing) {
          const banner = document.createElement('div');
          banner.id = 'closed-banner';
          banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:3000;background:rgba(255,149,0,0.95);color:#fff;padding:12px 20px;padding-top:calc(12px + env(safe-area-inset-top));display:flex;align-items:center;gap:10px;font-size:14px;font-weight:600;backdrop-filter:blur(8px);';
          banner.innerHTML = `<span style="font-size:18px">⏸️</span><span style="flex:1">${data.message || 'المكتبة مغلقة حالياً — ستُطبع طلباتك عند الفتح'}</span><button onclick="this.parentElement.remove()" style="background:rgba(255,255,255,0.2);border:none;color:#fff;border-radius:50%;width:24px;height:24px;cursor:pointer;font-size:12px;">×</button>`;
          document.body.prepend(banner);
        }
      } else {
        existing?.remove();
        showToast('المكتبة مفتوحة الآن 👋', 'success', 4000);
      }
    });

    state.socket.on('disconnect', () => {
      if (!state.trackingInterval) {
        state.trackingInterval = setInterval(() => pollStatus(requestId), 6000);
      }
    });
    state.socket.on('connect', () => {
      clearInterval(state.trackingInterval);
      state.trackingInterval = null;
    });
  } catch (e) {
    // WebSocket unavailable — fall back to polling
    state.trackingInterval = setInterval(() => pollStatus(requestId), 5000);
  }
}

async function pollStatus(requestId) {
  try {
    const res  = await fetch(`${API_BASE}/status/${requestId}`);
    const data = await res.json();
    updateTimeline(data.status);
    if (data.status === 'delivered') {
      clearInterval(state.trackingInterval);
      showToast('طلبك جاهز للاستلام! 🎉', 'success', 5000);
    }
  } catch (_) {}
}

function resetAndGoHome() {
  if (state.socket) { state.socket.disconnect(); state.socket = null; }
  clearInterval(state.trackingInterval);
  state.files      = [];
  state.requestId  = '';
  state.verifyCode = '';
  state.totalPages = 0;
  state.filesCount = 0;
  $('manual-id').value   = '';
  $('manual-name').value = '';
  $('order-notes').value = '';
  $('submit-error-wrap').classList.add('hidden');
  $('notif-contact-wrap').classList.add('hidden');
  document.querySelector('input[name="notif"][value="none"]').checked = true;
  $('wait-badge').classList.add('hidden');
  renderFileList();
  showScreen('screen-login');
}

$('btn-retry-submit').addEventListener('click', () => {
  $('submit-error-wrap').classList.add('hidden');
  submitRequest();
});

$('btn-new-order').addEventListener('click', resetAndGoHome);
$('btn-completion-new').addEventListener('click', resetAndGoHome);

$('btn-copy-code').addEventListener('click', () => {
  const code = $('tracking-code').textContent.replace(/\s/g, '');
  if (!code || code === '----') return;
  navigator.clipboard.writeText(code)
    .then(() => {
      const btn = $('btn-copy-code');
      btn.textContent = '✅ تم النسخ';
      if (navigator.vibrate) navigator.vibrate(30);
      setTimeout(() => { btn.innerHTML = '📋 نسخ الرمز'; }, 2000);
    })
    .catch(() => showToast('تعذّر النسخ', 'error'));
});

// Rating stars
$('rating-stars').addEventListener('click', async e => {
  const star = e.target.closest('[data-r]');
  if (!star) return;
  const rating = +star.dataset.r;
  document.querySelectorAll('#rating-stars [data-r]').forEach(s => {
    s.classList.toggle('active', +s.dataset.r <= rating);
  });
  showToast(rating >= 4 ? 'شكراً على تقييمك 🌟' : 'شكراً، سنحسّن تجربتك', 'success', 2500);
  if (state.requestId) {
    try {
      await fetch(`${API_BASE}/rating/${state.requestId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating }),
      });
    } catch (_) {}
  }
});

// ── PWA Install ────────────────────────────────────────────────────────────────
let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredPrompt = e;
  setTimeout(() => {
    const dismissed = localStorage.getItem('pwa-dismissed');
    const dismissedAt = dismissed ? new Date(dismissed) : null;
    const cooldownPassed = !dismissedAt || (Date.now() - dismissedAt.getTime() > 24 * 60 * 60 * 1000);
    if (cooldownPassed) {
      const banner = $('pwa-banner');
      banner.style.display = 'flex';
      requestAnimationFrame(() => banner.classList.add('visible'));
    }
  }, 2000);
});

$('btn-pwa-install').addEventListener('click', async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  hidePwaBanner();
});

$('btn-pwa-dismiss').addEventListener('click', () => {
  hidePwaBanner();
  localStorage.setItem('pwa-dismissed', new Date().toISOString());
});

function hidePwaBanner() {
  const b = $('pwa-banner');
  b.classList.remove('visible');
  setTimeout(() => b.style.display = 'none', 300);
}

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
}
function isStandalone() {
  return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
}

if (isIOS() && !isStandalone()) {
  const key = localStorage.getItem('ios-dismissed');
  if (!key) {
    setTimeout(() => {
      const modal = $('ios-modal');
      modal.style.display = 'flex';
      requestAnimationFrame(() => modal.classList.add('visible'));
    }, 3000);
  }
}

$('btn-ios-close').addEventListener('click', () => {
  const modal = $('ios-modal');
  modal.classList.remove('visible');
  setTimeout(() => modal.style.display = 'none', 300);
  localStorage.setItem('ios-dismissed', '1');
});

// ── Closed-mode banner ──────────────────────────────────────────────
fetch(`${API_BASE}/closed`)
  .then(r => r.json())
  .then(data => {
    if (data.closed) {
      const banner = document.createElement('div');
      banner.id = 'closed-banner';
      banner.style.cssText = `
        position:fixed;top:0;left:0;right:0;z-index:3000;
        background:rgba(255,149,0,0.95);color:#fff;
        padding:12px 20px;padding-top:calc(12px + env(safe-area-inset-top));
        display:flex;align-items:center;gap:10px;
        font-size:14px;font-weight:600;backdrop-filter:blur(8px);
      `;
      banner.innerHTML = `
        <span style="font-size:18px">⏸️</span>
        <span style="flex:1">${data.message || 'المكتبة مغلقة حالياً — ستُطبع طلباتك عند الفتح'}</span>
        <button onclick="this.parentElement.remove()" style="background:rgba(255,255,255,0.2);border:none;color:#fff;border-radius:50%;width:24px;height:24px;cursor:pointer;font-size:12px;">×</button>
      `;
      document.body.prepend(banner);
    }
  })
  .catch(() => {});

// ── 30-min idle session timeout ──────────────────────────────────
const IDLE_TIMEOUT = 30 * 60 * 1000;
let idleTimer;
function resetIdle() {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    const active = document.querySelector('.screen.active');
    const isTracking = active && (active.id === 'screen-tracking' || active.id === 'screen-completion');
    if (isTracking) return;
    showToast('انتهت جلستك بسبب عدم النشاط 🔒', 'info', 5000);
    setTimeout(resetAndGoHome, 800);
  }, IDLE_TIMEOUT);
}
['touchstart', 'touchend', 'mousemove', 'keydown', 'click', 'scroll'].forEach(ev =>
  document.addEventListener(ev, resetIdle, { passive: true })
);
resetIdle();

// ── Server connection monitor ──────────────────────────────────────
let _connBanner = null;

async function checkServerConnection() {
  try {
    const res = await fetch(`${_host}/health`, { cache: 'no-store', signal: AbortSignal.timeout(4000) });
    if (res.ok) {
      state.serverOnline = true;
      if (_connBanner) { _connBanner.remove(); _connBanner = null; }
      const btn = $('btn-submit');
      if (btn && !btn.dataset.uploading) btn.disabled = false;
      return true;
    }
  } catch (_) {}
  state.serverOnline = false;

  if (!_connBanner) {
    _connBanner = document.createElement('div');
    _connBanner.id = 'conn-banner';
    _connBanner.style.cssText = [
      'position:fixed;bottom:0;left:0;right:0;z-index:3500',
      'background:rgba(255,59,48,0.93);color:#fff',
      'padding:12px 20px;padding-bottom:calc(12px + env(safe-area-inset-bottom))',
      'display:flex;align-items:center;gap:10px',
      'font-size:13px;font-weight:600;backdrop-filter:blur(8px)',
    ].join(';');
    _connBanner.innerHTML = [
      '<span style="font-size:18px">⚠️</span>',
      '<span style="flex:1">الخادم غير متاح — تحقّق من اتصال الجهاز بالشبكة</span>',
      '<button id="btn-conn-retry" style="background:rgba(255,255,255,0.2);border:none;color:#fff;border-radius:9999px;padding:4px 12px;cursor:pointer;font-size:12px;">\u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629</button>',
    ].join('');
    document.body.appendChild(_connBanner);
    document.getElementById('btn-conn-retry')?.addEventListener('click', () => checkServerConnection());
  }
  return false;
}

checkServerConnection();
setInterval(checkServerConnection, 15000);
