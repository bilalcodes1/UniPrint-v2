# UniPrint v2.0

نظام طباعة الجامعة الذكي — Library Print Management System

## Architecture

```
UniPrint/
├── backend/          Flask REST API + Socket.IO (port 5001)
├── frontend/         SvelteKit Dashboard (port 3000)
└── student-pages/    Student PWA (served via backend or any HTTP server)
    └── lan/          LAN version — served at http://uniprint.local:5001/student
```

## Quick Start

### Backend
```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python run.py
```

### Frontend (Dashboard)
```bash
cd frontend
npm install
npm run dev        # dev server on :3000
npm run build      # production build → build/
```

### Student LAN Page
Open `student-pages/lan/index.html` directly in a browser, or serve the folder:
```bash
cd student-pages
python3 -m http.server 8080
# Open http://localhost:8080/lan/
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET  | `/health` | Health check |
| POST | `/api/submit` | Submit print request (multipart) |
| GET  | `/api/status/<id>` | Get request status |
| POST | `/api/print/<id>` | Mark as printing |
| POST | `/api/deliver/<id>` | Mark as delivered |
| GET  | `/api/stats` | Dashboard stats |
| GET  | `/api/requests/recent` | Recent requests |
| GET  | `/api/requests/search` | Search requests |
| GET  | `/api/student/<hash>` | Student info |

## Socket.IO Events

| Event | Direction | Payload |
|-------|-----------|---------|
| `new_request` | Server → Client | `{request_id, student_name, verification_code, ...}` |
| `status_update` | Server → Client | `{request_id, status}` |

## File Limits
- Max **5 files** per request
- Max **20 MB** per file
- Allowed types: `pdf doc docx ppt pptx xls xlsx jpg jpeg png`
