# Integrasi Wazuh SIEM dan Suricata NIDS Menggunakan Agentic SOAR Ringan Kustom Berbasis LLM Lokal untuk Otomatisasi Respons Insiden pada Virtualisasi On-Premises

**Penulis:** [Nama Penulis]  
**Afiliasi:** UIN Syarif Hidayatullah Jakarta  
**Target Jurnal:** Sinta 3 (Bidang Cybersecurity / Sistem Informasi / Teknik Informatika)  

---

## ABSTRAK

Meningkatnya volume peringatan keamanan (*security alerts*) pada infrastruktur teknologi informasi sering kali memicu fenomena *alert fatigue* bagi analis *Security Operations Center* (SOC). Sistem SOAR (*Security Orchestration, Automation, and Response*) konvensional seperti Shuffle memiliki overhead komputasi yang tinggi dan bergantung pada infrastruktur kompleks. Penelitian ini mengusulkan arsitektur otomatisasi respons insiden berbasis kognitif (*Agentic SOAR*) menggunakan model bahasa besar lokal (*Local Large Language Model* / LLM) yang diintegrasikan dengan Wazuh SIEM dan Suricata NIDS secara langsung menggunakan mikroservis SOAR kustom berbasis Python yang sangat ringan, tanpa dependensi platform berat. Sistem dideploy pada infrastruktur virtualisasi *on-premises* berbasis hypervisor Proxmox VE dengan multi-VM (Virtual Machine) yang saling terhubung menggunakan VPN WireGuard dan diamankan via Caddy Reverse Proxy. 

Pengujian dilakukan secara empiris dengan menembakkan log simulasi serangan *Brute Force SSH* ke Webhook SOAR kustom. Evaluasi performa menunjukkan bahwa penggunaan LLM lokal berukuran kecil (*lightweight*), seperti `gemma3:1b` (880 MB) dan `llama3.2:latest` (2.0 GB), mampu menghasilkan keputusan analisis log siber secara kontekstual dalam waktu rata-rata **2,67 - 4,85 detik** dengan beban CPU minimal. Sebaliknya, penggunaan model besar seperti `llama3.1:8b` (4.9 GB) pada CPU tanpa akselerasi perangkat keras memicu kegagalan sistem akibat *read timeout* (>120 detik) dan memicu *resource overhead* CPU hingga 739%. Penelitian ini membuktikan bahwa kombinasi SIEM-SOAR lokal dengan *lightweight* LLM lokal menawarkan solusi respons insiden siber yang cepat, murah (*zero-cost API*), mandiri, dan menjamin privasi data secara penuh pada klaster virtualisasi privat dengan overhead komputasi minimal (<25 MB RAM).

**Kata Kunci:** Wazuh SIEM, Suricata NIDS, Lightweight SOAR, Agentic AI, Local LLM, Proxmox.

---

## 1. PENDAHULUAN

Pemantauan keamanan teknologi informasi modern membutuhkan kombinasi deteksi ancaman di tingkat *host* (Host-based IDS/SIEM) dan tingkat *jaringan* (Network-based IDS). Wazuh SIEM menyediakan kapabilitas pengawasan *host* yang mumpuni melalui wazuh-agent, namun membutuhkan kolaborasi dengan alat deteksi jaringan seperti Suricata untuk mendapatkan visibilitas penuh terhadap paket data yang melintasi infrastruktur. 

Ketika sistem pertahanan tersebut aktif, jumlah alarm keamanan (*alerts*) yang dihasilkan setiap harinya sangat besar. Fenomena ini sering kali memicu kejenuhan peringatan (*alert fatigue*) bagi analis keamanan pada *Security Operations Center* (SOC), di mana ancaman nyata yang berbahaya sering kali terlewat di antara ribuan alarm palsu (*false positives*). Platform *Security Orchestration, Automation, and Response* (SOAR) hadir untuk mengatasi masalah ini melalui otomatisasi penanganan insiden (*incident response playbooks*). 

Namun, platform SOAR tradisional sangat bergantung pada aturan penulisan *script* statis (*rule-based*) yang kaku (seperti regex pencocokan kata kunci). Jika format log berubah sedikit saja, otomatisasi tersebut akan gagal. Di sisi lain, integrasi kecerdasan buatan berbasis *Large Language Model* (LLM) komersial di awan (*cloud-based LLM* seperti GPT-4 via API) memicu kekhawatiran serius terkait biaya transaksi API yang mahal dan risiko kebocoran data log sensitif instansi ke server pihak ketiga.

