# Mathematical Modeling and Empirical Evidence of Cryptographic Bottleneck Mitigation in WireGuard Hybrid Clouds

Dokumen ini menyajikan pemodelan matematika formal untuk waktu pemrosesan kriptografi ($T_{crypto}$), perhitungan tingkat pengiriman paket (*Packets per Second*, PPS), serta analisis beban instruksi CPU untuk enkripsi/dekripsi ChaCha20-Poly1305 pada terowongan WireGuard. Bukti ini mendasari klaim efisiensi dari arsitektur *Local-Bypass* Layer 2 yang diusulkan.

## 1. Pemodelan Waktu Pemrosesan Kriptografi ($T_{crypto}$)
Pada arsitektur VPN tradisional (Trombone Routing), setiap paket yang mengalir melalui antarmuka virtual WireGuard (`wg0`) wajib melalui proses enkripsi di pengirim dan dekripsi di penerima menggunakan algoritma AEAD **ChaCha20-Poly1305**. 

Total waktu pemrosesan kriptografi per detik ($T_{crypto}$) pada sistem operasi dapat dimodelkan sebagai berikut:

$$T_{crypto} = PPS \times \left( T_{chacha20}(S) + T_{poly1305}(S) + T_{overhead} \right)$$

Di mana:
- $PPS$: Jumlah paket data yang diproses per detik (*Packets Per Second*).
- $S$: Ukuran paket data dalam byte (di mana $S \le \text{MTU}$).
- $T_{chacha20}(S)$: Waktu yang dibutuhkan untuk enkripsi/dekripsi payload ukuran $S$ menggunakan algoritma cipher ChaCha20.
- $T_{poly1305}(S)$: Waktu yang dibutuhkan untuk membangkitkan/memverifikasi tag otentikasi MAC berukuran 16-byte menggunakan Poly1305.
- $T_{overhead}$: Waktu tambahan sistem operasi (inisialisasi enkapsulasi, alokasi memori buffer socket `sk_buff`, context switch kernel-user, pemanggilan interupsi *softirq*).

Waktu operasi ChaCha20 dan Poly1305 merupakan fungsi linier terhadap ukuran paket $S$ yang bergantung pada efisiensi CPU inang ($\text{cycles per byte}$, $\theta$):

$$T_{chacha20}(S) + T_{poly1305}(S) = \frac{S \times \theta}{f_{core}}$$

Di mana:
- $\theta$: Jumlah siklus clock CPU rata-rata yang dibutuhkan untuk memproses satu byte data ($\text{cycles/byte}$).
- $f_{core}$: Frekuensi clock core CPU yang memproses paket (dalam Hz).

## 2. Perhitungan Tingkat Pengiriman Paket (Packets Per Second - PPS)
Hubungan antara *throughput* data plane lokal $Th$ (dalam Gigabit per detik, Gbps) dan ukuran paket $S$ (dalam Byte) terhadap nilai $PPS$ dirumuskan sebagai:

$$PPS = \frac{Th \times 10^9}{8 \times S}$$

Berdasarkan hasil pengujian benchmark aktual, throughput lokal puncak ketika bypass dinonaktifkan (via WireGuard) adalah **$Th_{before} = 64,8 \text{ Mbps}$**, sedangkan setelah bypass lokal diaktifkan melonjak hingga **$Th_{after} = 23,5 \text{ Gbps}$**.

Mari lakukan komparasi kebutuhan PPS untuk memproses throughput ini pada dua skenario ukuran paket ($S$):

### Skenario A: Paket Standar Ethernet (MTU = 1500 Byte, WireGuard MTU = 1420 Byte)
Untuk lalu lintas payload besar (misalnya transfer basis data PostgreSQL/replikasi file):
* **Sebelum Bypass (64,8 Mbps via WireGuard)**:
  $$PPS_{before} = \frac{64,8 \times 10^6 \text{ bps}}{8 \times 1420 \text{ Byte}} \approx 5.704 \text{ paket/detik}$$
