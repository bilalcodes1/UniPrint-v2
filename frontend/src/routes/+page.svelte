<script>
  import { onMount, onDestroy } from 'svelte';
  import { io } from 'socket.io-client';
  import { tweened } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import apiClient, { SOCKET_URL } from '$lib/api.js';

  let stats = { today_total: 0, today_done: 0, pending: 0, today_pages: 0, total_students: 0 };
  let requests = [];
  let loading = true;
  let searchQuery = '';
  let filterStatus = '';
  let verifyInputs = {};
  let verifyErrors = {};
  let actionLoading = {};
  let socket;
  let toasts = [];
  let toastId = 0;
  let newRequestIds = new Set();
  let backendOffline = false;

  // File preview modal
  let previewModal = null; // { fileId, name, mime, url }

  // Disk space
  let disk = null;
  let diskWarningDismissed = false;

  // Library closed mode
  let libraryClosed = false;
  let closedMessage = 'المكتبة مغلقة حالياً — ستُطبع الطلبات عند الفتح';
  let closedLoading = false;

  // Pagination
  let currentPage = 1;
  let hasMore = false;
  let loadingMore = false;
  let requestsTotal = 0;

  // Active section
  let activeSection = 'dashboard';

  // Settings section
  let settingsForm = {
    operator_name:    'سعد',
    library_name:     'مكتبة جامعة الأنبار',
    library_path:     '',
    schedule_enabled: false,
    open_time:        '08:00',
    close_time:       '17:00',
    close_message:    'المكتبة مغلقة – يفتح الساعة 08:00',
    retention_days:   30,
  };
  let settingsSaving = false;
  let settingsSaved = false;

  async function loadSettings() {
    try {
      const s = await apiClient.getSettings();
      settingsForm = {
        operator_name:    s.operator_name    || 'سعد',
        library_name:     s.library_name     || '',
        library_path:     s.library_path     || '',
        schedule_enabled: s.schedule_enabled === '1',
        open_time:        s.open_time        || '08:00',
        close_time:       s.close_time       || '17:00',
        close_message:    s.close_message    || 'المكتبة مغلقة – يفتح الساعة 08:00',
        retention_days:   parseInt(s.retention_days) || 30,
      };
    } catch {}
  }

  async function saveSettings() {
    settingsSaving = true;
    try {
      const payload = {
        ...settingsForm,
        schedule_enabled: settingsForm.schedule_enabled ? '1' : '0',
        retention_days:   String(settingsForm.retention_days || 30),
      };
      await apiClient.updateSettings(payload);
      operatorName = settingsForm.operator_name;
      localStorage.setItem('uniprint_operator', operatorName);
      settingsSaved = true;
      setTimeout(() => settingsSaved = false, 2500);
    } catch { showToast('خطأ في الحفظ', 'error'); }
    settingsSaving = false;
  }

  function goTo(section) {
    activeSection = section;
    if (section === 'settings') loadSettings();
  }

  // Setup wizard
  let showWizard = false;
  let wizardStep = 1;
  let wizardLoading = false;
  let wizardSettings = { operator_name: 'سعد', library_name: 'مكتبة جامعة الأنبار', library_path: '' };
  let wizardScanStatus = '';
  let wizardTestStatus = '';

  // Count-up tweened values
  const tw_total   = tweened(0, { duration: 800, easing: cubicOut });
  const tw_done    = tweened(0, { duration: 800, easing: cubicOut });
  const tw_pending = tweened(0, { duration: 800, easing: cubicOut });
  const tw_pages   = tweened(0, { duration: 900, easing: cubicOut });

  const STATUS_LABELS = {
    received:  'استُلم',
    waiting:   'انتظار',
    ready:     'جاهز',
    rejected:  'مرفوض',
    delivered: 'سُلّم',
  };

  function showToast(msg, type = 'default') {
    const id = ++toastId;
    toasts = [...toasts, { id, msg, type }];
    setTimeout(() => { toasts = toasts.filter(t => t.id !== id); }, 3500);
  }

  function launchConfetti() {
    const colors = ['#2D6BE4', '#34C759', '#FF9500', '#FF3B30', '#5AC8FA'];
    for (let i = 0; i < 35; i++) {
      const el = document.createElement('div');
      const size = 4 + Math.random() * 6;
      el.style.cssText = `position:fixed;top:0;left:${Math.random()*100}vw;
        width:${size}px;height:${size*1.5}px;
        background:${colors[Math.floor(Math.random()*colors.length)]};
        border-radius:2px;pointer-events:none;z-index:9999;
        animation:confetti-fall ${0.8+Math.random()*0.8}s ease-out ${Math.random()*0.4}s both;`;
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 2000);
    }
  }

  async function loadData() {
    try {
      const [s, r, d, c] = await Promise.all([
        apiClient.getStats(),
        apiClient.getRecentRequests(1, 20),
        apiClient.getDiskInfo(),
        apiClient.getClosedState(),
      ]);
      backendOffline = false;
      stats = s;
      requests = r.items ?? r;
      requestsTotal = r.total ?? requests.length;
      hasMore = r.has_more ?? false;
      currentPage = 1;
      disk  = d;
      libraryClosed = c.closed;
      if (c.message) closedMessage = c.message;
      tw_total.set(s.today_total);
      tw_done.set(s.today_done);
      tw_pending.set(s.pending);
      tw_pages.set(s.today_pages);
    } catch (e) {
      backendOffline = true;
      showToast('تعذّر الاتصال بالخادم', 'error');
    } finally {
      loading = false;
    }
  }

  async function loadMore() {
    if (loadingMore || !hasMore) return;
    loadingMore = true;
    try {
      const r = await apiClient.getRecentRequests(currentPage + 1, 20);
      requests = [...requests, ...(r.items ?? [])];
      currentPage = r.page;
      hasMore = r.has_more;
    } catch (e) {
      showToast('خطأ في تحميل المزيد', 'error');
    } finally {
      loadingMore = false;
    }
  }

  async function checkSetup() {
    try {
      const status = await apiClient.getSetupStatus();
      if (!status.setup_complete) {
        const s = await apiClient.getSettings();
        wizardSettings.operator_name = s.operator_name || 'سعد';
        wizardSettings.library_name  = s.library_name  || 'مكتبة جامعة الأنبار';
        wizardSettings.library_path  = s.library_path  || '';
        showWizard = true;
      }
    } catch (_) {}
  }

  async function wizardScan() {
    if (!wizardSettings.library_path) { wizardScanStatus = 'error'; return; }
    wizardScanStatus = 'scanning';
    try {
      const res = await apiClient.scanLibrary(wizardSettings.library_path);
      wizardScanStatus = 'done';
    } catch (e) {
      wizardScanStatus = 'error';
    }
  }

  async function finishWizard() {
    wizardLoading = true;
    try {
      await apiClient.updateSettings({
        operator_name:   wizardSettings.operator_name,
        library_name:    wizardSettings.library_name,
        library_path:    wizardSettings.library_path,
        setup_complete:  '1',
      });
      localStorage.setItem('uniprint_operator', wizardSettings.operator_name);
      operatorName = wizardSettings.operator_name;
      showWizard = false;
      showToast('تم الإعداد بنجاح 🎉', 'success');
    } catch (e) {
      showToast('خطأ في حفظ الإعدادات', 'error');
    } finally {
      wizardLoading = false;
    }
  }

  async function openPreview(reqId) {
    try {
      const files = await apiClient.getRequestFiles(reqId);
      if (!files || files.length === 0) { showToast('لا توجد ملفات', 'info'); return; }
      const f = files[0];
      previewModal = {
        fileId: f.id,
        name:   f.original_name,
        mime:   f.mime_type,
        url:    `http://localhost:5001/api/files/${f.id}/preview`,
        files,
        currentIdx: 0,
      };
    } catch (e) {
      showToast('تعذّر تحميل الملف', 'error');
    }
  }

  function switchPreview(idx) {
    if (!previewModal) return;
    const f = previewModal.files[idx];
    previewModal = { ...previewModal, fileId: f.id, name: f.original_name, mime: f.mime_type,
      url: `http://localhost:5001/api/files/${f.id}/preview`, currentIdx: idx };
  }

  async function toggleClosed() {
    closedLoading = true;
    try {
      const result = await apiClient.setClosedState(!libraryClosed, closedMessage);
      libraryClosed = result.closed;
      showToast(libraryClosed ? 'تم إغلاق المكتبة مؤقتاً ⏸️' : 'تم فتح المكتبة ✅', libraryClosed ? 'info' : 'success');
    } catch (e) {
      showToast('تعذّر تغيير الحالة', 'error');
    } finally {
      closedLoading = false;
    }
  }

  let successFlash = {};

  async function handlePrint(req) {
    const code = (verifyInputs[req.id] || '').trim();
    if (code.length !== 4) { verifyErrors[req.id] = true; return; }
    verifyErrors[req.id] = false;
    actionLoading[req.id] = 'print';
    try {
      await apiClient.printRequest(req.id, code);
      requests = requests.map(r => r.id === req.id ? { ...r, status: 'waiting' } : r);
      showToast('بدأت الطباعة ✅', 'success');
      successFlash[req.id] = true;
      verifyInputs[req.id] = '';
      setTimeout(() => { successFlash = { ...successFlash, [req.id]: false }; }, 1500);
    } catch (e) {
      verifyErrors[req.id] = true;
      showToast(e.message || 'خطأ في الطباعة', 'error');
    } finally {
      actionLoading[req.id] = null;
      loadData();
    }
  }

  async function handleReject(req) {
    if (!confirm(`رفض طلب ${req.student_name || 'الطالب'}؟ لن يتمكن من الطباعة.`)) return;
    actionLoading[req.id] = 'reject';
    try {
      await apiClient.rejectRequest(req.id);
      requests = requests.filter(r => r.id !== req.id);
      showToast('تم رفض الطلب', 'error');
    } catch (e) {
      showToast(e.message || 'خطأ في الرفض', 'error');
    } finally {
      actionLoading[req.id] = null;
    }
  }

  async function handleReady(req) {
    actionLoading[req.id] = 'ready';
    try {
      await apiClient.markReady(req.id);
      requests = requests.map(r => r.id === req.id ? { ...r, status: 'ready' } : r);
      showToast('\u062c\u0627\u0647\u0632 \u0644\u0644\u0627\u0633\u062a\u0644\u0627\u0645 \u2705', 'success');
      successFlash[req.id] = true;
      setTimeout(() => { successFlash = { ...successFlash, [req.id]: false }; }, 1500);
    } catch (e) {
      showToast(e.message || '\u062e\u0637\u0623', 'error');
    } finally {
      actionLoading[req.id] = null;
    }
  }

  async function handleDeliver(req) {
    const code = (verifyInputs[req.id] || '').trim();
    if (code.length !== 4) { verifyErrors[req.id] = true; return; }
    verifyErrors[req.id] = false;
    actionLoading[req.id] = 'deliver';
    try {
      await apiClient.deliverRequest(req.id, code);
      requests = requests.map(r => r.id === req.id ? { ...r, status: 'delivered' } : r);
      stats = { ...stats, today_done: stats.today_done + 1, pending: Math.max(0, stats.pending - 1) };
      showToast('تم التسليم 🎉', 'success');
      launchConfetti();
      successFlash[req.id] = true;
      verifyInputs[req.id] = '';
      setTimeout(() => { successFlash = { ...successFlash, [req.id]: false }; }, 1500);
    } catch (e) {
      verifyErrors[req.id] = true;
      showToast(e.message || 'خطأ في التسليم', 'error');
    } finally {
      actionLoading[req.id] = null;
      loadData();
    }
  }

  async function handleSearch() {
    loading = true;
    try {
      requests = await apiClient.searchRequests(searchQuery, filterStatus);
    } catch (e) {
      showToast('خطأ في البحث', 'error');
    } finally {
      loading = false;
    }
  }

  function connectSocket() {
    socket = io(SOCKET_URL, { transports: ['websocket', 'polling'] });

    socket.on('new_request', (data) => {
      showToast(`طلب جديد 📥 — ${data.student_name || 'طالب'}`, 'info');
      stats = { ...stats, today_total: stats.today_total + 1, pending: stats.pending + 1 };
      tw_total.set(stats.today_total);
      tw_pending.set(stats.pending);
      if (data.request_id) newRequestIds = new Set([...newRequestIds, data.request_id]);
      loadData().then(() => {
        setTimeout(() => { newRequestIds = new Set(); }, 600);
      });
    });

    socket.on('status_update', (data) => {
      requests = requests.map(r =>
        r.id === data.request_id ? { ...r, status: data.status } : r
      );
      if (data.status === 'delivered') {
        showToast('تم التسليم 🎉', 'success');
        launchConfetti();
      }
    });

    socket.on('closed_state', (data) => {
      libraryClosed = data.closed;
      closedMessage = data.message;
    });
  }

  let pollingInterval;
  let searchInputEl;

  function handleKeydown(e) {
    if (e.key === 'Escape' && previewModal) { previewModal = null; return; }
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      searchInputEl?.focus();
    }
  }

  let pollingDot = false;

  onMount(() => {
    operatorName = localStorage.getItem('uniprint_operator') || 'سعد';
    loadData();
    checkSetup();
    connectSocket();
    pollingInterval = setInterval(async () => {
      pollingDot = true;
      await loadData();
      setTimeout(() => { pollingDot = false; }, 400);
    }, 5000);
    window.addEventListener('keydown', handleKeydown);
  });

  onDestroy(() => {
    socket?.disconnect();
    clearInterval(pollingInterval);
    window.removeEventListener('keydown', handleKeydown);
  });

  let operatorName = 'سعد';
  let editingName = false;

  $: pendingRequests   = requests.filter(r => r.status === 'received');
  $: waitingRequests   = requests.filter(r => r.status === 'waiting');
  $: completedRequests = requests.filter(r => r.status === 'delivered');
  $: newActiveRequests = requests.filter(r => ['received','waiting','ready'].includes(r.status));
  $: studentMap = Object.values(requests.reduce((m, r) => { const k = r.student_national_id_hash; if (!m[k]) m[k] = { hash: k, name: r.student_name || 'غير معروف', count: 0, last: r.created_at }; m[k].count++; return m; }, {}));
  $: displayRequests = activeSection === 'new-requests' ? newActiveRequests : activeSection === 'completed' ? completedRequests : requests;
  $: sectionTitle = activeSection === 'new-requests' ? 'الطلبات النشطة' : activeSection === 'completed' ? 'الطلبات المكتملة' : 'الطلبات الأخيرة';

  function greetingText() {
    const h = new Date().getHours();
    if (h < 12) return 'صباح الخير';
    if (h < 17) return 'مساء الخير';
    return 'مساء النور';
  }

  function saveOperatorName(name) {
    const trimmed = name.trim();
    if (trimmed) { operatorName = trimmed; localStorage.setItem('uniprint_operator', trimmed); }
    editingName = false;
  }

  function formatTime(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleTimeString('ar-IQ', { hour: '2-digit', minute: '2-digit' });
  }