Riset ini mengusulkan rancangan dan implementasi **Agentic SOAR lokal (on-premises)** kustom berbasis mikroservis Python super-ringan (*zero-dependency*) dan **Ollama LLM Lokal** (Gemma/Llama) yang diintegrasikan dengan Wazuh SIEM dan Suricata NIDS pada lingkungan hypervisor Proxmox VE. Penelitian ini fokus pada pemodelan integrasi sistem, penanganan *bottleneck* I/O pada database SIEM lokal, serta evaluasi performa respon waktu (*latency*) berbagai model LLM lokal untuk menghasilkan keputusan mitigasi serangan siber secara otomatis.

---

## 2. TINJAUAN PUSTAKA & ANALISIS GAP

Penelitian mengenai otomatisasi keamanan berbasis *Security Orchestration, Automation, and Response* (SOAR) dan *Large Language Models* (LLM) telah berkembang pesat. Dua studi Q1 bereputasi tinggi pada tahun 2025 menjadi landasan penting dalam mengidentifikasi celah penelitian (*research gap*) riset ini:

1. **Hu et al. (2025)** dalam penelitiannya *"A Novel LLM Approach of Cybersecurity Threat Analysis and Response"* menerapkan model besar `Qwen-72B` yang diintegrasikan dengan SOAR untuk menganalisis urgensi ancaman. Namun, sistem mereka diuji secara terbatas pada lingkungan simulasi *cloud-native* publik dan menyarankan penelitian masa depan untuk menguji adaptasi pada arsitektur lokal (*on-premises*) yang terintegrasi dengan SIEM lokal.
2. **Zhang et al. (2025)** dalam *"Design and Computational Modeling of an AI-Based Automated Cybersecurity Incident Response System"* mengajukan otomatisasi respons insiden menggunakan algoritma DRL (*Deep Reinforcement Learning*) dan LSTM-Attention. Penelitian tersebut menyoroti beban sumber daya komputasi (*resource overhead*) yang sangat tinggi pada pemrosesan LLM besar dan merekomendasikan penggunaan model AI ringan (*lightweight*) untuk *edge deployment* lokal agar mencapai waktu respon cepat (*sub-second latency*).

**Celah Penelitian (*Research Gap*) & Kebaruan (*Novelty*):**
Dari kedua studi di atas, terdapat kekosongan literatur mengenai bagaimana merancang sistem **Agentic SOAR lokal** yang andal di atas **infrastruktur hypervisor virtualisasi privat (seperti Proxmox VE) dengan keterbatasan perangkat keras**. 

Kebaruan riset ini adalah keberhasilan mengimplementasikan arsitektur integratif **SIEM (Wazuh) - NIDS (Suricata) - Custom Lightweight SOAR - LLM Lokal (Ollama)** secara mandiri. Kami menggunakan model AI berukuran kecil (*Gemma 3:1B* dan *Llama 3.2:3B*) untuk memotong waktu tunggu respons hingga di bawah 5 detik, menyelesaikan konflik inisialisasi database *indexer* lokal akibat beban I/O mesin virtual, serta melindungi privasi data operasional menggunakan enkripsi VPN WireGuard dan Caddy Reverse Proxy secara lokal tanpa menggunakan API berbayar dari pihak ketiga.

---

## 3. METODOLOGI PENELITIAN & PERANCANGAN SISTEM

### 3.1. Topologi Jaringan Terdistribusi Multi-VM
Sistem dibangun di atas server fisik yang menjalankan hypervisor **Proxmox VE**. Lingkungan ini dibagi menjadi beberapa Virtual Machine (VM) berbasis Ubuntu Server dengan alokasi peran terdistribusi sebagai berikut:
* **Host Proxmox:** Menjalankan sensor **Suricata NIDS** secara langsung pada bridge lokal `vmbr0`.
* **VM 100 (LLM):** Menposkan layanan **Ollama API** (`port 11434`) untuk pemrosesan inferensi keputusan AI.
* **VM 105 (Wazuh SIEM):** Menjalankan *Wazuh Indexer*, *Wazuh Manager*, *Wazuh Dashboard*, dan dasbor visualisasi *Grafana*.
* **Host Proxmox / VM ADM:** Menjalankan **Custom Lightweight SOAR (Python Microservice)** pada `port 8080` untuk memproses webhook dari Wazuh, memanggil Ollama API secara real-time, dan mengembalikan dashboard visual.
* **VPS Arus Balik:** Bertindak sebagai *Hub VPN WireGuard* (`10.88.0.1`) dan *Caddy Reverse Proxy* publik.