* **Setelah Bypass (23,5 Gbps via L2 Local Bypass)**:
  $$PPS_{after} = \frac{23,5 \times 10^9 \text{ bps}}{8 \times 1500 \text{ Byte}} \approx 1.958.333 \text{ paket/detik (1,96 MPPS)}$$

### Skenario B: Paket Kecil / Skenario Terburuk (S = 64 Byte)
Untuk lalu lintas pesan kontrol, TCP ACK, atau query caching Redis berukuran kecil:
* **Sebelum Bypass (64,8 Mbps via WireGuard)**:
  $$PPS_{before\_small} = \frac{64,8 \times 10^6 \text{ bps}}{8 \times 64 \text{ Byte}} \approx 126.562 \text{ paket/detik}$$
* **Setelah Bypass (23,5 Gbps via L2 Local Bypass)**:
  $$PPS_{after\_small} = \frac{23,5 \times 10^9 \text{ bps}}{8 \times 64 \text{ Byte}} \approx 45.898.437 \text{ paket/detik (45,90 MPPS)}$$

## 3. Estimasi Penghematan Siklus Instruksi CPU (CPU Core Offloading)
Pada prosesor kelas enterprise **Intel Xeon Gold 5218** (2.30 GHz base clock, AVX-512 enabled) yang menjadi inang *experimental testbed*, biaya instruksi rata-rata untuk modul kriptografi WireGuard teroptimasi kernel-space adalah **$\theta \approx 1.5 \text{ cycles/byte}$**.

Mari kita hitung total kebutuhan frekuensi CPU ($F_{cpu}$) murni untuk memproses enkripsi/dekripsi lalu lintas data lokal jika dipaksa melewati VPN WireGuard pada throughput puncak $23.5 \text{ Gbps}$:

$$F_{cpu} = Th \times 10^9 \text{ bps} \times \frac{1}{8} \text{ Byte/bit} \times \theta \text{ cycles/Byte}$$

Substitusikan parameter puncak:

$$F_{cpu} = 23,5 \times 10^9 \times \frac{1.5}{8} = 4.406.250.000 \text{ Hz} \approx 4,41 \text{ GHz}$$

Karena frekuensi base clock dari satu core CPU Intel Xeon Gold 5218 adalah **$2,3 \text{ GHz}$**, maka daya pemrosesan yang dibutuhkan murni untuk kalkulasi kriptografi WireGuard pada bandwidth $23,5 \text{ Gbps}$ adalah:

$$\text{Kebutuhan Core CPU} = \frac{4,41 \text{ GHz}}{2,3 \text{ GHz}} \approx 1,92 \text{ Cores}$$

Artinya, jika lalu lintas data lokal sebesar 23,5 Gbps dipaksa melalui enkripsi WireGuard (Trombone Routing):
1. **Hampir 2 Core CPU fisik (100% load)** pada hypervisor akan terkonsumsi habis hanya untuk menjalankan fungsi enkripsi/dekripsi ChaCha20-Poly1305.
2. Karena WireGuard menggunakan antarmuka *single-queue* secara default pada kernel space untuk alokasi thread per-peer, limitasi kinerja akan mentok pada kapasitas batas *single-core frequency* inang (kematian performa jaringan akibat bottleneck CPU).

Dengan diterapkannya **L2 Local Bypass**, aliran paket dialihkan sepenuhnya ke Layer 2 virtual switch (`vmbr0`). Karena lalu lintas data dikirimkan tanpa enkapsulasi WireGuard:

$$T_{crypto\_local} \to 0$$

Hasil pengalihan ini berhasil membebaskan resource CPU hingga **4,41 GHz (Offload ~2 CPU Cores secara penuh)**. Siklus CPU berharga ini didelegasikan kembali ke tugas-tugas kritis aplikasi inang (seperti kalkulasi relasional PostgreSQL atau pemrosesan session cache Redis), yang berdampak langsung pada kenaikan performa transaksional aplikasi secara agregat.
