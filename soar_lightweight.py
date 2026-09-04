import http.server
import socketserver
import json
import urllib.request
import urllib.error
import datetime
import os
import subprocess
import re
import threading
import secrets
from http import cookies

def _load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception as e:
            print("Warning: failed to read .env file:", e)

_load_env_file()

PORT = int(os.getenv('SOAR_PORT', 8080))
EVENTS_FILE = os.getenv('SOAR_EVENTS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'soar_events.json'))
ASSETS_FILE = os.getenv('SOAR_ASSETS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'protected_assets.json'))
SESSIONS_FILE = os.getenv('SOAR_SESSIONS_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'soar_sessions.json'))
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/api/generate')
AI_MODEL = os.getenv('SOAR_AI_MODEL', 'qwen2.5-coder:1.5b')
DEFAULT_TTL = int(os.getenv('DEFAULT_TTL', 86400))

ADMIN_USER = os.getenv('SOAR_ADMIN_USER', 'admin')
ADMIN_PASS = os.getenv('SOAR_ADMIN_PASS', 'admin123')
EXTRA_WHITELIST_IPS = set(ip.strip() for ip in os.getenv('SOAR_WHITELISTED_IPS', '').split(',') if ip.strip())
ARUSBALIK_SSH_HOST = os.getenv('ARUSBALIK_SSH_HOST', '10.88.0.1')
ARUSBALIK_SSH_USER = os.getenv('ARUSBALIK_SSH_USER', 'root')
ARUSBALIK_SSH_PASS = os.getenv('ARUSBALIK_SSH_PASS', '')

db_lock = threading.Lock()

def load_events():
    with db_lock:
        if os.path.exists(EVENTS_FILE):
            try:
                with open(EVENTS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

def save_events(events):
    with db_lock:
        try:
            with open(EVENTS_FILE, 'w') as f:
                json.dump(events, f, indent=2)
        except Exception as e:
            print("Gagal menyimpan event ke file:", e)

def load_assets():
    with db_lock:
        if os.path.exists(ASSETS_FILE):
            try:
                with open(ASSETS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

def save_assets(assets):
    with db_lock:
        try:
            with open(ASSETS_FILE, 'w') as f:
                json.dump(assets, f, indent=2)
        except Exception as e:
            print("Gagal menyimpan aset ke file:", e)

def load_sessions():
    with db_lock:
        if os.path.exists(SESSIONS_FILE):
            try:
                with open(SESSIONS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

def save_sessions(sessions):
    with db_lock:
        try:
            with open(SESSIONS_FILE, 'w') as f:
                json.dump(sessions, f, indent=2)
        except Exception as e:
            print("Gagal menyimpan sesi ke file:", e)

def is_authenticated(headers):
    cookie_str = headers.get('Cookie')
    if not cookie_str:
        return False
    try:
        c = cookies.SimpleCookie(cookie_str)
        if 'soar_session' not in c:
            return False
        token = c['soar_session'].value
        sessions = load_sessions()
        if token in sessions:
            expires_str = sessions[token].get('expires')
            if expires_str:
                expires = datetime.datetime.fromisoformat(expires_str)
                if datetime.datetime.now() < expires:
                    return True
        return False
    except Exception:
        return False

def get_asset_by_host_or_ip(host_or_ip):
    if not host_or_ip:
        return None
    needle = str(host_or_ip).lower().strip()
    assets = load_assets()
    for a in assets:
        if (a.get('hostname', '').lower() == needle or 
            a.get('name', '').lower() == needle or 
            a.get('wg_ip', '') == needle or
            a.get('id', '') == needle):
            return a
    return None

# --- FIREWALL MITIGATION ENGINE (DUAL-TIER O(1) IPSET: HOST + EDGE ARUSBALIK) ---
def block_ip_everywhere(attacker_ip, ttl=DEFAULT_TTL):
    if not attacker_ip or attacker_ip in ('0.0.0.0', '255.255.255.255') or not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', attacker_ip):
        return False
    if attacker_ip.startswith("127.") or attacker_ip in EXTRA_WHITELIST_IPS:
        return False
    
    # 1. Proxmox Host ipset (O(1) Kernel Hash Table)
    try:
        subprocess.run(["/usr/sbin/ipset", "add", "soar_host_blacklist", attacker_ip, "timeout", str(ttl), "-exist"], check=True)
    except Exception as e:
        print(f"Error adding to host ipset ({attacker_ip}):", e)

    # 2. ArusBalik Edge VPS (Gateway) - Non-blocking thread
    if ARUSBALIK_SSH_HOST and ARUSBALIK_SSH_PASS:
        def push_edge():
            try:
                cmd = f"ipset add soar_edge_blacklist {attacker_ip} timeout {ttl} -exist"
                subprocess.run([
                    "sshpass", "-p", ARUSBALIK_SSH_PASS, "ssh", 
                    "-o", "StrictHostKeyChecking=no", 
                    "-o", "ConnectTimeout=3", 
                    f"{ARUSBALIK_SSH_USER}@{ARUSBALIK_SSH_HOST}", cmd
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception as e:
                print(f"Error pushing {attacker_ip} to ArusBalik edge ipset:", e)

        t = threading.Thread(target=push_edge, daemon=True)
        t.start()
    return True

def unblock_ip_everywhere(attacker_ip):
    if not attacker_ip or attacker_ip in ('0.0.0.0', '255.255.255.255'):
        return False
    
    # 1. Hapus dari Proxmox Host ipset & iptables
    try:
        subprocess.run(["/usr/sbin/ipset", "del", "soar_host_blacklist", attacker_ip], stderr=subprocess.DEVNULL)
    except Exception:
        pass

    # 2. Hapus dari ArusBalik Edge VPS
    if ARUSBALIK_SSH_HOST and ARUSBALIK_SSH_PASS:
        def del_edge():
            try:
                cmd = f"ipset del soar_edge_blacklist {attacker_ip}"
                subprocess.run([
                    "sshpass", "-p", ARUSBALIK_SSH_PASS, "ssh", 
                    "-o", "StrictHostKeyChecking=no", 
                    "-o", "ConnectTimeout=3", 
                    f"{ARUSBALIK_SSH_USER}@{ARUSBALIK_SSH_HOST}", cmd
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception as e:
                print(f"Error removing {attacker_ip} from ArusBalik edge ipset:", e)

        t = threading.Thread(target=del_edge, daemon=True)
        t.start()
    return True

def get_active_blocked_ips():
    """Mengambil daftar IP terblokir aktif beserta sisa timeout (TTL) dari ipset Proxmox"""
    blocked_list = []
    try:
        res = subprocess.run(["/usr/sbin/ipset", "list", "soar_host_blacklist"], capture_output=True, text=True)
        if res.returncode == 0:
            matches = re.findall(r'(\d+\.\d+\.\d+\.\d+)\s+timeout\s+(\d+)', res.stdout)
            events = load_events()
            for ip, timeout_str in matches:
                matched_event = None
                for ev in reversed(events):
                    if ev.get('ip') == ip:
                        matched_event = ev
                        break
                
                timeout_sec = int(timeout_str)
                hours = timeout_sec // 3600
                minutes = (timeout_sec % 3600) // 60
                ttl_human = f"{hours}j {minutes}m lagi" if hours > 0 else f"{minutes}m lagi"

                blocked_list.append({
                    "ip": ip,
                    "ttl_seconds": timeout_sec,
                    "ttl_human": ttl_human,
                    "target_host": (matched_event.get('target_host_display') or matched_event.get('target_host')) if matched_event else "Semua Node",
                    "reason": matched_event.get('incident_type') if matched_event else "Mitigasi Otomatis SOAR",
                    "blocked_at": matched_event.get('timestamp') if matched_event else "Aktif"
                })
    except Exception as e:
        print("Error fetching ipset blocked list:", e)
    return blocked_list


LOGIN_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - Lightweight Cognitive SOAR</title>
    <link rel="icon" type="image/jpeg" href="/soar_logo.jpg">
    <link rel="shortcut icon" href="/favicon.ico">
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-gray-100 font-sans min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-gray-800 border border-gray-700 rounded-2xl shadow-2xl p-8 backdrop-blur-sm">
        <div class="text-center mb-8">
            <img src="/soar_logo.jpg" alt="UIN SOAR Logo" class="w-20 h-20 mx-auto rounded-2xl shadow-xl shadow-cyan-500/25 border-2 border-cyan-500/30 object-cover mb-4">
            <h1 class="text-2xl font-extrabold text-white tracking-tight">UIN Jakarta SOAR</h1>
            <p class="text-gray-400 text-xs mt-1.5 font-medium">Security Operations Center - Portal Autentikasi</p>
        </div>

        <div id="loginAlert" class="hidden mb-6 p-3 bg-red-950/60 border border-red-800 text-red-300 text-xs rounded-xl flex items-center">
            <span class="mr-2 text-base">⚠️</span>
            <span id="alertMsg">Username atau password tidak valid!</span>
        </div>

        <form id="loginForm" onsubmit="handleLogin(event)" class="space-y-5 text-sm">
            <div>
                <label class="block text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Username Administrator</label>
                <div class="relative">
                    <input type="text" id="username" required placeholder="Masukkan username" class="w-full px-4 py-3 bg-gray-900 border border-gray-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors">
                </div>
            </div>

            <div>
                <label class="block text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Password Akses</label>
                <div class="relative">
                    <input type="password" id="password" required placeholder="••••••••••••" class="w-full px-4 py-3 bg-gray-900 border border-gray-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors">
                </div>
            </div>

            <button type="submit" id="submitBtn" class="w-full py-3 px-4 bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white font-semibold rounded-xl shadow-lg shadow-indigo-500/25 transition-all duration-150 transform active:scale-95 flex items-center justify-center">
                <span>Masuk ke Konsol SOC</span>
                <span class="ml-2">🔐</span>
            </button>
        </form>

        <div class="mt-8 pt-6 border-t border-gray-700/60 text-center">
            <p class="text-xs text-gray-500 flex items-center justify-center">
                <span class="w-2 h-2 bg-green-500 rounded-full inline-block mr-2 animate-pulse"></span>
                Sistem Terproteksi Dual-Tier Kernel Edge Firewall
            </p>
        </div>
    </div>

    <script>
        function handleLogin(e) {
            e.preventDefault();
            const u = document.getElementById('username').value.trim();
            const p = document.getElementById('password').value.trim();
            const btn = document.getElementById('submitBtn');
            const alertBox = document.getElementById('loginAlert');
            const alertMsg = document.getElementById('alertMsg');

            btn.disabled = true;
            btn.innerHTML = '<span class="animate-spin mr-2">⏳</span> Memverifikasi...';

            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: u, password: p })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    window.location.href = '/';
                } else {
                    alertBox.classList.remove('hidden');
                    alertMsg.innerText = data.error || 'Username atau password salah!';
                    btn.disabled = false;
                    btn.innerHTML = '<span>Masuk ke Konsol SOC</span><span class="ml-2">🔐</span>';
                }
            })
            .catch(err => {
                alertBox.classList.remove('hidden');
                alertMsg.innerText = 'Koneksi gagal: ' + err;
                btn.disabled = false;
                btn.innerHTML = '<span>Masuk ke Konsol SOC</span><span class="ml-2">🔐</span>';
            });
        }
    </script>
</body>
</html>
"""


def _parse_llm_json(ai_raw, title, host):
    try:
        return json.loads(ai_raw)
    except Exception:
        repaired = ai_raw.strip()
        if repaired.count('"') % 2 != 0:
            repaired += '"'
        if not repaired.endswith('}'):
            repaired += '\n}'
        try:
            return json.loads(repaired)
        except Exception:
            m_summary = re.search(r'"analysis_summary"\s*:\s*"([^"]*)', ai_raw)
            m_detail = re.search(r'"detailed_analysis"\s*:\s*"([^"]*)', ai_raw)
            m_type = re.search(r'"incident_type"\s*:\s*"([^"]*)', ai_raw)
            return {
                "action": "block",
                "incident_type": m_type.group(1) if m_type else title,
                "analysis_summary": m_summary.group(1) if m_summary else f"Insiden {title} terdeteksi dan diblokir WAF pada host {host}.",
                "detailed_analysis": m_detail.group(1) if m_detail else ai_raw
            }

def run_background_analysis(ev_id, title, text, host, raw):
    try:
        prompt = (
            f"Host target: {host}\n"
            f"Kejadian: {title}\n"
            f"Log: {raw}\n\n"
            f"Keluarkan JSON valid (padat & ringkas Bahasa Indonesia):\n"
            f'{{\n'
            f'  "action": "block",\n'
            f'  "incident_type": "Tipe Serangan Spesifik",\n'
            f'  "analysis_summary": "1 kalimat ringkasan kejadian",\n'
            f'  "detailed_analysis": "Penyebab & mitigasi singkat"\n'
            f'}}'
        )
        ollama_payload = {
            "model": AI_MODEL,
            "system": "Anda adalah AI Analis SOC. Jawab selalu dalam JSON ringkas Bahasa Indonesia. Setiap nilai teks maksimal 1 kalimat pendek padat.",
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {
                "num_predict": 140,
                "temperature": 0.1
            },
            "keep_alive": "24h"
        }
        req = urllib.request.Request(
            OLLAMA_URL, 
            data=json.dumps(ollama_payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            ai_raw_response = res_json.get('response', '').strip()
        
        ai_data = _parse_llm_json(ai_raw_response, title, host)
        analysis_summary = ai_data.get('analysis_summary') or ai_data.get('analysis') or ai_data.get('summary') or 'Analisis selesai.'
        detailed_analysis_raw = ai_data.get('detailed_analysis') or 'Analisis rinci tidak tersedia.'
        
        if isinstance(detailed_analysis_raw, dict):
            lines = []
            labels = {
                "server_targeted": "Target Server",
                "reason_blocked": "Alasan Blokir",
                "exploited_vulnerability": "Kerentanan yang Dieksploitasi",
                "threat_behaviour": "Perilaku Ancaman",
                "recommended_next_steps": "Rekomendasi Tindakan & Mitigasi"
            }
            for k, v in detailed_analysis_raw.items():
                label = labels.get(k, k.replace('_', ' ').title())
                val = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                lines.append(f"• {label}:\n  {val}")
            detailed_analysis = "\n\n".join(lines)
        elif isinstance(detailed_analysis_raw, list):
            detailed_analysis = "\n".join(f"• {item}" for item in detailed_analysis_raw)
        else:
            detailed_analysis = str(detailed_analysis_raw)

        incident_type_ai = ai_data.get('incident_type') or title
        
        current_events = load_events()
        for ev in current_events:
            if ev.get("id") == ev_id:
                ev["analysis"] = analysis_summary
                ev["detailed_analysis"] = detailed_analysis
                ev["incident_type"] = incident_type_ai
                break
        save_events(current_events)
    except Exception as e:
        print("Error background LLM:", e)
        try:
            current_events = load_events()
            for ev in current_events:
                if ev.get("id") == ev_id and not ev.get("analysis"):
                    ev["analysis"] = f"Proteksi aktif: Insiden '{title}' pada {host} berhasil dicegah."
                    ev["detailed_analysis"] = f"• Target: {host}\n• Status: Diblokir oleh aturan mitigasi otomatis\n• Rekomendasi: Evaluasi log keamanan di server terkait"
                    break
            save_events(current_events)
        except Exception:
            pass


class LightweightSOARHandler(http.server.BaseHTTPRequestHandler):

    def do_HEAD(self):
        if self.path in ['/favicon.ico', '/favicon.png', '/soar_logo.jpg']:
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()

    def do_GET(self):
        # 1. Aset Publik Statis (Favicon & Logo)
        if self.path in ['/favicon.ico', '/favicon.png', '/soar_logo.jpg']:
            logo_path = '/root/riset/soar_logo.jpg'
            if os.path.exists(logo_path):
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                with open(logo_path, 'rb') as img_f:
                    self.wfile.write(img_f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        # 2. Halaman Login
        elif self.path == '/login':
            if is_authenticated(self.headers):
                self.send_response(302)
                self.send_header('Location', '/')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(LOGIN_HTML.encode('utf-8'))
            return

        # 3. Logout Endpoint
        elif self.path == '/logout':
            cookie_str = self.headers.get('Cookie')
            if cookie_str:
                try:
                    c = cookies.SimpleCookie(cookie_str)
                    if 'soar_session' in c:
                        token = c['soar_session'].value
                        sessions = load_sessions()
                        if token in sessions:
                            del sessions[token]
                            save_sessions(sessions)
                except Exception:
                    pass

            self.send_response(302)
            self.send_header('Set-Cookie', 'soar_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')
            self.send_header('Location', '/login')
            self.end_headers()
            return

        # 4. API Endpoints (Memerlukan Autentikasi)
        elif self.path == '/api/events':
            if not is_authenticated(self.headers):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode('utf-8'))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            events = load_events()
            self.wfile.write(json.dumps(events).encode('utf-8'))
            return

        elif self.path == '/api/assets':
            if not is_authenticated(self.headers):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode('utf-8'))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            assets = load_assets()
            self.wfile.write(json.dumps(assets).encode('utf-8'))
            return

        elif self.path == '/api/blocked':
            if not is_authenticated(self.headers):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode('utf-8'))
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            blocked_ips = get_active_blocked_ips()
            self.wfile.write(json.dumps(blocked_ips).encode('utf-8'))
            return

        # 5. Halaman Utama Dasbor (Memerlukan Autentikasi)
        elif self.path == '/' or self.path == '/index.html':
            if not is_authenticated(self.headers):
                self.send_response(302)
                self.send_header('Location', '/login')
                self.end_headers()
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()

            html_content = """<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lightweight Cognitive SOAR - Dashboard</title>
    <link rel="icon" type="image/jpeg" href="/soar_logo.jpg">
    <link rel="shortcut icon" href="/favicon.ico">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-gray-900 text-gray-100 font-sans min-h-screen">
    <div class="container mx-auto px-4 py-8">
        
        <!-- Header -->
        <div class="flex flex-col md:flex-row md:items-center justify-between border-b border-gray-800 pb-6 mb-8">
            <div>
                <h1 class="text-3xl font-extrabold tracking-tight text-white flex items-center">
                    <img src="/soar_logo.jpg" alt="UIN SOAR Logo" class="w-11 h-11 rounded-xl mr-3 shadow-lg shadow-cyan-500/25 object-cover border border-cyan-500/30">
                    Lightweight Agentic SOAR
                </h1>
                <p class="text-gray-400 mt-2 text-sm md:text-base">Sistem Orkestrasi Keamanan Siber Terintegrasi berbasis LLM Lokal (Ollama) & Edge Mitigation (ArusBalik)</p>
            </div>
            <div class="mt-4 md:mt-0 flex items-center space-x-3">
                <div class="flex items-center bg-gray-800 border border-gray-700 px-4 py-2 rounded-lg text-sm text-cyan-400 font-mono shadow-inner">
                    <span class="w-3 h-3 bg-green-500 rounded-full inline-block mr-2.5 animate-pulse"></span>
                    Dual-Tier Edge Defense (O(1))
                </div>
                <!-- User Profile & Logout -->
                <div class="flex items-center space-x-2 bg-gray-800 border border-gray-700 px-3 py-1.5 rounded-lg text-xs text-gray-300">
                    <span class="font-semibold text-indigo-400">👤 admin</span>
                    <span class="text-gray-600">|</span>
                    <a href="/logout" class="text-red-400 hover:text-red-300 font-semibold transition-colors">Keluar</a>
                </div>
            </div>
        </div>

        <!-- Statistik Dinamis -->
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-md">
                <p class="text-sm text-gray-400 font-medium">Total Insiden Teranalisis</p>
                <p id="statTotal" class="text-3xl font-bold text-white mt-2">0</p>
            </div>
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-md">
                <p class="text-sm text-gray-400 font-medium">Node Terlindungi (VM/Aset)</p>
                <p id="statAssets" class="text-3xl font-bold text-cyan-400 mt-2">0</p>
            </div>
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-md">
                <p class="text-sm text-gray-400 font-medium">IP Terblokir Aktif (Edge + Host)</p>
                <p id="statBlockedActive" class="text-3xl font-bold text-red-500 mt-2">0</p>
            </div>
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-md">
                <p class="text-sm text-gray-400 font-medium">Aktivitas Diabaikan (Normal)</p>
                <p id="statIgnore" class="text-3xl font-bold text-green-400 mt-2">0</p>
            </div>
        </div>

        <!-- Tab Navigasi 4 Fitur -->
        <div class="flex flex-wrap gap-2 border-b border-gray-700 mb-6">
            <button id="tabEventsBtn" onclick="switchTab('events')" class="px-5 py-3 font-semibold text-sm border-b-2 border-indigo-500 text-indigo-400 flex items-center space-x-2 transition-all">
                <span>⚡ Log Triase Insiden</span>
                <span id="badgeEventCount" class="bg-indigo-900/60 text-indigo-300 text-xs px-2 py-0.5 rounded-full font-mono">0</span>
            </button>
            <button id="tabBlockedBtn" onclick="switchTab('blocked')" class="px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all">
                <span>🚫 Manajemen Blokir (TTL & Unblock)</span>
                <span id="badgeBlockedCount" class="bg-red-950 text-red-400 text-xs px-2 py-0.5 rounded-full font-mono border border-red-900/50">0</span>
            </button>
            <button id="tabChartsBtn" onclick="switchTab('charts')" class="px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all">
                <span>📊 Visualisasi & Analitik (Chart.js)</span>
            </button>
            <button id="tabAssetsBtn" onclick="switchTab('assets')" class="px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all">
                <span>🛡️ Inventaris Node & IP</span>
                <span id="badgeAssetCount" class="bg-gray-800 text-gray-300 text-xs px-2 py-0.5 rounded-full font-mono">0</span>
            </button>
        </div>

        <!-- VIEW 1: TABEL LOG SERANGAN (TRIAGE REAL-TIME) -->
        <div id="tabEventsView" class="space-y-4">
            <div class="bg-gray-800 rounded-xl border border-gray-700 shadow-xl overflow-hidden">
                <div class="px-6 py-4 border-b border-gray-700 bg-gray-850 flex items-center justify-between">
                    <div>
                        <h2 class="text-lg font-semibold text-white">Log Aktivitas Triase Kognitif Real-Time</h2>
                        <p class="text-xs text-indigo-400 mt-0.5">💡 Klik pada baris tabel untuk melihat rincian laporan mendalam AI, fakta log, & status mitigasi</p>
                    </div>
                    <div class="flex items-center space-x-2">
                        <span class="w-2 h-2 bg-indigo-500 rounded-full animate-ping"></span>
                        <span class="text-xs text-gray-400">Pembaruan otomatis aktif</span>
                    </div>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead class="bg-gray-900/50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Waktu</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Tipe Serangan</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Server Sasaran (Target)</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">IP Asal Penyerang</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Tindakan</th>
                            </tr>
                        </thead>
                        <tbody id="tableBody" class="divide-y divide-gray-700 bg-gray-800">
                            <!-- Baris diisi oleh JS -->
                        </tbody>
                    </table>
                </div>
                
                <!-- Kontrol Pagination -->
                <div class="px-6 py-4 border-t border-gray-700 bg-gray-900/30 flex items-center justify-between">
                    <div class="text-sm text-gray-400">
                        Menampilkan <span id="pageStart" class="font-semibold text-white">0</span> sampai <span id="pageEnd" class="font-semibold text-white">0</span> dari <span id="totalItems" class="font-semibold text-white">0</span> log
                    </div>
                    <div class="flex space-x-3">
                        <button id="prevBtn" onclick="changePage(-1)" class="px-4 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed border border-gray-700 rounded-lg text-sm font-semibold transition-all duration-150">Sebelumnya</button>
                        <button id="nextBtn" onclick="changePage(1)" class="px-4 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed border border-gray-700 rounded-lg text-sm font-semibold transition-all duration-150">Selanjutnya</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- VIEW 2: MANAJEMEN BLOKIR (TTL & UNBLOCK) -->
        <div id="tabBlockedView" class="hidden space-y-4">
            <div class="bg-gray-800 rounded-xl border border-gray-700 shadow-xl overflow-hidden">
                <div class="px-6 py-4 border-b border-gray-700 bg-gray-850 flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                        <h2 class="text-lg font-semibold text-white flex items-center">
                            <span>🚫 Daftar IP Terblokir Aktif (Edge + Host Kernel Hash)</span>
                        </h2>
                        <p class="text-xs text-red-400 mt-0.5">Semua IP di bawah ini di-DROP secara O(1) di Edge Gateway ArusBalik dan Proxmox Host</p>
                    </div>
                    <div>
                        <button onclick="fetchBlockedFromDB()" class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-xs text-gray-200 rounded-lg transition-all">
                            🔄 Refresh Daftar
                        </button>
                    </div>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead class="bg-gray-900/50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">IP Penyerang</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Node Sasaran</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Alasan Pemblokiran</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Sisa Waktu (TTL Kernel)</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Aksi Interaktif</th>
                            </tr>
                        </thead>
                        <tbody id="blockedTableBody" class="divide-y divide-gray-700 bg-gray-800">
                            <!-- Diisi oleh JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- VIEW 3: VISUALISASI GRAFIK STATISTIK (CHART.JS) -->
        <div id="tabChartsView" class="hidden space-y-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Chart 1: Distribusi Serangan -->
                <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-xl">
                    <h3 class="text-base font-bold text-white mb-1 flex items-center">
                        <span class="mr-2">🍩</span> Distribusi Kategori Ancaman
                    </h3>
                    <p class="text-xs text-gray-400 mb-4">Persentase jenis eksploitasi yang dideteksi SIEM & SOAR</p>
                    <div class="relative h-64 flex items-center justify-center">
                        <canvas id="chartThreatTypes"></canvas>
                    </div>
                </div>

                <!-- Chart 2: Sasaran Target Paling Sering Diserang -->
                <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-xl">
                    <h3 class="text-base font-bold text-white mb-1 flex items-center">
                        <span class="mr-2">🎯</span> Frekuensi Serangan per Node Sasaran
                    </h3>
                    <p class="text-xs text-gray-400 mb-4">Node VM yang paling intensif menjadi target serangan siber</p>
                    <div class="relative h-64 flex items-center justify-center">
                        <canvas id="chartTargetNodes"></canvas>
                    </div>
                </div>
            </div>

            <!-- Chart 3: Tren Insiden Waktu Nyata -->
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-xl">
                <h3 class="text-base font-bold text-white mb-1 flex items-center">
                    <span class="mr-2">📈</span> Tren Garis Waktu Insiden
                </h3>
                <p class="text-xs text-gray-400 mb-4">Histori eskalasi dan volume serangan siber yang diproses SOAR</p>
                <div class="relative h-64">
                    <canvas id="chartTimeline"></canvas>
                </div>
            </div>
        </div>

        <!-- VIEW 4: TABEL INVENTARIS NODE TERLINDUNGI -->
        <div id="tabAssetsView" class="hidden space-y-4">
            <div class="bg-gray-800 rounded-xl border border-gray-700 shadow-xl overflow-hidden">
                <div class="px-6 py-4 border-b border-gray-700 bg-gray-850 flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                        <h2 class="text-lg font-semibold text-white flex items-center">
                            <span>🛡️ Topologi & Node Terlindungi (Protected Assets)</span>
                        </h2>
                        <p class="text-xs text-cyan-400 mt-0.5">Pemetaan dinamis seluruh VM Proxmox & VPS Gateway yang diproteksi oleh SIEM Wazuh & SOAR</p>
                    </div>
                    <div>
                        <button onclick="openAddAssetModal()" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold flex items-center shadow-lg shadow-indigo-600/30 transition-all">
                            <span class="mr-1.5 font-bold">+</span> Daftarkan Node / IP Baru
                        </button>
                    </div>
                </div>
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-700">
                        <thead class="bg-gray-900/50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Node / Hostname</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Nama & Peran Server</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">IP WireGuard (wg0)</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">IP LAN (ens18)</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Layanan Terkait</th>
                                <th class="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Status</th>
                            </tr>
                        </thead>
                        <tbody id="assetsTableBody" class="divide-y divide-gray-700 bg-gray-800">
                            <!-- Diisi oleh JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

    </div>

    <!-- MODAL POPUP LAPORAN DETAIL & FORENSIK INCIDENT -->
    <div id="incidentModal" class="fixed inset-0 z-50 hidden bg-black/80 flex items-center justify-center p-4 backdrop-blur-sm transition-opacity duration-300">
        <div class="bg-gray-800 border border-gray-700 rounded-2xl max-w-3xl w-full max-h-[85vh] overflow-hidden shadow-2xl flex flex-col transform scale-95 transition-transform duration-200">
            <!-- Modal Header -->
            <div class="px-6 py-4 border-b border-gray-700 bg-gray-900/50 flex justify-between items-center">
                <h3 class="text-xl font-bold text-white flex items-center">
                    <span class="mr-2">🛡️</span> Laporan Kognitif & Forensik Siber
                </h3>
                <button onclick="closeModal()" class="text-gray-400 hover:text-white transition-colors duration-150 text-2xl font-bold">&times;</button>
            </div>
            <!-- Modal Content -->
            <div class="p-6 overflow-y-auto space-y-6 text-sm text-gray-300 leading-relaxed">
                <!-- Meta Info Grid -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 bg-gray-900/40 p-4 rounded-xl border border-gray-700/50">
                    <div>
                        <p class="text-xs text-gray-400 font-semibold uppercase tracking-wider">Server Korban (Target Host)</p>
                        <p id="modalTargetHost" class="text-base font-bold text-indigo-400 mt-0.5">-</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400 font-semibold uppercase tracking-wider">IP Penyerang (Source IP)</p>
                        <p id="modalIp" class="text-base font-mono font-bold text-red-400 mt-0.5">-</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400 font-semibold uppercase tracking-wider">Waktu Deteksi</p>
                        <p id="modalTimestamp" class="text-base text-gray-200 mt-0.5">-</p>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400 font-semibold uppercase tracking-wider">Status Mitigasi</p>
                        <p id="modalMitigation" class="text-base text-green-400 font-semibold mt-0.5">-</p>
                    </div>
                </div>

                <!-- Info Topologi Target Korban -->
                <div id="modalAssetDetails" class="bg-gray-900/60 p-4 rounded-xl border border-indigo-900/40 space-y-2">
                    <p class="text-xs text-indigo-400 font-bold uppercase tracking-wider">📍 Detail Topologi Node Korban</p>
                    <div class="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
                        <div>
                            <span class="text-gray-400">IP WireGuard:</span>
                            <span id="modalTargetWg" class="font-mono text-cyan-300 font-semibold ml-1">-</span>
                        </div>
                        <div>
                            <span class="text-gray-400">IP LAN Proxmox:</span>
                            <span id="modalTargetLan" class="font-mono text-emerald-300 font-semibold ml-1">-</span>
                        </div>
                        <div class="col-span-2 md:col-span-1">
                            <span class="text-gray-400">Layanan:</span>
                            <span id="modalTargetService" class="text-gray-200 ml-1">-</span>
                        </div>
                    </div>
                </div>

                <!-- Triage Decision badge -->
                <div class="flex items-center space-x-2.5">
                    <span class="text-gray-400 font-semibold">Keputusan Keamanan AI:</span>
                    <span id="modalActionBadge" class="px-3 py-1 rounded-full text-xs font-bold uppercase border">-</span>
                </div>

                <!-- Payload / Log Mentah (Forensik) -->
                <div>
                    <h4 class="text-xs text-gray-400 font-bold uppercase tracking-wider mb-2">Fakta Serangan / Log Mentah (Payload Forensik)</h4>
                    <pre id="modalRawLog" class="bg-gray-900 border border-gray-700/50 p-4 rounded-xl text-red-300 font-mono text-xs overflow-x-auto whitespace-pre-wrap max-h-40 leading-normal">-</pre>
                </div>

                <!-- Ringkasan Singkat (Hasil Analisis) -->
                <div>
                    <h4 class="text-xs text-gray-400 font-bold uppercase tracking-wider mb-2">Hasil Analisis (Ringkasan Kognitif)</h4>
                    <p id="modalAnalysis" class="bg-gray-900/30 border border-gray-700/50 p-4 rounded-xl text-gray-200">-</p>
                </div>

                <!-- Laporan Kognitif Mendalam (Detailed AI Reasoning) -->
                <div>
                    <h4 class="text-xs text-gray-400 font-bold uppercase tracking-wider mb-2">Laporan Forensik AI Mendalam (Llama 3.2 Cognitive Reasoning)</h4>
                    <div id="modalDetailedAnalysis" class="bg-gray-900/50 border border-indigo-900/30 p-4 rounded-xl text-indigo-200 text-xs md:text-sm font-mono whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">-</div>
                </div>
            </div>
            <!-- Modal Footer -->
            <div class="px-6 py-4 border-t border-gray-700 bg-gray-900/50 flex justify-end">
                <button onclick="closeModal()" class="px-5 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm font-medium transition-colors duration-150">Tutup Laporan</button>
            </div>
        </div>
    </div>

    <!-- MODAL TAMBAH NODE / ASET BARU -->
    <div id="addAssetModal" class="fixed inset-0 z-50 hidden bg-black/80 flex items-center justify-center p-4 backdrop-blur-sm">
        <div class="bg-gray-800 border border-gray-700 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl p-6">
            <div class="flex justify-between items-center pb-3 border-b border-gray-700 mb-4">
                <h3 class="text-lg font-bold text-white flex items-center">
                    <span class="mr-2">➕</span> Daftarkan Node Terlindungi
                </h3>
                <button onclick="closeAddAssetModal()" class="text-gray-400 hover:text-white text-xl font-bold">&times;</button>
            </div>
            <form id="addAssetForm" onsubmit="submitNewAsset(event)" class="space-y-4 text-sm">
                <div>
                    <label class="block text-gray-400 text-xs font-semibold mb-1">Hostname / ID Agent Wazuh</label>
                    <input type="text" id="inputHostname" required placeholder="misal: siakad atau vm-111" class="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white font-mono focus:border-indigo-500 focus:outline-none">
                </div>
                <div>
                    <label class="block text-gray-400 text-xs font-semibold mb-1">Nama Layanan & Deskripsi</label>
                    <input type="text" id="inputName" required placeholder="misal: VM (111) - Sistem SIAKAD" class="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-indigo-500 focus:outline-none">
                </div>
                <div>
                    <label class="block text-gray-400 text-xs font-semibold mb-1">IP WireGuard (wg0)</label>
                    <input type="text" id="inputWgIp" required placeholder="misal: 10.88.0.17" class="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white font-mono focus:border-indigo-500 focus:outline-none">
                </div>
                <div>
                    <label class="block text-gray-400 text-xs font-semibold mb-1">IP LAN Lokal Proxmox (ens18)</label>
                    <input type="text" id="inputLanIp" placeholder="misal: 172.20.32.99 (Opsional)" class="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white font-mono focus:border-indigo-500 focus:outline-none">
                </div>
                <div>
                    <label class="block text-gray-400 text-xs font-semibold mb-1">Layanan / Domain Publik</label>
                    <input type="text" id="inputServices" placeholder="misal: siakad.uinjakarta.id, Nginx" class="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white focus:border-indigo-500 focus:outline-none">
                </div>
                <div class="flex justify-end space-x-3 pt-3 border-t border-gray-700">
                    <button type="button" onclick="closeAddAssetModal()" class="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm">Batal</button>
                    <button type="submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm font-semibold">Simpan Node</button>
                </div>
            </form>
        </div>
    </div>

    <!-- JAVASCRIPT SPA & CHARTS LOGIC -->
    <script>
        let eventsData = [];
        let assetsData = [];
        let blockedData = [];
        let currentPage = 1;
        const ITEMS_PER_PAGE = 8;
        let isModalOpen = false;
        let activeTab = 'events';

        let chart1Instance = null;
        let chart2Instance = null;
        let chart3Instance = null;

        function switchTab(tab) {
            activeTab = tab;
            const tabs = ['events', 'blocked', 'charts', 'assets'];
            tabs.forEach(t => {
                const btn = document.getElementById(`tab${t.charAt(0).toUpperCase() + t.slice(1)}Btn`);
                const view = document.getElementById(`tab${t.charAt(0).toUpperCase() + t.slice(1)}View`);
                if (t === tab) {
                    btn.className = "px-5 py-3 font-semibold text-sm border-b-2 border-indigo-500 text-indigo-400 flex items-center space-x-2 transition-all";
                    view.classList.remove('hidden');
                } else {
                    btn.className = "px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all";
                    view.classList.add('hidden');
                }
            });

            if (tab === 'charts') {
                renderAllCharts();
            } else if (tab === 'blocked') {
                fetchBlockedFromDB();
            } else if (tab === 'assets') {
                fetchAssetsFromDB();
            }
        }

        function fetchEventsFromDB() {
            fetch('/api/events')
                .then(res => {
                    if (res.status === 401) { window.location.href = '/login'; return []; }
                    return res.json();
                })
                .then(data => {
                    eventsData = data;
                    document.getElementById('badgeEventCount').innerText = eventsData.length;
                    updateStats();
                    renderTablePage();
                    if (activeTab === 'charts') renderAllCharts();
                })
                .catch(err => console.error("Gagal menarik data log:", err));
        }

        function fetchAssetsFromDB() {
            fetch('/api/assets')
                .then(res => {
                    if (res.status === 401) { window.location.href = '/login'; return []; }
                    return res.json();
                })
                .then(data => {
                    assetsData = data;
                    document.getElementById('statAssets').innerText = assetsData.length;
                    document.getElementById('badgeAssetCount').innerText = assetsData.length;
                    renderAssetsTable();
                })
                .catch(err => console.error("Gagal menarik data aset:", err));
        }

        function fetchBlockedFromDB() {
            fetch('/api/blocked')
                .then(res => {
                    if (res.status === 401) { window.location.href = '/login'; return []; }
                    return res.json();
                })
                .then(data => {
                    blockedData = data;
                    document.getElementById('statBlockedActive').innerText = blockedData.length;
                    document.getElementById('badgeBlockedCount').innerText = blockedData.length;
                    renderBlockedTable();
                })
                .catch(err => console.error("Gagal menarik data blacklist:", err));
        }

        function updateStats() {
            let total = eventsData.length;
            let ignoreCount = 0;
            eventsData.forEach(ev => {
                if (ev.action === 'ignore') ignoreCount++;
            });
            document.getElementById('statTotal').innerText = total;
            document.getElementById('statIgnore').innerText = ignoreCount;
        }

        function renderTablePage() {
            const tbody = document.getElementById('tableBody');
            tbody.innerHTML = '';

            const total = eventsData.length;
            const totalPages = Math.ceil(total / ITEMS_PER_PAGE) || 1;
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;

            const reversed = [...eventsData].reverse();
            const startIdx = (currentPage - 1) * ITEMS_PER_PAGE;
            const endIdx = Math.min(startIdx + ITEMS_PER_PAGE, total);
            const paginatedEvents = reversed.slice(startIdx, endIdx);

            if (paginatedEvents.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-8 text-center text-sm text-gray-500">Belum ada aktivitas ancaman siber yang tercatat.</td></tr>`;
                updatePaginationControls(0, 0, 0);
                return;
            }

            paginatedEvents.forEach((ev, displayIdx) => {
                const originalIndex = total - 1 - (startIdx + displayIdx);
                const badgeColor = ev.action === 'block' 
                    ? "bg-red-950/40 text-red-400 border border-red-900/50" 
                    : "bg-green-950/40 text-green-400 border border-green-900/50";

                const targetDisplay = ev.target_host_display || ev.target_host || 'Local Host';

                const tr = document.createElement('tr');
                tr.className = "hover:bg-gray-700/40 transition-colors duration-150 cursor-pointer";
                tr.setAttribute('onclick', `showEventDetails(${originalIndex})`);

                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-400">${ev.timestamp || ''}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-semibold text-gray-100">${ev.incident_type || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-cyan-400 font-medium">
                        ${targetDisplay}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-red-400 font-mono">${ev.ip || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold ${badgeColor}">
                            ${(ev.action || 'ignore').toUpperCase()}
                        </span>
                    </td>
                `;
                tbody.appendChild(tr);
            });

            updatePaginationControls(startIdx + 1, endIdx, total);
        }

        function renderBlockedTable() {
            const tbody = document.getElementById('blockedTableBody');
            tbody.innerHTML = '';

            if (blockedData.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="px-6 py-8 text-center text-sm text-emerald-400 font-medium">✨ Tidak ada IP yang sedang terblokir saat ini (Tabel firewall bersih).</td></tr>`;
                return;
            }

            blockedData.forEach(item => {
                const tr = document.createElement('tr');
                tr.className = "hover:bg-gray-700/40 transition-colors duration-150";
                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-mono font-bold text-red-400">${item.ip}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-cyan-300 font-medium">${item.target_host}</td>
                    <td class="px-6 py-4 text-sm text-gray-300">${item.reason}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        <span class="px-2.5 py-1 rounded-md text-xs font-mono font-semibold bg-amber-950/40 text-amber-300 border border-amber-900/50">
                            ⏱️ ${item.ttl_human}
                        </span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        <button onclick="unblockIp('${item.ip}')" class="px-3.5 py-1.5 bg-amber-600/80 hover:bg-amber-500 text-white rounded-lg text-xs font-semibold shadow-md shadow-amber-600/20 transition-all flex items-center">
                            <span class="mr-1">🔓</span> Unblock Sekarang
                        </button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function unblockIp(ip) {
            if (!confirm(`Konfirmasi: Apakah Anda yakin ingin melepas pemblokiran IP ${ip} dari Edge Gateway & Proxmox?`)) {
                return;
            }

            fetch('/api/unblock', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ip: ip })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert(`IP ${ip} berhasil dilepas dari daftar blokir!`);
                    fetchBlockedFromDB();
                } else {
                    alert("Gagal unblock: " + (data.error || "Terjadi kesalahan"));
                }
            })
            .catch(err => alert("Koneksi gagal: " + err));
        }

        function renderAssetsTable() {
            const tbody = document.getElementById('assetsTableBody');
            tbody.innerHTML = '';

            if (assetsData.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="px-6 py-8 text-center text-sm text-gray-500">Belum ada aset node yang didaftarkan.</td></tr>`;
                return;
            }

            assetsData.forEach(asset => {
                const tr = document.createElement('tr');
                tr.className = "hover:bg-gray-700/40 transition-colors duration-150";
                tr.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-mono font-bold text-indigo-400">${asset.hostname}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-200">${asset.name}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-cyan-400 font-semibold">${asset.wg_ip}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-mono text-emerald-400">${asset.lan_ip || '-'}</td>
                    <td class="px-6 py-4 text-sm text-gray-300">${asset.services || '-'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        <span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-950/40 text-emerald-400 border border-emerald-900/50">
                            TERLINDUNGI
                        </span>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }

        function renderAllCharts() {
            const threatCounts = {};
            const targetCounts = {};
            const timelineCounts = {};

            eventsData.forEach(ev => {
                const type = ev.incident_type || 'Kejadian Umum';
                threatCounts[type] = (threatCounts[type] || 0) + 1;

                const host = ev.target_host_display || ev.target_host || 'Local Host';
                targetCounts[host] = (targetCounts[host] || 0) + 1;

                const dateStr = (ev.timestamp || '').split(' ')[0] || 'Unknown';
                timelineCounts[dateStr] = (timelineCounts[dateStr] || 0) + 1;
            });

            // 1. Threat Types Donut Chart
            const ctx1 = document.getElementById('chartThreatTypes');
            if (ctx1) {
                if (chart1Instance) chart1Instance.destroy();
                chart1Instance = new Chart(ctx1, {
                    type: 'doughnut',
                    data: {
                        labels: Object.keys(threatCounts),
                        datasets: [{
                            data: Object.values(threatCounts),
                            backgroundColor: ['#ef4444', '#f59e0b', '#06b6d4', '#6366f1', '#10b981', '#8b5cf6'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom', labels: { color: '#9ca3af', boxWidth: 12 } }
                        }
                    }
                });
            }

            // 2. Target Nodes Bar Chart
            const ctx2 = document.getElementById('chartTargetNodes');
            if (ctx2) {
                if (chart2Instance) chart2Instance.destroy();
                chart2Instance = new Chart(ctx2, {
                    type: 'bar',
                    data: {
                        labels: Object.keys(targetCounts),
                        datasets: [{
                            label: 'Jumlah Serangan',
                            data: Object.values(targetCounts),
                            backgroundColor: '#06b6d4',
                            borderRadius: 6
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
                            y: { ticks: { color: '#9ca3af', stepSize: 1 }, grid: { color: '#374151' } }
                        }
                    }
                });
            }

            // 3. Timeline Line Chart
            const ctx3 = document.getElementById('chartTimeline');
            if (ctx3) {
                if (chart3Instance) chart3Instance.destroy();
                chart3Instance = new Chart(ctx3, {
                    type: 'line',
                    data: {
                        labels: Object.keys(timelineCounts),
                        datasets: [{
                            label: 'Insiden Terdeteksi',
                            data: Object.values(timelineCounts),
                            borderColor: '#818cf8',
                            backgroundColor: 'rgba(129, 140, 248, 0.1)',
                            fill: true,
                            tension: 0.3,
                            borderWidth: 2,
                            pointBackgroundColor: '#818cf8'
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { ticks: { color: '#9ca3af' }, grid: { display: false } },
                            y: { ticks: { color: '#9ca3af', stepSize: 1 }, grid: { color: '#374151' } }
                        }
                    }
                });
            }
        }

        function updatePaginationControls(start, end, total) {
            document.getElementById('pageStart').innerText = total === 0 ? 0 : start;
            document.getElementById('pageEnd').innerText = end;
            document.getElementById('totalItems').innerText = total;

            const prevBtn = document.getElementById('prevBtn');
            const nextBtn = document.getElementById('nextBtn');

            prevBtn.disabled = (currentPage === 1);
            nextBtn.disabled = (currentPage * ITEMS_PER_PAGE >= total);
        }

        function changePage(direction) {
            currentPage += direction;
            renderTablePage();
        }

        function showEventDetails(idx) {
            isModalOpen = true;
            const ev = eventsData[idx];
            if (!ev) return;
            
            document.getElementById('modalTargetHost').innerText = ev.target_host_display || ev.target_host || 'Local Host / Manager';
            document.getElementById('modalIp').innerText = ev.ip || 'N/A';
            document.getElementById('modalTimestamp').innerText = ev.timestamp || 'N/A';
            document.getElementById('modalMitigation').innerText = ev.mitigation || 'N/A';
            document.getElementById('modalRawLog').innerText = ev.raw_log || 'Log mentah tidak tersedia.';
            
            const hostKey = (ev.target_host || '').toLowerCase();
            const matched = assetsData.find(a => (a.hostname || '').toLowerCase() === hostKey || (a.name || '').toLowerCase().includes(hostKey));
            
            document.getElementById('modalTargetWg').innerText = ev.target_ip || (matched ? matched.wg_ip : '10.88.0.x');
            document.getElementById('modalTargetLan').innerText = ev.target_lan || (matched ? matched.lan_ip : '-');
            document.getElementById('modalTargetService').innerText = ev.target_service || (matched ? matched.services : 'Layanan Kampus Terpantau');

            document.getElementById('modalAnalysis').innerText = ev.analysis || 'Analisis tidak tersedia.';
            
            let detailText = ev.detailed_analysis;
            if (typeof detailText === 'object' && detailText !== null) {
                const labels = {
                    server_targeted: "Target Server",
                    reason_blocked: "Alasan Blokir",
                    exploited_vulnerability: "Kerentanan yang Dieksploitasi",
                    threat_behaviour: "Perilaku Ancaman",
                    recommended_next_steps: "Rekomendasi Tindakan & Mitigasi"
                };
                detailText = Object.entries(detailText)
                    .map(([k, v]) => `• ${labels[k] || k.replace(/_/g, ' ').toUpperCase()}:\n  ${typeof v === 'object' ? JSON.stringify(v) : v}`)
                    .join('\n\n');
            }
            document.getElementById('modalDetailedAnalysis').innerText = detailText || 'Tidak ada laporan kognitif mendalam tambahan untuk kejadian lama ini.';
            
            const badge = document.getElementById('modalActionBadge');
            badge.innerText = (ev.action || 'ignore').toUpperCase();
            if (ev.action === 'block') {
                badge.className = "px-3 py-1 rounded-full text-xs font-bold uppercase bg-red-950/40 text-red-400 border border-red-900/50";
            } else {
                badge.className = "px-3 py-1 rounded-full text-xs font-bold uppercase bg-green-950/40 text-green-400 border border-green-900/50";
            }
            
            const modal = document.getElementById('incidentModal');
            modal.classList.remove('hidden');
            setTimeout(() => {
                modal.querySelector('.transform').classList.remove('scale-95');
                modal.querySelector('.transform').classList.add('scale-100');
            }, 10);
        }

        function closeModal() {
            const modal = document.getElementById('incidentModal');
            modal.querySelector('.transform').classList.remove('scale-100');
            modal.querySelector('.transform').classList.add('scale-95');
            setTimeout(() => {
                modal.classList.add('hidden');
                isModalOpen = false;
            }, 150);
        }

        function openAddAssetModal() {
            document.getElementById('addAssetModal').classList.remove('hidden');
        }

        function closeAddAssetModal() {
            document.getElementById('addAssetModal').classList.add('hidden');
        }

        function submitNewAsset(e) {
            e.preventDefault();
            const payload = {
                hostname: document.getElementById('inputHostname').value.trim(),
                name: document.getElementById('inputName').value.trim(),
                wg_ip: document.getElementById('inputWgIp').value.trim(),
                lan_ip: document.getElementById('inputLanIp').value.trim(),
                services: document.getElementById('inputServices').value.trim(),
                status: "protected"
            };

            fetch('/api/assets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert("Node berhasil didaftarkan ke inventaris SOAR!");
                    closeAddAssetModal();
                    document.getElementById('addAssetForm').reset();
                    fetchAssetsFromDB();
                } else {
                    alert("Gagal menambahkan node: " + (data.error || "Kesalahan tidak diketahui"));
                }
            })
            .catch(err => {
                alert("Error koneksi: " + err);
            });
        }

        // Inisialisasi awal
        fetchEventsFromDB();
        fetchAssetsFromDB();
        fetchBlockedFromDB();
        
        setInterval(() => {
            if (!isModalOpen) {
                if (activeTab === 'events') fetchEventsFromDB();
                else if (activeTab === 'blocked') fetchBlockedFromDB();
            }
        }, 5000);
    </script>
</body>
</html>
"""
            self.wfile.write(html_content.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    # 2. HANDLE POST (LOGIN, WEBHOOK, UNBLOCK, ASSET REGISTRATION)
    def do_POST(self):
        # A. Login Authentication Endpoint
        if self.path == '/api/login':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                creds = json.loads(post_data)
                u = creds.get('username', '').strip()
                p = creds.get('password', '').strip()
                if u == ADMIN_USER and p == ADMIN_PASS:
                    token = secrets.token_hex(24)
                    expires = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
                    sessions = load_sessions()
                    sessions[token] = {"user": ADMIN_USER, "expires": expires}
                    save_sessions(sessions)

                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Set-Cookie', f'soar_session={token}; Path=/; Max-Age=604800; HttpOnly; SameSite=Lax')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                    return
                else:
                    self.send_response(401)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Username atau password tidak valid!"}).encode('utf-8'))
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                return

        # B. Unblock Endpoint (Memerlukan Autentikasi)
        elif self.path == '/api/unblock':
            if not is_authenticated(self.headers):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode('utf-8'))
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                payload = json.loads(post_data)
                ip = payload.get('ip', '').strip()
                if not ip:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "IP wajib disertakan"}).encode('utf-8'))
                    return

                unblock_ip_everywhere(ip)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": f"IP {ip} berhasil di-unblock"}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                return

        # C. Registrasi Aset Baru (Memerlukan Autentikasi)
        elif self.path == '/api/assets':
            if not is_authenticated(self.headers):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized"}).encode('utf-8'))
                return

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                new_asset_data = json.loads(post_data)
                hostname = new_asset_data.get('hostname', '').strip()
                wg_ip = new_asset_data.get('wg_ip', '').strip()
                if not hostname or not wg_ip:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "Hostname dan IP WireGuard wajib diisi"}).encode('utf-8'))
                    return

                assets = load_assets()
                updated = False
                for idx, a in enumerate(assets):
                    if a.get('hostname', '').lower() == hostname.lower():
                        assets[idx].update(new_asset_data)
                        updated = True
                        break
                if not updated:
                    assets.append(new_asset_data)
                
                save_assets(assets)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "assets": assets}).encode('utf-8'))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
                return

        # D. Webhook Ingestion (Terbuka untuk integrasi Wazuh SIEM)
        elif self.path == '/webhook':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            try:
                log_data = json.loads(post_data)
                
                # 1. ArusBalik Embedded WAF Format
                if log_data.get("source") == "arusbalik_waf" or "rule_id" in log_data:
                    attacker_ip = str(log_data.get('attacker_ip') or log_data.get('client_ip') or log_data.get('ip') or '').strip()
                    target_host = str(log_data.get('target_host') or log_data.get('host') or 'Web Application').strip()
                    rule_id = log_data.get('rule_id', 0)
                    uri = str(log_data.get('uri') or '/')
                    method = str(log_data.get('method') or 'GET')
                    incident_name = str(log_data.get('incident_type') or 'Web Application Attack')
                    incident_type = f"WAF Block: {incident_name} (Rule {rule_id})"
                    raw_log = f"ArusBalik WAF Blocked | Rule: {rule_id} | Host: {target_host} | Method: {method} | URI: {uri} | Attacker IP: {attacker_ip}"

                    matched_asset = get_asset_by_host_or_ip(target_host)
                    target_display = f"{target_host} ({matched_asset['wg_ip']})" if matched_asset else target_host

                    action = "block"
                    mitigation_status = "Diblokir oleh ArusBalik Embedded WAF (HTTP 403)"
                    is_valid_ip = bool(re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', attacker_ip))
                    is_whitelisted = (
                        attacker_ip in ('0.0.0.0', '255.255.255.255') or
                        attacker_ip.startswith("10.88.0.") or 
                        attacker_ip.startswith("127.") or 
                        attacker_ip in EXTRA_WHITELIST_IPS
                    )

                    if attacker_ip and is_valid_ip and not is_whitelisted:
                        block_ip_everywhere(attacker_ip, ttl=DEFAULT_TTL)
                        mitigation_status = f"Diblokir oleh ArusBalik WAF (403) & O(1) ipset drop ({attacker_ip})"

                    event_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                    events = load_events()
                    new_event = {
                        "id": event_id,
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "incident_type": incident_type,
                        "target_host": target_host,
                        "target_host_display": target_display,
                        "target_ip": matched_asset.get('wg_ip') if matched_asset else 'N/A',
                        "target_lan": matched_asset.get('lan_ip') if matched_asset else 'N/A',
                        "target_service": matched_asset.get('services') if matched_asset else 'N/A',
                        "raw_log": raw_log,
                        "ip": attacker_ip if attacker_ip else "N/A",
                        "analysis": f"Permintaan berbahaya ke {target_host}{uri} diblokir langsung oleh ArusBalik In-Process WAF (Rule {rule_id}).",
                        "detailed_analysis": "Ollama Llama 3.2 sedang merumuskan analisis kognitif di latar belakang secara asinkron...",
                        "action": action,
                        "mitigation": mitigation_status
                    }
                    events.append(new_event)
                    if len(events) > 50:
                        events = events[-50:]
                    save_events(events)

                    t = threading.Thread(
                        target=run_background_analysis,
                        args=(event_id, incident_type, f"WAF rule {rule_id} triggered on {uri} by {attacker_ip}", target_host, raw_log)
                    )
                    t.daemon = True
                    t.start()

                    self.wfile.write(json.dumps({"success": True, "id": event_id, "event": new_event}).encode('utf-8'))
                    return

                # Tracecat format
                if "analysis_summary" in log_data:
                    action = log_data.get('action', 'ignore').lower()
                    attacker_ip = log_data.get('ip', '').strip()
                    incident_type = log_data.get('incident_type', 'Kejadian Umum')
                    analysis_summary = log_data.get('analysis_summary') or log_data.get('analysis') or log_data.get('summary') or 'Analisis tidak tersedia.'
                    detailed_analysis = log_data.get('detailed_analysis') or 'Tidak tersedia.'
                    target_host = log_data.get('target_host') or 'Local Host'
                    raw_log = log_data.get('raw_log') or 'Log mentah tidak tersedia.'
                    
                    matched_asset = get_asset_by_host_or_ip(target_host)
                    target_display = f"{target_host} ({matched_asset['wg_ip']})" if matched_asset else target_host
                    
                    mitigation_status = "Diabaikan (Normal)"
                    is_valid_ip = re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', attacker_ip)
                    
                    if action == 'block' and attacker_ip and is_valid_ip:
                        block_ip_everywhere(attacker_ip, ttl=DEFAULT_TTL)
                        mitigation_status = f"IP {attacker_ip} Diblokir via O(1) ipset (Edge ArusBalik & Proxmox Host)"
                    
                    events = load_events()
                    new_event = {
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "incident_type": incident_type,
                        "target_host": target_host,
                        "target_host_display": target_display,
                        "target_ip": matched_asset.get('wg_ip') if matched_asset else 'N/A',
                        "target_lan": matched_asset.get('lan_ip') if matched_asset else 'N/A',
                        "target_service": matched_asset.get('services') if matched_asset else 'N/A',
                        "raw_log": raw_log,
                        "ip": attacker_ip if attacker_ip else "N/A",
                        "analysis": analysis_summary,
                        "detailed_analysis": detailed_analysis,
                        "action": action,
                        "mitigation": mitigation_status
                    }
                    events.append(new_event)
                    if len(events) > 50:
                        events = events[-50:]
                    save_events(events)
                    self.wfile.write(json.dumps({"success": True, "event": new_event}).encode('utf-8'))
                    return
                
                # Wazuh Alert Format
                log_title = log_data.get('title', 'Aktivitas Keamanan Tidak Dikenal')
                log_text = log_data.get('text', '')
                
                agent_name = log_data.get('agent', {}).get('name') or log_data.get('location') or 'Local Host'
                raw_log = log_data.get('full_log') or log_data.get('message') or log_text or 'Log mentah tidak tersedia.'
                
                attacker_ip = ""
                if 'data' in log_data and isinstance(log_data['data'], dict):
                    attacker_ip = log_data['data'].get('srcip', '')
                
                if not attacker_ip:
                    ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', raw_log)
                    if ip_match:
                        found_ip = ip_match.group(0)
                        if not found_ip.startswith("10.88.0.") and not found_ip.startswith("127."):
                            attacker_ip = found_ip

                attacker_ip = attacker_ip.strip()
                
                matched_asset = get_asset_by_host_or_ip(agent_name)
                target_display = f"{agent_name} ({matched_asset['wg_ip']})" if matched_asset else agent_name
                
                # --- MITIGASI INSTAN VIA IPSET (SUB-MILIDETIK O(1)) ---
                action = "ignore"
                mitigation_status = "Diabaikan (Normal)"
                is_valid_ip = re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', attacker_ip)
                
                is_whitelisted = (
                    attacker_ip in ('0.0.0.0', '255.255.255.255') or
                    attacker_ip.startswith("10.88.0.") or 
                    attacker_ip.startswith("127.") or 
                    attacker_ip in EXTRA_WHITELIST_IPS
                )

                if attacker_ip and is_valid_ip:
                    if is_whitelisted:
                        action = "ignore"
                        mitigation_status = f"IP {attacker_ip} Dikecualikan (Internal Whitelist)"
                    else:
                        action = "block"
                        block_ip_everywhere(attacker_ip, ttl=DEFAULT_TTL)
                        mitigation_status = f"IP {attacker_ip} Diblokir via O(1) ipset (Edge ArusBalik & Proxmox Host)"

                event_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
                events = load_events()
                new_event = {
                    "id": event_id,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "incident_type": log_title,
                    "target_host": agent_name,
                    "target_host_display": target_display,
                    "target_ip": matched_asset.get('wg_ip') if matched_asset else 'N/A',
                    "target_lan": matched_asset.get('lan_ip') if matched_asset else 'N/A',
                    "target_service": matched_asset.get('services') if matched_asset else 'N/A',
                    "raw_log": raw_log,
                    "ip": attacker_ip if attacker_ip else "N/A",
                    "analysis": "Sedang menganalisis log siber...",
                    "detailed_analysis": "Ollama Llama 3.2 sedang merumuskan analisis kognitif di latar belakang secara asinkron...",
                    "action": action,
                    "mitigation": mitigation_status
                }
                events.append(new_event)
                if len(events) > 50:
                    events = events[-50:]
                save_events(events)

                t = threading.Thread(target=run_background_analysis, args=(event_id, log_title, log_text, agent_name, raw_log))
                t.daemon = True
                t.start()

                self.wfile.write(json.dumps({"success": True, "id": event_id}).encode('utf-8'))
                
            except Exception as e:
                print("Error parsing webhook:", e)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

class ReusableThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

def run_server():
    server = ReusableThreadingTCPServer(('0.0.0.0', PORT), LightweightSOARHandler)
    print(f"[*] Lightweight SOAR Engine aktif di port {PORT}...")
    server.serve_forever()

if __name__ == '__main__':
    run_server()