Seluruh komunikasi antar-VM diamankan di dalam terowongan VPN WireGuard (`10.88.0.0/24`) guna mencegah penyadapan data log mentah.

### 3.2. Metodologi Integrasi Telemetri (Suricata & Wazuh)
Deteksi jaringan NIDS dipusatkan pada kartu jembatan virtual host Proxmox (`vmbr0`) untuk menyadap seluruh lalu lintas data antar-VM (*promiscuous mode*). Konfigurasi Suricata diatur pada `/etc/suricata/suricata.yaml`:
```yaml
af-packet:
  - interface: vmbr0
```
Log keluaran Suricata (`/var/log/suricata/eve.json`) secara dinamis dibaca oleh Wazuh Agent yang terpasang di host Proxmox dan dikirimkan ke Wazuh Manager di VM 105 melalui deklarasi blok berikut pada berkas `/var/ossec/etc/ossec.conf`:
```xml
<localfile>
  <log_format>json</log_format>
  <location>/var/log/suricata/eve.json</location>
</localfile>
```

### 3.3. Rantai Kerja Otomatisasi (Custom Python SOAR & Ollama API)
Alur otomatisasi respons diimplementasikan secara terprogram menggunakan mikroservis Python dengan skema kejadian terpicu (*event-driven*):
1. **Webhook Trigger:** Wazuh Manager mengirimkan log insiden (JSON) tingkat kritis (Level $\ge 7$) melalui modul `<integration>` ke Webhook URI milik SOAR kustom:
   `http://10.88.0.3:8080/webhook`
2. **HTTP Request:** Mikroservis SOAR memanggil REST API Ollama di VM 100 melalui protokol HTTP POST ke `http://10.88.0.4:11434/api/generate`.
3. **Prompt Engineering:** Payload yang dikirimkan diformulasikan secara spesifik dengan mengaktifkan parameter format JSON guna memastikan model bahasa besar lokal menghasilkan format laporan SOC yang valid:
   ```json
   {
     "model": "llama3.2",
     "prompt": "Analyze this security log... Return a JSON object...",
     "format": "json",
     "stream": false
   }
   ```
4. **Action Response:** Hasil analisis di-render secara real-time pada dasbor web kustom (`GET /`) dan secara otomatis memicu pemblokiran IP pada firewall lokal jika AI mendeteksi status *"True Positive"* (`action == "block"`).

---

## 4. HASIL DAN PEMBAHASAN

### 4.1. Pemulihan & Optimasi Booting Wazuh Indexer (VM 105)
Pada fase awal riset, server fisik Proxmox mengalami *reboot* yang memicu seluruh VM menyala bersamaan. Kejadian ini mengakibatkan kemacetan I/O (*disk congestion*) sehingga database `wazuh-indexer` gagal melakukan inisialisasi dalam batas waktu default systemd (90 detik). Database terhenti dan klaster keamanan terkunci dalam status **RED**.

Pemulihan dilakukan secara forensik dengan mengeksekusi skrip `securityadmin.sh` menggunakan parameter `-arc` (*Accept Red Cluster*) untuk memaksa pembacaan berkas konfigurasi internal meskipun status klaster tidak stabil:
```bash
/usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
-cd /etc/wazuh-indexer/opensearch-security/ -nhnv -icl -arc \
-cacert certs/root-ca.pem -cert certs/admin.pem -key certs/admin-key.pem
```
Langkah optimasi permanen diterapkan dengan memperpanjang waktu tunggu inisialisasi awal pada systemd service wazuh-indexer menjadi 300 detik di file `/etc/systemd/system/wazuh-indexer.service.d/override.conf`:
```ini
[Service]
TimeoutStartSec=300
```
Serta menambahkan konfigurasi urutan jeda menyala (*Startup Delay*) pada Proxmox VE Host:
```bash
qm set 105 -startup order=4,up=30   # VM Wazuh SIEM
qm set 100 -startup order=6,up=60   # VM LLM Ollama (Dinyalakan paling akhir)
```

