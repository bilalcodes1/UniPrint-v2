const API_BASE = 'http://localhost:5001/api';
export const SOCKET_URL = 'http://localhost:5001';

// ── helpers ──────────────────────────────────────────────────────────────────
async function handleResponse(res) {
	const data = await res.json().catch(() => ({}));
	if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
	return data;
}

function get(path, params = {}) {
	const url = new URL(`${API_BASE}${path}`);
	Object.entries(params).forEach(([k, v]) => v !== undefined && url.searchParams.set(k, v));
	return fetch(url.toString(), { headers: { Accept: 'application/json' } }).then(handleResponse);
}

function post(path, body) {
	return fetch(`${API_BASE}${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(body),
	}).then(handleResponse);
}

function postForm(path, formData) {
	return fetch(`${API_BASE}${path}`, { method: 'POST', body: formData }).then(handleResponse);
}

// ── API client ────────────────────────────────────────────────────────────────
export const apiClient = {
	// Print requests
	submitRequest(data) {
		const fd = new FormData();
		Object.entries(data).forEach(([k, v]) => { if (k !== 'files') fd.append(k, v); });
		(data.files ?? []).forEach(f => fd.append('files', f));
		return postForm('/submit', fd);
	},

	getRequestStatus: (id)                  => get(`/status/${id}`),
	printRequest:    (id, verificationCode) => post(`/print/${id}`,   { verification_code: verificationCode }),
	markReady:       (id)                   => post(`/ready/${id}`,   {}),
	deliverRequest:  (id, verificationCode) => post(`/deliver/${id}`, { verification_code: verificationCode }),
	rejectRequest:   (id, reason)           => post(`/reject/${id}`,  { reason }),

	// Students
	getStudentInfo:  (hash)                 => get(`/student/${hash}`),
	getStudents:     (page = 1, limit = 20) => get('/students', { page, limit }),
	searchStudents:  (q)                    => get('/students/search', { q }),

	// Dashboard
	getStats:          ()                          => get('/stats'),
	getRecentRequests: (page = 1, perPage = 20)    => get('/requests/recent', { page, per_page: perPage }),
	searchRequests:    (q, status)                 => get('/requests/search', { q, status }),
	getRequest:        (id)                        => get(`/requests/${id}`),
	getRequestFiles:   (id)                        => get(`/requests/${id}/files`),

	// Rating
	saveRating: (id, rating)  => post(`/rating/${id}`, { rating }),

	// Settings & Setup
	getSettings:     ()       => get('/settings'),
	updateSettings:  (data)   => post('/settings', data),
	getSetupStatus:  ()       => get('/setup/status'),

	// Library
	getLibraryFiles:   (page = 1, perPage = 30, department = '', stage = '') =>
		get('/library/files', { page, per_page: perPage, department, stage }),
	searchLibrary:     (q)    => get('/library/search', { q }),
	scanLibrary:       (path) => post('/library/scan', path ? { path } : {}),
	getLibraryScanStatus: ()  => get('/library/scan/status'),

	// OCR
	extractNationalId(imageFile) {
		const fd = new FormData();
		fd.append('image', imageFile);
		return postForm('/extract-national-id', fd);
	},

	// System
	getSystemHealth: () => fetch('http://localhost:5001/health').then(handleResponse),
	getDiskInfo:      () => get('/disk'),
	getClosedState:   () => get('/closed'),
	setClosedState:   (closed, message) => post('/closed', { closed, message }),
};

export async function checkServerConnection() {
	try {
		await fetch('http://localhost:5001/health', { signal: AbortSignal.timeout(5000) });
		return true;
	} catch {
		return false;
	}
}

export default apiClient;
