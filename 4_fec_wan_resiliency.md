# Forward Error Correction (FEC) for WAN Resiliency in Hybrid Edge-Clouds

## 1. Tantangan Kehilangan Paket (Packet Loss) pada Jaringan WAN

Meskipun metode perutean bypass lokal (*local-bypass*) yang kami usulkan berhasil memecahkan masalah latensi dan throughput di sisi LAN (intranet lokal kluster Proxmox), lalu lintas data yang melintasi jaringan internet publik (WAN) menuju VPS publik tetap menghadapi tantangan klasik: **kehilangan paket (packet loss) dan jitter**.

Jalur WAN publik sering kali mengalami kemacetan (*network congestion*), yang mengakibatkan paket drop pada router perantara. Pada terowongan VPN seperti WireGuard yang menggunakan protokol transport UDP, kehilangan paket data akan berdampak langsung pada lapisan transport di atasnya (seperti TCP). Kehilangan satu segmen TCP akan memicu mekanisme transmisi ulang (*TCP retransmission*) dan memicu efek **Head-of-Line (HOL) blocking**. Hal ini melipatgandakan latensi (Round Trip Time, RTT) secara eksponensial dan memotong throughput TCP secara drastis melalui algoritma kontrol kemacetan (*congestion control*).

---

## 2. Implementasi Reed-Solomon Forward Error Correction (FEC)

Untuk mengatasi hilangnya keandalan pada jalur WAN, kami mengintegrasikan konsep **Reed-Solomon Forward Error Correction (FEC)** (mengadopsi teknologi seperti *UDPspeeder*) di atas terowongan WireGuard untuk lalu lintas WAN.

### A. Prinsip Kerja Matematika FEC (N, K)
FEC bekerja dengan menambahkan informasi redundansi (paket paritas) ke dalam aliran data asli sebelum dikirimkan ke jaringan WAN. Skema FEC didefinisikan sebagai $(N, K)$, di mana:
- $K$: Jumlah paket data asli yang dikirim.
- $R$: Jumlah paket redundansi (paritas) tambahan.
- $N = K + R$: Total paket yang dikirimkan ke jaringan.

Menggunakan pengodean Reed-Solomon, penerima dapat memulihkan (merekonstruksi) hingga $R$ paket yang hilang dari total $N$ paket yang diterima secara *real-time* tanpa perlu mengirimkan permintaan transmisi ulang (ACK/NACK) ke pengirim.

Secara matematis, probabilitas kegagalan pengiriman paket (yaitu ketika jumlah paket yang hilang di jaringan $x$ melebihi jumlah paritas $R$) dengan tingkat packet loss jalur WAN dasar $p$ adalah:

$$P_{fail} = \sum_{x=R+1}^{N} \binom{N}{x} p^x (1-p)^{N-x}$$

### B. Studi Kasus Reduksi Packet Loss
Misalkan jalur internet WAN publik memiliki packet loss dasar yang sangat buruk sebesar **$p = 10\%$ ($0.10$)**. Kita menerapkan skema FEC $(10, 4)$ di atas terowongan WireGuard (mengirimkan 4 paket paritas untuk setiap 10 paket data).
- Total paket $N = 14$
- Paket data asli $K = 10$
- Paket redundansi $R = 4$

Probabilitas kegagalan rekonstruksi paket ($P_{fail}$) setelah FEC diterapkan:

$$P_{fail} = \sum_{x=5}^{14} \binom{14}{x} (0.1)^x (0.9)^{14-x}$$

Mari kita hitung nilai probabilitas kumulatif untuk $x \ge 5$:

- Untuk $x=5$: $\binom{14}{5} (0.1)^5 (0.9)^9 = 2002 \times 0.00001 \times 0.38742 \approx 0.00775$
- Untuk $x=6$: $\binom{14}{6} (0.1)^6 (0.9)^8 = 3003 \times 0.000001 \times 0.43046 \approx 0.00129$
- Untuk $x=7$: $\binom{14}{7} (0.1)^7 (0.9)^7 = 3432 \times 10^{-7} \times 0.47829 \approx 0.00016$

Jika kita menjumlahkan seluruh probabilitas dari $x=5$ hingga $14$:

$$P_{fail} \approx 0.0092 \text{ atau } 0.92\%$$

Dengan menerapkan FEC $(10, 4)$, tingkat kehilangan paket efektif yang dirasakan oleh aplikasi pada sisi WAN turun drastis dari **$10\%$ menjadi hanya $0.92\%$** (penurunan kerusakan paket hingga **10.8 kali lipat**).

---

## 3. Sinergi Dual-Plane untuk Hybrid Cloud Resilient

Dengan menggabungkan kedua metode ini, kita menciptakan arsitektur **Dual-Plane Resilient Hybrid Cloud**:

```
                       ┌───────────────────────────────┐
                       │    HYBRID EDGE-CLOUD WAN      │
                       │  WireGuard + Reed-Solomon FEC │
                       │    Loss: 10% ──> 0.92% (WAN)  │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │     LOCAL HYPERVISOR LAN      │
                       │  Decentralized SDN L2 Bypass  │
                       │    Latency: 0.4 ms (LAN)      │
                       └───────────────────────────────┘
```

1. **Sisi Intranet Lokal (LAN)**: Skrip/daemon SDN bypass lokal memastikan bahwa trafik VM-to-VM yang padat (seperti transaksi database PostgreSQL atau replikasi penyimpanan MinIO) dialihkan sepenuhnya melewati rute terpendek L2 virtual switch. Latensi dipertahankan pada **0.4 ms** dengan **0% packet loss**.
2. **Sisi Internet Publik (WAN)**: Enkapsulasi FEC pada terowongan WireGuard memastikan bahwa lalu lintas kontrol, sinkronisasi data jarak jauh, dan komunikasi agen eksternal terlindungi dari drop paket di internet publik tanpa memicu overhead retransmisi TCP.

Sinergi ini memastikan bahwa kluster edge-cloud hibrida Proxmox tidak hanya memiliki performa secepat jaringan LAN lokal untuk beban kerja lokalnya, tetapi juga tetap tangguh (*resilient*) terhadap gangguan fisik di jaringan WAN luar.