</script>

<svelte:head>
  <title>UniPrint — لوحة التحكم</title>
</svelte:head>

<style>
  @keyframes confetti-fall {
    0%   { transform: translateY(-10px) rotate(0deg);   opacity: 1; }
    100% { transform: translateY(120px) rotate(360deg); opacity: 0; }
  }

  .layout { display: flex; min-height: 100vh; }

  /* ── Sidebar ── */
  .sidebar {
    width: 220px; flex-shrink: 0;
    background: var(--bg-sidebar); color: #fff;
    display: flex; flex-direction: column; gap: 4px;
    padding: 20px 12px;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
  }
  .sidebar-logo {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px 20px;
    font-size: 18px; font-weight: 700;
  }
  .sidebar-logo span { font-size: 26px; }
  .sidebar-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 12px; border-radius: var(--radius-md);
    font-size: 14px; font-weight: 500; color: rgba(255,255,255,0.7);
    cursor: pointer; transition: background var(--transition-fast), color var(--transition-fast);
    user-select: none;
  }
  .sidebar-item:hover, .sidebar-item.active {
    background: rgba(255,255,255,0.1); color: #fff;
  }
  .sidebar-badge {
    margin-right: auto;
    background: var(--color-danger); color: #fff;
    font-size: 11px; font-weight: 700;
    padding: 1px 7px; border-radius: var(--radius-full);
  }
  .sidebar-footer { margin-top: auto; padding: 12px; display: flex; flex-direction: column; gap: 4px; }
  .sidebar-version { font-size: 11px; color: rgba(255,255,255,0.3); }
  .conn-dot { display: flex; align-items: center; gap: 6px; font-size: 12px; color: rgba(255,255,255,0.5); }
  .conn-dot__circle {
    width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  }
  .conn-dot.online  .conn-dot__circle { background: #34C759; animation: pulse-dot 2s ease-in-out infinite; }
  .conn-dot.offline .conn-dot__circle { background: #FF3B30; }

  /* ── Main ── */
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  .topbar {
    background: var(--bg-card); border-bottom: 1px solid var(--border-light);
    padding: 0 28px; height: 56px;
    display: flex; align-items: center; gap: 12px;
  }
  .topbar-title { font-size: 17px; font-weight: 600; flex: 1; }
  .topbar-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-success); animation: pulse-dot 2s ease infinite; }
  .topbar-dot.offline { background: var(--color-danger); animation: none; }
  .polling-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-primary); opacity: 0.7; animation: pulse-dot 0.4s ease both; margin-right: 6px; }

  .content { flex: 1; overflow-y: auto; padding: 28px; }

  /* ── Greeting ── */
  .greeting { font-size: 22px; font-weight: 700; margin-bottom: 20px; }
  .greeting span { color: var(--color-primary); }
  .name-edit {
    display: inline; width: 120px; font-size: 22px; font-weight: 700;
    color: var(--color-primary); border: none; border-bottom: 2px solid var(--color-primary);
    background: transparent; font-family: inherit; outline: none; padding: 0 2px;
  }

  /* ── Stats ── */
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
  .stat-card { padding: 20px; }
  .stat-label { font-size: 12px; color: var(--text-secondary); font-weight: 500; margin-bottom: 6px; }
  .stat-value { font-size: 32px; font-weight: 700; color: var(--text-primary); line-height: 1; }
  .stat-sub { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }

  /* ── Search bar ── */
  .search-bar {
    display: flex; gap: 10px; margin-bottom: 20px;
  }
  .search-input {
    flex: 1; height: 40px; padding: 0 14px;
    background: var(--bg-card); border: 1.5px solid var(--border-medium);
    border-radius: var(--radius-md); font-family: inherit; font-size: 14px;
    color: var(--text-primary); direction: rtl;
    transition: border-color var(--transition-fast);
  }
  .search-input:focus { outline: none; border-color: var(--color-primary); }
  select.search-input { cursor: pointer; }

  /* ── Requests table ── */
  .section-title { font-size: 16px; font-weight: 700; margin-bottom: 12px; }
  .requests-list { display: flex; flex-direction: column; gap: 10px; }

  @keyframes slide-in-right { from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }
  @keyframes success-pulse { 0%,100%{ box-shadow:var(--shadow-sm); } 40%{ box-shadow:0 0 0 4px rgba(52,199,89,0.25); } }
  .req-card { padding: 16px 20px; transition: box-shadow var(--transition-fast); }
  .req-card:hover { box-shadow: var(--shadow-md); }
  .req-card.new-in { animation: slide-in-right 0.30s ease-out both; }
  .req-card.success-flash { animation: success-pulse 1.5s ease both; }

  .req-top { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
  .req-name-wrap { display: flex; flex-direction: column; gap: 2px; }
  .req-name { font-weight: 600; font-size: 15px; }
  .req-id   { font-size: 10px; color: var(--text-tertiary); font-variant-numeric: tabular-nums; letter-spacing: 1px; }
  .req-meta { font-size: 12px; color: var(--text-secondary); margin-right: auto; }
  .req-files { font-size: 13px; color: var(--text-secondary); }
  .req-notes  { font-size: 12px; color: var(--text-secondary); margin-top: 6px; padding: 6px 10px; background: rgba(255,204,0,0.08); border-radius: var(--radius-sm); border-inline-start: 3px solid var(--color-warning); }

  .req-actions { display: flex; align-items: center; gap: 10px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-light); }

  .verify-inputs { display: flex; gap: 6px; }
  .verify-box {
    width: 40px; height: 40px; text-align: center;
    border: 1.5px solid var(--border-medium); border-radius: var(--radius-md);
    font-size: 18px; font-weight: 700; font-family: monospace;
    background: var(--bg-primary); color: var(--text-primary);
    transition: border-color var(--transition-fast);
    direction: ltr;
  }
  .verify-box:focus { outline: none; border-color: var(--color-primary); box-shadow: 0 0 0 3px var(--color-primary-glass); }
  .verify-box.error { border-color: var(--color-danger); animation: shake 0.35s ease both; }
  .verify-box.ok    { border-color: var(--color-success); background: rgba(52,199,89,0.07); }

  @keyframes shake {
    0%,100%{ transform:translateX(0); }
    20%{ transform:translateX(-5px); }
    40%{ transform:translateX(5px); }
    60%{ transform:translateX(-3px); }
    80%{ transform:translateX(3px); }
  }

  .spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.4);
    border-top-color: #fff; border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  /* ── Skeleton shimmer ── */
  @keyframes shimmer { from { background-position: -400px 0; } to { background-position: 400px 0; } }
  .skel {
    border-radius: var(--radius-sm);
    background: linear-gradient(90deg, var(--border-light) 25%, var(--border-medium) 50%, var(--border-light) 75%);
    background-size: 400px 100%;
    animation: shimmer 1.4s ease-in-out infinite;
  }
  .skel-line { display: block; }

  /* ── Empty state ── */
  .empty { text-align: center; padding: 60px 20px; color: var(--text-secondary); }
  .empty-icon { font-size: 48px; margin-bottom: 12px; }
  .empty-msg { font-size: 16px; font-weight: 600; color: var(--text-primary); }
  .empty-sub { font-size: 13px; margin-top: 6px; }

  /* ── Toast ── */
  .toast-wrap {
    position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
    z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none;
  }
  .toast {
    padding: 10px 20px; border-radius: var(--radius-full);
    font-size: 13px; font-weight: 600; color: #fff;
    background: #1C1C1E; box-shadow: var(--shadow-lg);
    animation: slide-up 0.3s ease-out both;
    white-space: nowrap;
  }
  .toast.success { background: var(--color-success); }
  .toast.error   { background: var(--color-danger); }
  .toast.info    { background: var(--color-primary); }

  /* ── Alert banner ── */
  .alert-banner {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 16px; border-radius: var(--radius-md);
    margin-bottom: 16px; font-size: 14px; font-weight: 500;
  }
  .alert-warning { background: rgba(255,149,0,0.12); color: var(--color-warning); }

  /* ── Closed-mode bar ── */
  .closed-bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 16px; border-radius: var(--radius-md);
    margin-bottom: 20px; font-size: 14px; font-weight: 500;
    transition: background var(--transition-normal);
  }
  .closed-bar.open   { background: rgba(52,199,89,0.10);  color: var(--color-success); }
  .closed-bar.closed { background: rgba(255,149,0,0.10);  color: var(--color-warning); }
  .closed-bar__info  { display: flex; align-items: center; gap: 8px; }
  .closed-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: currentColor; animation: pulse-dot 2s ease infinite;
  }
  .btn-closed { background: rgba(255,149,0,0.15); color: var(--color-warning); }
  .btn-closed:hover { background: rgba(255,149,0,0.25); }

  /* ── Disk bar ── */
  .disk-bar { padding: 14px 16px; margin-bottom: 20px; }
  .disk-bar__header {
    display: flex; justify-content: space-between;
    font-size: 13px; font-weight: 500; margin-bottom: 8px;
  }
  .disk-bar__nums { color: var(--text-secondary); }
  .disk-track {
    height: 6px; background: var(--border-light);
    border-radius: var(--radius-full); overflow: hidden;
  }
  .disk-fill {
    height: 100%; border-radius: var(--radius-full);
    background: var(--color-primary);
    transition: width 0.8s cubic-bezier(0.25,0.46,0.45,0.94);
  }
  .disk-fill.warn { background: var(--color-danger); }

  /* ── File Preview Modal ── */
  .preview-backdrop {
    position: fixed; inset: 0; z-index: 4000;
    background: rgba(0,0,0,0.55); backdrop-filter: blur(6px);
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
    animation: slide-up 0.25s ease-out both;
  }
  .preview-card {
    background: var(--bg-card); border-radius: var(--radius-xl);
    box-shadow: var(--shadow-xl); width: 100%; max-width: 820px;
    max-height: 90vh; display: flex; flex-direction: column; overflow: hidden;
    transform: scale(0.97);
    animation: preview-in 0.25s ease-out both;
  }
  @keyframes preview-in {
    from { opacity:0; transform: scale(0.95); }
    to   { opacity:1; transform: scale(1); }
  }
  .preview-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px; border-bottom: 1px solid var(--border-light);
  }
  .preview-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
  .preview-tabs {
    display: flex; gap: 6px; padding: 10px 16px;
    border-bottom: 1px solid var(--border-light); overflow-x: auto;
  }
  .preview-tab {
    flex-shrink: 0; padding: 5px 12px; border-radius: var(--radius-full);
    border: 1px solid var(--border-medium); background: transparent;
    font-size: 12px; font-weight: 500; cursor: pointer; color: var(--text-secondary);
    transition: all var(--transition-fast);
  }
  .preview-tab.active { background: var(--color-primary); color: #fff; border-color: transparent; }
  .preview-body { flex: 1; overflow: auto; min-height: 400px; }
  .preview-iframe { width: 100%; height: 100%; min-height: 500px; border: none; }
  .preview-img { max-width: 100%; height: auto; display: block; margin: auto; padding: 16px; }

  /* ── Offline banner ── */
  .offline-banner {
    position: fixed; top: 0; left: 0; right: 0; z-index: 3500;
    background: rgba(255,59,48,0.92); color: #fff;
    padding: 10px 20px; font-size: 13px; font-weight: 600;
    display: flex; align-items: center; gap: 8px;
    backdrop-filter: blur(8px);
    animation: slide-up 0.25s ease-out both;
  }

  @media (max-width: 900px) {
    .stats-grid { grid-template-columns: repeat(2,1fr); }
    .sidebar { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
  }
</style>

<!-- File Preview Modal -->
{#if previewModal}
  <div class="preview-backdrop" on:click={() => previewModal = null} role="dialog" aria-modal="true">
    <div class="preview-card" on:click|stopPropagation>
      <div class="preview-header">
        <span class="preview-title">{previewModal.name}</span>
        <div style="display:flex;gap:8px;align-items:center">
          <a class="btn btn-ghost btn-sm" href={previewModal.url} download={previewModal.name}>⬇️ تحميل</a>
          <button class="btn btn-ghost btn-sm" on:click={() => previewModal = null}>✕ إغلاق</button>
        </div>
      </div>

      {#if previewModal.files.length > 1}
        <div class="preview-tabs">
          {#each previewModal.files as f, i}
            <button class="preview-tab {previewModal.currentIdx === i ? 'active' : ''}"
              on:click={() => switchPreview(i)}>
              {f.original_name}
            </button>
          {/each}
        </div>
      {/if}

      <div class="preview-body">
        {#if previewModal.mime?.startsWith('image/')}
          <img src={previewModal.url} alt={previewModal.name} class="preview-img" />
        {:else}
          <iframe src={previewModal.url} title={previewModal.name} class="preview-iframe"></iframe>
        {/if}
      </div>
    </div>
  </div>
{/if}

<!-- Backend Offline Banner -->
{#if backendOffline}
  <div class="offline-banner" role="alert">
    ⚠️ الخادم غير متاح — البيانات قد تكون غير محدّثة
    <button class="btn btn-ghost btn-sm" on:click={loadData} style="margin-right:8px">إعادة المحاولة ↻</button>
  </div>
{/if}

<!-- Toast container -->
<div class="toast-wrap">
  {#each toasts as t (t.id)}
    <div class="toast {t.type}">{t.msg}</div>
  {/each}
</div>

<div class="layout">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-logo"><span>🖨️</span> UniPrint</div>

    <div class="sidebar-item {activeSection==='dashboard'?'active':''}" on:click={() => goTo('dashboard')}>📊 لوحة التحكم</div>
    <div class="sidebar-item {activeSection==='new-requests'?'active':''}" on:click={() => goTo('new-requests')}>
      📋 الطلبات الجديدة
      {#if newActiveRequests.length > 0}<span class="sidebar-badge">{newActiveRequests.length}</span>{/if}
    </div>
    <div class="sidebar-item {activeSection==='completed'?'active':''}" on:click={() => goTo('completed')}>✅ المكتملة</div>
    <div class="sidebar-item {activeSection==='students'?'active':''}" on:click={() => goTo('students')}>👥 الطلاب</div>
    <div class="sidebar-item {activeSection==='stats'?'active':''}" on:click={() => goTo('stats')}>📈 الإحصاءات</div>
    <div class="sidebar-item {activeSection==='settings'?'active':''}" on:click={() => goTo('settings')}>⚙️ الإعدادات</div>

    <div class="sidebar-footer">
      <div class="conn-dot {backendOffline ? 'offline' : 'online'}">
        <span class="conn-dot__circle"></span>
        {backendOffline ? 'غير متصل' : 'متصل'}
      </div>
      <div class="sidebar-version">v2.0.0</div>
    </div>
  </aside>

  <!-- Main content -->
  <div class="main">
    <!-- Topbar -->
    <header class="topbar">
      <div class="topbar-dot {backendOffline ? 'offline' : ''}"></div>
      <div class="topbar-title">UniPrint Dashboard</div>
      {#if pollingDot}<div class="polling-dot"></div>{/if}
      <span style="font-size:13px;color:var(--text-secondary);">
        {new Date().toLocaleDateString('ar-IQ', { weekday:'long', day:'numeric', month:'long' })}
      </span>
    </header>

    <!-- Content -->
    <main class="content">
      <p class="greeting">
        {greetingText()}،
        {#if editingName}
          <input class="name-edit" value={operatorName} autofocus
            on:blur={e => saveOperatorName(e.target.value)}
            on:keydown={e => { if (e.key === 'Enter') saveOperatorName(e.target.value); if (e.key === 'Escape') editingName = false; }}
          />
        {:else}
          <span title="اضغط لتغيير الاسم" style="cursor:pointer" on:click={() => editingName = true}>{operatorName}!</span>
        {/if}
        ☀️
      </p>

      <!-- Disk space warning -->
      {#if disk && disk.warning && !diskWarningDismissed}
        <div class="alert-banner alert-warning">
          <span>⚠️ المساحة المتبقية: <strong>{disk.free_gb} GB</strong> ({disk.pct_free}%)</span>
          <button class="btn btn-sm" on:click={() => diskWarningDismissed = true}>تجاهل ×</button>
        </div>
      {/if}

      <!-- Library closed mode -->
      <div class="closed-bar {libraryClosed ? 'closed' : 'open'}">
        <div class="closed-bar__info">
          <span class="closed-dot"></span>
          <span>{libraryClosed ? 'مغلق — ' + closedMessage : 'المكتبة مفتوحة • تستقبل طلبات'}</span>
        </div>
        <button class="btn btn-sm {libraryClosed ? 'btn-success' : 'btn-closed'}"
          on:click={toggleClosed} disabled={closedLoading}>
          {closedLoading ? '…' : libraryClosed ? '✅ فتح المكتبة' : '⏸️ إغلاق مؤقت'}
        </button>
      </div>

      {#if activeSection === 'dashboard'}
      <!-- Stats -->
      <div class="stats-grid">
        <div class="card stat-card animate-up">
          <div class="stat-label">طلبات اليوم</div>
          <div class="stat-value">{Math.round($tw_total)}</div>
          <div class="stat-sub">📋 إجمالي</div>
        </div>
        <div class="card stat-card animate-up" style="animation-delay:60ms">
          <div class="stat-label">مكتملة اليوم</div>
          <div class="stat-value">{Math.round($tw_done)}</div>
          <div class="stat-sub">✅ تم التسليم</div>
        </div>
        <div class="card stat-card animate-up" style="animation-delay:120ms">
          <div class="stat-label">قيد الانتظار</div>
          <div class="stat-value">{Math.round($tw_pending)}</div>
          <div class="stat-sub">⏳ لم تُطبع بعد</div>
        </div>
        <div class="card stat-card animate-up" style="animation-delay:180ms">
          <div class="stat-label">صفحات اليوم</div>
          <div class="stat-value">{Math.round($tw_pages)}</div>
          <div class="stat-sub">📄 مجموع الصفحات</div>
        </div>
      </div>

      <!-- Disk space bar -->
      {#if disk}
        <div class="disk-bar card">
          <div class="disk-bar__header">
            <span>💾 المساحة المتبقية</span>
            <span class="disk-bar__nums">{disk.free_gb} GB حر من {disk.total_gb} GB</span>
          </div>
          <div class="disk-track">
            <div class="disk-fill {disk.warning ? 'warn' : ''}" style="width:{disk.pct_used}%"></div>
          </div>
        </div>
      {/if}
      {/if}

      {#if activeSection !== 'students' && activeSection !== 'stats' && activeSection !== 'settings'}
      <!-- Search -->
      <div class="search-bar">
        <input
          class="search-input"
          placeholder="بحث بالاسم أو رقم الطلب… (⌘K)"
          bind:value={searchQuery}
          bind:this={searchInputEl}
          on:keydown={e => e.key === 'Enter' && handleSearch()}
        />
        <select class="search-input" style="width:140px" bind:value={filterStatus} on:change={handleSearch}>
          <option value="">كل الحالات</option>
          <option value="received">استُلم</option>
          <option value="waiting">انتظار</option>
          <option value="ready">جاهز</option>
          <option value="delivered">سُلّم</option>
        </select>
        <button class="btn btn-primary btn-sm" on:click={handleSearch}>بحث</button>
      </div>

      <!-- Requests list -->
      <p class="section-title">{sectionTitle}</p>

      {#if loading}
        <div class="requests-list">
          {#each [1,2,3] as _}
            <div class="card req-card skeleton-card">
              <div class="skel skel-line" style="width:30%;height:18px"></div>
              <div class="skel skel-line" style="width:55%;height:14px;margin-top:8px"></div>
              <div class="skel skel-line" style="width:80%;height:12px;margin-top:8px"></div>
            </div>
          {/each}
        </div>
      {:else if displayRequests.length === 0}
        <div class="empty">
          <div class="empty-icon">🎉</div>
          <div class="empty-msg">لا توجد طلبات حالياً</div>
          <div class="empty-sub">الطلبات الجديدة ستظهر هنا مباشرة</div>
        </div>
      {:else}
        <div class="requests-list">
          {#each displayRequests as req (req.id)}
            <div class="card req-card
              {newRequestIds.has(req.id) ? 'new-in' : ''}
              {successFlash[req.id] ? 'success-flash' : ''}">
              <div class="req-top">
                <span class="badge badge-{req.status}">{STATUS_LABELS[req.status] ?? req.status}</span>
                <div class="req-name-wrap">
                  <span class="req-name">{req.student_name || 'طالب غير معروف'}</span>
                  <span class="req-id">{req.id.slice(0,8).toUpperCase()}</span>
                </div>
                <span class="req-meta">{formatTime(req.created_at)}</span>
              </div>

              <div class="req-files">
                📁 {req.files_count ?? 0} ملف  ·  📄 {req.total_pages ?? 0} صفحة
                · رمز: <strong style="font-size:15px;letter-spacing:2px">{req.verification_code}</strong>
                <button class="btn btn-ghost btn-sm" style="margin-right:8px" on:click={() => openPreview(req.id)}>معاينة 🔍</button>
              </div>
              {#if req.notes}
                <div class="req-notes">📝 {req.notes}</div>
              {/if}

              {#if ['received','waiting','ready'].includes(req.status)}
                <div class="req-actions">
                  <!-- Reject — available for received and waiting only -->
                  {#if req.status !== 'ready'}
                    <button class="btn btn-danger btn-sm" style="margin-right:auto"
                      disabled={!!actionLoading[req.id]}
                      on:click={() => handleReject(req)}>
                      {#if actionLoading[req.id] === 'reject'}
                        <div class="spinner"></div>
                      {:else}
                        ✕ رفض
                      {/if}
                    </button>
                  {/if}

                  <!-- Step 1: received → print (needs code) -->
                  {#if req.status === 'received'}
                    <div class="verify-inputs">
                      {#each [0,1,2,3] as i}
                        <input
                          class="verify-box {verifyErrors[req.id] ? 'error' : ''} {(verifyInputs[req.id]||'').length === 4 && !verifyErrors[req.id] ? 'ok' : ''}"
                          maxlength="1" inputmode="numeric" type="text"
                          value={(verifyInputs[req.id] || '')[i] || ''}
                          on:input={e => {
                            const val = e.target.value.replace(/\D/g,'');
                            const arr = (verifyInputs[req.id] || '').split('');
                            arr[i] = val[0] || '';
                            verifyInputs[req.id] = arr.join('');
                            verifyErrors[req.id] = false;
                            if (val && e.target.nextElementSibling) e.target.nextElementSibling.focus();
                          }}
                          on:keydown={e => {
                            if (e.key === 'Backspace' && !e.target.value && e.target.previousElementSibling) {
                              e.target.previousElementSibling.focus();
                            } else if (e.key === 'Enter' && (verifyInputs[req.id]||'').length === 4) {
                              handlePrint(req);
                            }
                          }}
                        />
                      {/each}
                    </div>
                    <button class="btn btn-primary btn-sm" on:click={() => handlePrint(req)}
                      disabled={actionLoading[req.id] || (verifyInputs[req.id]||'').length < 4}>
                      {#if actionLoading[req.id] === 'print'}
                        <div class="spinner"></div>
                      {:else}
                        🖨️ طباعة
                      {/if}
                    </button>
                  {/if}

                  <!-- Step 2: waiting → ready (no code needed) -->
                  {#if req.status === 'waiting'}
                    <button class="btn btn-closed btn-sm" style="margin-right:auto"
                      disabled={!!actionLoading[req.id]}
                      on:click={() => handleReady(req)}>
                      {#if actionLoading[req.id] === 'ready'}
                        <div class="spinner"></div>
                      {:else}
                        ✅ جاهز للاستلام
                      {/if}
                    </button>
                  {/if}

                  <!-- Step 3: ready → deliver (needs code) -->
                  {#if req.status === 'ready'}
                    <div class="verify-inputs">
                      {#each [0,1,2,3] as i}
                        <input
                          class="verify-box {verifyErrors[req.id] ? 'error' : ''} {(verifyInputs[req.id]||'').length === 4 && !verifyErrors[req.id] ? 'ok' : ''}"
                          maxlength="1" inputmode="numeric" type="text"
                          value={(verifyInputs[req.id] || '')[i] || ''}
                          on:input={e => {
                            const val = e.target.value.replace(/\D/g,'');
                            const arr = (verifyInputs[req.id] || '').split('');
                            arr[i] = val[0] || '';
                            verifyInputs[req.id] = arr.join('');
                            verifyErrors[req.id] = false;
                            if (val && e.target.nextElementSibling) e.target.nextElementSibling.focus();
                          }}
                          on:keydown={e => {
                            if (e.key === 'Backspace' && !e.target.value && e.target.previousElementSibling) {
                              e.target.previousElementSibling.focus();
                            } else if (e.key === 'Enter' && (verifyInputs[req.id]||'').length === 4) {
                              handleDeliver(req);
                            }
                          }}
                        />
                      {/each}
                    </div>
                    <button class="btn btn-success btn-sm" on:click={() => handleDeliver(req)}
                      disabled={actionLoading[req.id] || (verifyInputs[req.id]||'').length < 4}>
                      {#if actionLoading[req.id] === 'deliver'}
                        <div class="spinner"></div>
                      {:else}
                        🎉 تم التسليم
                      {/if}
                    </button>
                  {/if}
                </div>
              {/if}
            </div>
          {/each}
        </div>

        <!-- Load More -->
        {#if hasMore}
          <div style="text-align:center;margin:16px 0">
            <button class="btn btn-ghost" on:click={loadMore} disabled={loadingMore}>
              {#if loadingMore}<div class="spinner" style="display:inline-block"></div>{:else}تحميل المزيد ({requestsTotal - requests.length} متبقي){/if}
            </button>
          </div>
        {/if}
      {/if}
      {/if}

      <!-- ── Students Section ────────────────────────────────────────── -->
      {#if activeSection === 'students'}
        <p class="section-title">الطلاب ({studentMap.length})</p>
        {#if studentMap.length === 0}
          <div class="empty"><div class="empty-icon">👥</div><div class="empty-msg">لا يوجد طلاب بعد</div></div>
        {:else}
          <div class="requests-list">
            {#each studentMap as s}
              <div class="card req-card">
                <div class="req-top">
                  <span class="badge badge-received">👤</span>
                  <div class="req-name-wrap">
                    <span class="req-name">{s.name}</span>
                    <span class="req-id">{s.hash.slice(0,12)}</span>
                  </div>
                  <span class="req-meta">{s.count} طلب</span>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {/if}

      <!-- ── Stats Section ───────────────────────────────────────────── -->
      {#if activeSection === 'stats'}
        <p class="section-title">الإحصاءات التفصيلية</p>
        <div class="stats-grid">
          <div class="card stat-card animate-up">
            <div class="stat-label">طلبات اليوم</div>
            <div class="stat-value">{Math.round($tw_total)}</div>
            <div class="stat-sub">📋 إجمالي</div>
          </div>
          <div class="card stat-card animate-up" style="animation-delay:60ms">
            <div class="stat-label">مكتملة اليوم</div>
            <div class="stat-value">{Math.round($tw_done)}</div>
            <div class="stat-sub">✅ تم التسليم</div>
          </div>
          <div class="card stat-card animate-up" style="animation-delay:120ms">
            <div class="stat-label">قيد الانتظار</div>
            <div class="stat-value">{Math.round($tw_pending)}</div>
            <div class="stat-sub">⏳ لم تُطبع بعد</div>
          </div>
          <div class="card stat-card animate-up" style="animation-delay:180ms">
            <div class="stat-label">صفحات اليوم</div>
            <div class="stat-value">{Math.round($tw_pages)}</div>
            <div class="stat-sub">📄 مجموع الصفحات</div>
          </div>
        </div>
        <div class="stats-grid" style="margin-top:12px">
          <div class="card stat-card animate-up">
            <div class="stat-label">طلبات نشطة</div>
            <div class="stat-value">{newActiveRequests.length}</div>
            <div class="stat-sub">📋 قيد المعالجة</div>
          </div>
          <div class="card stat-card animate-up" style="animation-delay:60ms">
            <div class="stat-label">إجمالي الطلاب</div>
            <div class="stat-value">{studentMap.length}</div>
            <div class="stat-sub">👥 طالب مختلف</div>
          </div>
          <div class="card stat-card animate-up" style="animation-delay:120ms">
            <div class="stat-label">معدّل الإنجاز</div>
            <div class="stat-value">{stats.today_total > 0 ? Math.round((stats.today_done / stats.today_total) * 100) : 0}%</div>
            <div class="stat-sub">📈 مكتملة / إجمالي</div>
          </div>
          <div class="card stat-card animate-up" style="animation-delay:180ms">
            <div class="stat-label">مرفوضة اليوم</div>
            <div class="stat-value">{requests.filter(r=>r.status==='rejected').length}</div>
            <div class="stat-sub">❌ مرفوضة</div>
          </div>
        </div>
        {#if disk}
          <div class="disk-bar card" style="margin-top:12px">
            <div class="disk-bar__header">
              <span>💾 المساحة المتبقية</span>
              <span class="disk-bar__nums">{disk.free_gb} GB حر من {disk.total_gb} GB</span>
            </div>
            <div class="disk-track">
              <div class="disk-fill {disk.warning ? 'warn' : ''}" style="width:{disk.pct_used}%"></div>
            </div>
          </div>
        {/if}
      {/if}

      <!-- ── Settings Section ────────────────────────────────────────── -->
      {#if activeSection === 'settings'}
        <p class="section-title">الإعدادات</p>

        <!-- Basic settings -->
        <div class="card" style="max-width:520px;padding:24px;display:flex;flex-direction:column;gap:16px;margin-bottom:12px">
          <p style="font-weight:700;font-size:14px;color:var(--text-secondary)">⚙️ الإعدادات الأساسية</p>
          <div>
            <div class="wiz-label">اسم المشغّل</div>
            <input class="wiz-input" bind:value={settingsForm.operator_name} placeholder="سعد" />
          </div>
          <div>
            <div class="wiz-label">اسم المكتبة</div>
            <input class="wiz-input" bind:value={settingsForm.library_name} placeholder="مكتبة جامعة الأنبار" />
          </div>
          <div>
            <div class="wiz-label">مسار مجلد الملفات</div>
            <input class="wiz-input" bind:value={settingsForm.library_path} placeholder="مثال: /Volumes/USB/Library" />
          </div>
          <div style="display:flex;gap:10px;align-items:center">
            <button class="btn btn-primary" on:click={saveSettings} disabled={settingsSaving}>
              {#if settingsSaving}<div class="spinner" style="display:inline-block"></div>{:else}💾 حفظ{/if}
            </button>
            {#if settingsSaved}<span style="color:var(--color-success);font-size:var(--text-sm)">✅ تم الحفظ</span>{/if}
          </div>
        </div>

        <!-- Schedule settings -->
        <div class="card" style="max-width:520px;padding:24px;display:flex;flex-direction:column;gap:14px;margin-bottom:12px">
          <p style="font-weight:700;font-size:14px;color:var(--text-secondary)">🕐 جدول الإغلاق التلقائي</p>
          <div style="display:flex;align-items:center;gap:10px">
            <input type="checkbox" id="sched-enabled" bind:checked={settingsForm.schedule_enabled} style="width:18px;height:18px;cursor:pointer" />
            <label for="sched-enabled" style="font-size:14px;cursor:pointer">تفعيل الإغلاق التلقائي حسب الجدول</label>
          </div>
          <div style="display:flex;gap:12px">
            <div style="flex:1">
              <div class="wiz-label">وقت الفتح</div>
              <input type="time" class="wiz-input" bind:value={settingsForm.open_time} />
            </div>
            <div style="flex:1">
              <div class="wiz-label">وقت الإغلاق</div>
              <input type="time" class="wiz-input" bind:value={settingsForm.close_time} />
            </div>
          </div>
          <div>
            <div class="wiz-label">رسالة الإغلاق</div>
            <input class="wiz-input" bind:value={settingsForm.close_message} placeholder="المكتبة مغلقة – يفتح الساعة 08:00" />
          </div>
          <div style="display:flex;gap:10px;align-items:center">
            <button class="btn btn-primary" on:click={saveSettings} disabled={settingsSaving}>
              {#if settingsSaving}<div class="spinner" style="display:inline-block"></div>{:else}💾 حفظ الجدول{/if}
            </button>
            {#if settingsSaved}<span style="color:var(--color-success);font-size:var(--text-sm)">✅ تم الحفظ</span>{/if}
          </div>
        </div>

        <!-- Retention settings -->
        <div class="card" style="max-width:520px;padding:24px;display:flex;flex-direction:column;gap:14px">
          <p style="font-weight:700;font-size:14px;color:var(--text-secondary)">🗑️ الأرشفة التلقائية</p>
          <div>
            <div class="wiz-label">احذف الطلبات المكتملة بعد (أيام)</div>
            <input type="number" class="wiz-input" bind:value={settingsForm.retention_days} min="1" max="365" placeholder="30" />
          </div>
          <p style="font-size:12px;color:var(--text-secondary)">⚠️ يحذف الملفات من القرص والقاعدة — يعمل كل يوم الساعة 3 صباحاً</p>
          <div style="display:flex;gap:10px;align-items:center">
            <button class="btn btn-primary" on:click={saveSettings} disabled={settingsSaving}>
              {#if settingsSaving}<div class="spinner" style="display:inline-block"></div>{:else}💾 حفظ{/if}
            </button>
            {#if settingsSaved}<span style="color:var(--color-success);font-size:var(--text-sm)">✅ تم الحفظ</span>{/if}
          </div>
        </div>
      {/if}

    </main>
  </div>
</div>

<!-- ── Setup Wizard ──────────────────────────────────────────────────────────── -->
{#if showWizard}
  <div class="wizard-backdrop" role="dialog" aria-modal="true" aria-label="إعداد UniPrint">
    <div class="wizard-card">
      <!-- Header -->
      <div class="wizard-header">
        <span class="wizard-logo">🖨️</span>
        <h2>إعداد UniPrint</h2>
        <p>خطوة {wizardStep} من 3</p>
        <div class="wizard-steps">
          {#each [1,2,3] as s}
            <div class="wiz-dot {wizardStep === s ? 'active' : ''} {wizardStep > s ? 'done' : ''}"></div>
          {/each}
        </div>
      </div>

      <!-- Step 1: Basic info -->
      {#if wizardStep === 1}
        <div class="wizard-body">
          <h3>معلومات المكتبة</h3>
          <p class="wiz-sub">سيظهر هذا الاسم للطلاب</p>
          <label class="wiz-label">اسم المكتبة</label>
          <input class="wiz-input" bind:value={wizardSettings.library_name} placeholder="مكتبة جامعة الأنبار" />
          <label class="wiz-label" style="margin-top:14px">اسم المشغّل</label>
          <input class="wiz-input" bind:value={wizardSettings.operator_name} placeholder="سعد" />
        </div>
        <div class="wizard-footer">
          <button class="btn btn-primary" on:click={() => wizardStep = 2}>التالي ←</button>
        </div>

      <!-- Step 2: Library path -->
      {:else if wizardStep === 2}
        <div class="wizard-body">
          <h3>مجلد الملفات</h3>
          <p class="wiz-sub">مسار المجلد الذي يحتوي ملفات القسم (اختياري)</p>
          <label class="wiz-label">المسار الكامل للمجلد</label>
          <input class="wiz-input" bind:value={wizardSettings.library_path}
            placeholder="مثال: C:\Library  أو  /Volumes/USB/Library" />
          {#if wizardSettings.library_path}
            <button class="btn btn-ghost btn-sm" style="margin-top:10px" on:click={wizardScan}
              disabled={wizardScanStatus === 'scanning'}>
              {wizardScanStatus === 'scanning' ? '⏳ جارٍ الفحص…' : wizardScanStatus === 'done' ? '✅ تم الفحص' : '🔍 فحص الملفات الآن'}
            </button>
          {/if}
          {#if wizardScanStatus === 'error'}<p style="color:var(--color-danger);font-size:var(--text-xs);margin-top:6px">المسار غير صحيح أو غير موجود</p>{/if}
        </div>
        <div class="wizard-footer">
          <button class="btn btn-ghost btn-sm" on:click={() => wizardStep = 1}>← رجوع</button>
          <button class="btn btn-primary" on:click={() => wizardStep = 3}>التالي ←</button>
        </div>

      <!-- Step 3: Done -->
      {:else if wizardStep === 3}
        <div class="wizard-body" style="text-align:center;padding-top:12px">
          <div style="font-size:52px;margin-bottom:12px">🎉</div>
          <h3>أنت جاهز!</h3>
          <p class="wiz-sub">UniPrint جاهز للعمل. يمكن تعديل الإعدادات لاحقاً من صفحة الإعدادات.</p>
          <div class="wiz-summary">
            <div>📚 <strong>{wizardSettings.library_name}</strong></div>
            <div>👤 <strong>{wizardSettings.operator_name}</strong></div>
            {#if wizardSettings.library_path}<div>📁 <strong>{wizardSettings.library_path}</strong></div>{/if}
          </div>
        </div>
        <div class="wizard-footer">
          <button class="btn btn-ghost btn-sm" on:click={() => wizardStep = 2}>← رجوع</button>
          <button class="btn btn-primary" on:click={finishWizard} disabled={wizardLoading}>
            {#if wizardLoading}<div class="spinner" style="display:inline-block"></div>{:else}✅ ابدأ{/if}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