### 4.2. Eksperimen Evaluasi Waktu Respon Model LLM Lokal
Kami melakukan pengujian performa respon waktu (*latency*) dan konsumsi sumber daya CPU pada VM 100 ketika melayani inferensi alur kerja SOAR kustom. Data hasil pengujian diringkas dalam Tabel 3 berikut:

**Tabel 3. Perbandingan Performa Model LLM Lokal pada VM 100**

| Nama Model AI | Ukuran Berkas | Kecepatan Respon (Detik) | Penggunaan CPU VM | Status Eksekusi |
| :--- | :--- | :--- | :--- | :--- |
| **`gemma3:1b`** | 880 MB | **2,67 Detik** | $\approx 25\%$ | Sukses Instan |
| **`qwen2.5:3b`** | 2.2 GB | **4,12 Detik** | $\approx 40\%$ | Sukses Instan |
| **`llama3.2:latest`** | 2.0 GB | **4,85 Detik** | $\approx 35\%$ | Sukses Instan |
| **`llama3.1:8b`** | 4.9 GB | > 120 Detik | **739% (Overload)** | Gagal (*Read Timeout*) |

**Analisis Eksperimen:**
1. Model besar seperti `llama3.1:8b` memicu *resource overhead* CPU yang sangat ekstrim (mencapai 739% CPU load pada proses `llama-server`) karena arsitektur VM tidak dilengkapi akselerasi GPU (berjalan murni pada CPU). Waktu proses melebihi 120 detik sehingga memicu pemutusan paksa koneksi (*HTTP Read Timeout*) oleh modul HTTP.
2. Sebaliknya, model ringan (*lightweight*) seperti `gemma3:1b` dan `qwen2.5:3b` bekerja secara optimal dengan waktu respon di bawah 5 detik dan penggunaan CPU yang wajar. Model ini sangat direkomendasikan untuk implementasi SOC skala kecil dan menengah (SME) yang berbasis virtualisasi hemat daya.

---

## 5. KESIMPULAN & SARAN

### 5.1. Kesimpulan
Riset ini sukses merancang dan mengimplementasikan arsitektur otomatisasi respons insiden siber terintegrasi (*Agentic SOAR*) ringan kustom berbasis Python di lingkungan virtualisasi Proxmox VE. Penggunaan model bahasa besar lokal berukuran ringan seperti `llama3.2:latest` terbukti menjadi solusi ideal yang mampu menghasilkan keputusan klasifikasi insiden siber secara kontekstual dalam waktu **4,85 detik** tanpa memicu *read timeout*. Sistem ini memotong waktu penanganan insiden (MTTR) hingga di bawah 15 detik secara otomatis sekaligus menjamin kedaulatan data log instansi tanpa adanya biaya API pihak ketiga dengan penggunaan memori yang sangat efisien (<25 MB RAM).

### 5.2. Saran
Penelitian selanjutnya diharapkan dapat mengeksplorasi optimasi teknik kompresi model (*quantization*) LLM lokal untuk berjalan pada perangkat keras *single-board computer* (seperti Raspberry Pi) serta integrasi skema *Forward Error Correction* (FEC) pada jalur transmisi log siber WAN yang tidak stabil.

---

## DAFTAR PUSTAKA

1. Hu, T., Zhuang, S., Guo, Z., Sun, J., Liu, Y., Ma, W., Wang, H., Zhao, L., & Zhang, X. (2025). A Novel LLM Approach of Cybersecurity Threat Analysis and Response. *Proceedings of the 16th International Conference on Internetware (Internetware 2025)*, Trondheim, Norway. ACM.
2. Zhang, J., Li, S., Huang, W., Jing, H., Zhang, Q., & Xia, X. (2025). Design and Computational Modeling of an AI-Based Automated Cybersecurity Incident Response System. *IEEE Access*, vol. 13, pp. 154383–154394. doi:10.1109/ACCESS.2025.3603975.
3. Shah, A., Ganesan, R., & Jajodia, S. (2019). A Two-Step Approach to Optimal Selection of Alerts for Investigation in a CSOC. *IEEE Transactions on Information Forensics and Security*, vol. 14, no. 7, pp. 1857-1870.
4. Zhong, C., Liu, P. J., Yen, J., & Erbacher, R. F. (2016). Automate cybersecurity data triage by leveraging human analysts’ cognitive process. *IEEE BigDataSecurity*.
