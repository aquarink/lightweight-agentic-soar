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

# PORT LAYANAN WEB & WEBHOOK
PORT = 8080
EVENTS_FILE = '/root/riset/soar_events.json'
ASSETS_FILE = '/root/riset/protected_assets.json'
OLLAMA_URL = 'http://10.88.0.4:11434/api/generate'

# Lock untuk keamanan akses file thread-safe
db_lock = threading.Lock()

# Fungsi untuk memuat data kejadian lama
def load_events():
    with db_lock:
        if os.path.exists(EVENTS_FILE):
            try:
                with open(EVENTS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

# Fungsi untuk menyimpan data kejadian baru
def save_events(events):
    with db_lock:
        try:
            with open(EVENTS_FILE, 'w') as f:
                json.dump(events, f, indent=2)
        except Exception as e:
            print("Gagal menyimpan event ke file:", e)

# Fungsi untuk memuat data aset node yang dilindungi
def load_assets():
    with db_lock:
        if os.path.exists(ASSETS_FILE):
            try:
                with open(ASSETS_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

# Fungsi untuk menyimpan data aset node
def save_assets(assets):
    with db_lock:
        try:
            with open(ASSETS_FILE, 'w') as f:
                json.dump(assets, f, indent=2)
        except Exception as e:
            print("Gagal menyimpan aset ke file:", e)

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

    
    # 1. HANDLE WEB DASHBOARD (GET /)
    def do_GET(self):
        # API ENDPOINT UNTUK MENARIK DATA DARI DATABASE SECARA DINAMIS
        if self.path == '/api/events':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            events = load_events()
            self.wfile.write(json.dumps(events).encode('utf-8'))
            return

        elif self.path == '/api/assets':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            assets = load_assets()
            self.wfile.write(json.dumps(assets).encode('utf-8'))
            return

        elif self.path in ['/favicon.ico', '/favicon.png', '/soar_logo.jpg']:
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
            
        elif self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            
            # HTML Dashboard SPA Premium dengan fitur Pagination & AJAX (Tarik DB langsung, tidak ke LLM saat muat halaman)
            html_content = """<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lightweight Cognitive SOAR - Dashboard</title>
    <link rel="icon" type="image/jpeg" href="/soar_logo.jpg">
    <link rel="shortcut icon" href="/favicon.ico">
    <script src="https://cdn.tailwindcss.com"></script>
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
                <p class="text-gray-400 mt-2 text-sm md:text-base">Sistem Orkestrasi Keamanan Siber Terintegrasi berbasis LLM Lokal Ringan (Ollama)</p>
            </div>
            <div class="mt-4 md:mt-0 flex items-center bg-gray-800 border border-gray-700 px-4 py-2 rounded-lg text-sm text-indigo-400 font-mono shadow-inner">
                <span class="w-3 h-3 bg-green-500 rounded-full inline-block mr-2.5 animate-pulse"></span>
                SOC Active Mode
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
                <p class="text-sm text-gray-400 font-medium">Mitigasi Pemblokiran (Block)</p>
                <p id="statBlock" class="text-3xl font-bold text-red-500 mt-2">0</p>
            </div>
            <div class="bg-gray-800 p-6 rounded-xl border border-gray-700 shadow-md">
                <p class="text-sm text-gray-400 font-medium">Aktivitas Diabaikan (Ignore)</p>
                <p id="statIgnore" class="text-3xl font-bold text-green-400 mt-2">0</p>
            </div>
        </div>

        <!-- Tab Navigasi -->
        <div class="flex space-x-2 border-b border-gray-700 mb-6">
            <button id="tabEventsBtn" onclick="switchTab('events')" class="px-5 py-3 font-semibold text-sm border-b-2 border-indigo-500 text-indigo-400 flex items-center space-x-2 transition-all">
                <span>⚡ Log Triase Insiden Real-Time</span>
                <span id="badgeEventCount" class="bg-indigo-900/60 text-indigo-300 text-xs px-2 py-0.5 rounded-full font-mono">0</span>
            </button>
            <button id="tabAssetsBtn" onclick="switchTab('assets')" class="px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all">
                <span>🛡️ Inventaris Node & IP Terlindungi</span>
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

        <!-- VIEW 2: TABEL INVENTARIS NODE TERLINDUNGI -->
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

    <!-- JAVASCRIPT SPA LOGIC -->
    <script>
        let eventsData = [];
        let assetsData = [];
        let currentPage = 1;
        const ITEMS_PER_PAGE = 8;
        let isModalOpen = false;
        let activeTab = 'events';

        function switchTab(tab) {
            activeTab = tab;
            const eventsBtn = document.getElementById('tabEventsBtn');
            const assetsBtn = document.getElementById('tabAssetsBtn');
            const eventsView = document.getElementById('tabEventsView');
            const assetsView = document.getElementById('tabAssetsView');

            if (tab === 'events') {
                eventsBtn.className = "px-5 py-3 font-semibold text-sm border-b-2 border-indigo-500 text-indigo-400 flex items-center space-x-2 transition-all";
                assetsBtn.className = "px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all";
                eventsView.classList.remove('hidden');
                assetsView.classList.add('hidden');
            } else {
                assetsBtn.className = "px-5 py-3 font-semibold text-sm border-b-2 border-cyan-500 text-cyan-400 flex items-center space-x-2 transition-all";
                eventsBtn.className = "px-5 py-3 font-semibold text-sm border-b-2 border-transparent text-gray-400 hover:text-gray-200 flex items-center space-x-2 transition-all";
                eventsView.classList.add('hidden');
                assetsView.classList.remove('hidden');
                fetchAssetsFromDB();
            }
        }

        function fetchEventsFromDB() {
            fetch('/api/events')
                .then(res => res.json())
                .then(data => {
                    eventsData = data;
                    document.getElementById('badgeEventCount').innerText = eventsData.length;
                    updateStats();
                    renderTablePage();
                })
                .catch(err => console.error("Gagal menarik data log:", err));
        }

        function fetchAssetsFromDB() {
            fetch('/api/assets')
                .then(res => res.json())
                .then(data => {
                    assetsData = data;
                    document.getElementById('statAssets').innerText = assetsData.length;
                    document.getElementById('badgeAssetCount').innerText = assetsData.length;
                    renderAssetsTable();
                })
                .catch(err => console.error("Gagal menarik data aset:", err));
        }

        function updateStats() {
            let total = eventsData.length;
            let blockCount = 0;
            let ignoreCount = 0;

            eventsData.forEach(ev => {
                if (ev.action === 'block') blockCount++;
                else ignoreCount++;
            });

            document.getElementById('statTotal').innerText = total;
            document.getElementById('statBlock').innerText = blockCount;
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
            
            // Detail Topologi Korban
            const hostKey = (ev.target_host || '').toLowerCase();
            const matched = assetsData.find(a => (a.hostname || '').toLowerCase() === hostKey || (a.name || '').toLowerCase().includes(hostKey));
            
            document.getElementById('modalTargetWg').innerText = ev.target_ip || (matched ? matched.wg_ip : '10.88.0.x');
            document.getElementById('modalTargetLan').innerText = ev.target_lan || (matched ? matched.lan_ip : '-');
            document.getElementById('modalTargetService').innerText = ev.target_service || (matched ? matched.services : 'Layanan Kampus Terpantau');

            document.getElementById('modalAnalysis').innerText = ev.analysis || 'Analisis tidak tersedia.';
            document.getElementById('modalDetailedAnalysis').innerText = ev.detailed_analysis || 'Tidak ada laporan kognitif mendalam tambahan untuk kejadian lama ini.';
            
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
        
        setInterval(() => {
            if (!isModalOpen && activeTab === 'events') {
                fetchEventsFromDB();
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

    # 2. HANDLE POST (WEBHOOK DARI WAZUH/TRACECAT & REGISTRASI ASET)
    def do_POST(self):
        # Endpoint untuk registrasi atau pembaruan aset node terlindungi secara dinamis
        if self.path == '/api/assets':
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

        elif self.path == '/webhook':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            try:
                # Parsing log
                log_data = json.loads(post_data)
                
                # Cek jika log berasal dari alur kerja Tracecat (memiliki analysis_summary)
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
                        try:
                            res = subprocess.run(["/usr/sbin/iptables", "-C", "INPUT", "-s", attacker_ip, "-j", "DROP"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            if res.returncode == 0:
                                mitigation_status = f"IP {attacker_ip} Sudah Diblokir Sebelumnya"
                            else:
                                subprocess.run(["/usr/sbin/iptables", "-A", "INPUT", "-s", attacker_ip, "-j", "DROP"], check=True)
                                subprocess.run(["/usr/sbin/iptables", "-A", "FORWARD", "-s", attacker_ip, "-j", "DROP"], check=False)
                                mitigation_status = f"IP {attacker_ip} Berhasil Diblokir via iptables"
                        except Exception as err:
                            mitigation_status = f"Gagal memblokir IP {attacker_ip}"
                    
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
                
                # JIKA BUKAN DARI TRACECAT (LOG WAZUH LAMA - ALIRAN UTAMA KITA SEKARANG)
                log_title = log_data.get('title', 'Aktivitas Keamanan Tidak Dikenal')
                log_text = log_data.get('text', '')
                
                # Ekstrak data server target (agent wazuh) dan log mentah siber
                agent_name = log_data.get('agent', {}).get('name') or log_data.get('location') or 'Local Host'
                raw_log = log_data.get('full_log') or log_data.get('message') or log_text or 'Log mentah tidak tersedia.'
                
                # Ekstrak IP penyerang dari data wazuh
                attacker_ip = ""
                if 'data' in log_data and isinstance(log_data['data'], dict):
                    attacker_ip = log_data['data'].get('srcip', '')
                
                # Fallback ekstraksi IP menggunakan Regex jika srcip kosong
                if not attacker_ip:
                    ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', raw_log)
                    if ip_match:
                        found_ip = ip_match.group(0)
                        if not found_ip.startswith("10.88.0.") and not found_ip.startswith("127."):
                            attacker_ip = found_ip

                attacker_ip = attacker_ip.strip()
                
                matched_asset = get_asset_by_host_or_ip(agent_name)
                target_display = f"{agent_name} ({matched_asset['wg_ip']})" if matched_asset else agent_name
                
                # --- MITIGASI INSTAN (SUB-MILIDETIK) ---
                action = "ignore"
                mitigation_status = "Diabaikan (Normal)"
                is_valid_ip = re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', attacker_ip)
                
                # Cek whitelist agar IP infrastruktur internal tidak terblokir sendiri
                is_whitelisted = (
                    attacker_ip.startswith("10.88.0.") or 
                    attacker_ip.startswith("127.") or 
                    attacker_ip.startswith("172.20.") or
                    attacker_ip == "38.47.180.2"
                )

                if attacker_ip and is_valid_ip:
                    if is_whitelisted:
                        action = "ignore"
                        mitigation_status = f"IP {attacker_ip} Dikecualikan (Internal Whitelist)"
                    else:
                        action = "block"
                        try:
                            res = subprocess.run(["/usr/sbin/iptables", "-C", "INPUT", "-s", attacker_ip, "-j", "DROP"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            if res.returncode == 0:
                                mitigation_status = f"IP {attacker_ip} Sudah Diblokir Sebelumnya"
                            else:
                                subprocess.run(["/usr/sbin/iptables", "-A", "INPUT", "-s", attacker_ip, "-j", "DROP"], check=True)
                                subprocess.run(["/usr/sbin/iptables", "-A", "FORWARD", "-s", attacker_ip, "-j", "DROP"], check=False)
                                mitigation_status = f"IP {attacker_ip} Berhasil Diblokir via iptables"
                        except Exception as err:
                            print("Gagal eksekusi mitigasi iptables:", err)
                            mitigation_status = f"Gagal memblokir IP {attacker_ip}"

                # Generate event ID unik
                event_id = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")

                # Simpan log ke database dengan status awal (Sedang dianalisis...)
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

                # --- PEMROSESAN LLM ASINKRON (BACKGROUND THREAD) ---
                def run_background_analysis(ev_id, title, text, host, raw):
                    try:
                        prompt = (
                            f"Analyze this security log from targeted server '{host}':\n"
                            f"Title: {title}\n"
                            f"Raw Log Message: {raw}\n\n"
                            f"Return a JSON object with these keys:\n"
                            f"1. 'action': either 'block' (if brute force, attacks, or security breach) or 'ignore'\n"
                            f"2. 'ip': the attacker source IP address if found in the log\n"
                            f"3. 'incident_type': type of attack or event\n"
                            f"4. 'analysis_summary': brief explanation of what happened in Indonesian language\n"
                            f"5. 'detailed_analysis': a long, humanized and structured report in Indonesian language explaining: "
                            f"which server was targeted ({host}), why it was blocked or ignored, what vulnerability "
                            f"was exploited (XSS, SQLi, brute force, etc.), how the threat behaves, and recommended next steps."
                        )
                        ollama_payload = {
                            "model": "llama3.2",
                            "prompt": prompt,
                            "format": "json",
                            "stream": False
                        }
                        req = urllib.request.Request(
                            OLLAMA_URL, 
                            data=json.dumps(ollama_payload).encode('utf-8'),
                            headers={'Content-Type': 'application/json'}
                        )
                        with urllib.request.urlopen(req, timeout=60) as response:
                            res_body = response.read().decode('utf-8')
                            res_json = json.loads(res_body)
                            ai_raw_response = res_json.get('response', '').strip()
                        
                        ai_data = json.loads(ai_raw_response)
                        analysis_summary = ai_data.get('analysis_summary') or ai_data.get('analysis') or ai_data.get('summary') or 'Analisis tidak tersedia.'
                        detailed_analysis = ai_data.get('detailed_analysis') or 'Tidak tersedia.'
                        incident_type_ai = ai_data.get('incident_type') or title
                        
                        # Muat ulang data event, cari yang ID-nya sama, dan update laporannya
                        current_events = load_events()
                        for ev in current_events:
                            if ev.get("id") == ev_id:
                                ev["analysis"] = analysis_summary
                                ev["detailed_analysis"] = detailed_analysis
                                ev["incident_type"] = incident_type_ai
                                break
                        save_events(current_events)
                        print(f"[BACKGROUND LLM] Sukses memperbarui analisis untuk event: {ev_id}")
                    except Exception as e:
                        print(f"[BACKGROUND LLM ERROR] Gagal memperbarui event {ev_id}: {e}")
                        current_events = load_events()
                        for ev in current_events:
                            if ev.get("id") == ev_id:
                                ev["analysis"] = "Gagal memproses analisis LLM."
                                ev["detailed_analysis"] = f"Terjadi kesalahan saat memanggil LLM lokal: {str(e)}"
                                break
                        save_events(current_events)

                # Jalankan thread asinkron untuk inferensi LLM
                threading.Thread(target=run_background_analysis, args=(event_id, log_title, log_text, agent_name, raw_log)).start()

                # Kembalikan respon sukses instan ke Wazuh
                self.wfile.write(json.dumps({
                    "success": True, 
                    "message": "Webhook received. Attacker blocked instantly. LLM analysis started in background."
                }).encode('utf-8'))
                
            except Exception as e:
                print("Error saat memproses webhook SOAR:", e)
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    # Pastikan direktori riset ada
    os.makedirs('/root/riset', exist_ok=True)
    
    # Jalankan server
    handler = LightweightSOARHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), handler) as httpd:
        print(f"Layanan Lightweight Agentic SOAR berjalan di port {PORT}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nMenghentikan server.")
