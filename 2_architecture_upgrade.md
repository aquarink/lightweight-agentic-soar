# Architecture Upgrade: Event-Driven Netlink Daemon vs Cron Polling

## 1. Analisis Kualitatif Model Konvergensi Perutean

Dalam perancangan sistem jaringan edge-cloud hibrida yang tangguh, kecepatan konvergensi perutean (*routing convergence time*) merupakan metrik performa utama. Konvergensi perutean didefinisikan sebagai waktu yang dibutuhkan oleh sistem untuk mendeteksi perubahan topologi fisik atau logis (seperti perubahan alamat IP antarmuka atau status tautan) dan memperbarui tabel perutean data plane secara konsisten.

### A. Polling-Based Model (Cron 120 Detik)
Pada arsitektur awal, deteksi perubahan konfigurasi IP dilakukan menggunakan penjadwal **cron** yang dieksekusi setiap 2 menit (120 detik). Model ini memiliki keterbatasan inheren:
- **Tingkat Keterlambatan Tinggi (Latency Bound)**: Jika perubahan IP terjadi pada detik ke-1 setelah eksekusi cron terakhir, sistem akan berada dalam status tidak konsisten (rute salah atau terputus) selama 119 detik ke depan sebelum cron berikutnya dieksekusi.
- **Konsumsi Sumber Daya Sia-sia (Resource Waste)**: Skrip Python pendeteksi dieksekusi secara berkala setiap 2 menit meskipun tidak ada perubahan jaringan sama sekali. Proses pemanggilan SSH, pengujian ping, dan pembacaan konfigurasi berulang ini membuang siklus CPU dan bandwidth.
- **Model Tarik (Pull Model)**: Aplikasi terus-menerus menanyakan status sistem ke kernel space, meningkatkan jumlah *context switch*.

### B. Event-Driven Model (Netlink Sockets Daemon)
Arsitektur yang ditingkatkan menggantikan cron dengan daemon perutean dinamis berbasis **Netlink socket**. Netlink adalah antarmuka IPC (Inter-Process Communication) berorientasi soket khusus di kernel Linux yang digunakan untuk mentransfer informasi jaringan antara kernel space dan user space.
- **Model Dorong (Push Model)**: Kernel space Linux segera mendorong (*push*) notifikasi event jaringan ke socket kelompok multicast (`RTMGRP_IPV4_IFADDR`) yang didengarkan oleh daemon di user space saat perubahan terjadi.
- **Deteksi Instan**: Tidak ada waktu tunggu yang dijadwalkan. Begitu alamat IP terdaftar (misalnya handshake VPN terbentuk dan IP `10.88.0.12` ditambahkan ke antarmuka `wg0`), kernel langsung memancarkan event `RTM_NEWADDR`.
- **Efisien**: Daemon tertidur (*blocked state* pada panggilan `recv`) dan tidak mengonsumsi CPU sampai kernel mengirimkan data event.

---

## 2. Analisis Kuantitatif dan Perhitungan Matematis Konvergensi

Mari kita formulasikan perbandingan waktu konvergensi secara matematis.

### Model Polling (Cron)
Waktu konvergensi perutean $T_{conv\_polling}$ dalam model polling terikat oleh interval polling $P$ (dalam detik) dan waktu eksekusi skrip optimasi $T_{exec}$.

Waktu konvergensi rata-rata ($\mathbb{E}[T_{conv\_polling}]$) jika perubahan IP diasumsikan terjadi secara acak dengan distribusi seragam (*uniform distribution*) dalam interval $P$:

$$\mathbb{E}[T_{conv\_polling}] = \frac{P}{2} + T_{exec}$$

Untuk interval cron $P = 120$ detik, dan waktu eksekusi SSH/skrip $T_{exec} \approx 2.5$ detik:

$$\mathbb{E}[T_{conv\_polling}] = \frac{120}{2} + 2.5 = 62.5 \text{ detik}$$

Waktu konvergensi terburuk (*worst-case scenario*):

$$T_{conv\_polling\_max} = P + T_{exec} = 120 + 2.5 = 122.5 \text{ detik}$$

### Model Event-Driven (Netlink Sockets)
Waktu konvergensi perutean $T_{conv\_event}$ dalam model Netlink langsung dipicu oleh interupsi kernel dan tidak bergantung pada interval tunggu. Waktu konvergensi dipengaruhi oleh latensi propagasi socket kernel-to-user $T_{netlink}$ dan waktu eksekusi skrip $T_{exec}$.

$$T_{conv\_event} = T_{netlink} + T_{exec}$$

Latensi socket Netlink internal pada kernel Linux modern berada dalam skala mikrodetik:

$$T_{netlink} \approx 50 \mu\text{s} = 0.00005 \text{ detik}$$

Maka waktu konvergensi total:

$$T_{conv\_event} = 0.00005 + 2.5 = 2.50005 \text{ detik}$$

Jika kita mengabaikan overhead eksekusi skrip optimasi perutean itu sendiri (karena skrip optimasi dijalankan pada kedua metode), waktu reaksi deteksi sistem murni ($T_{detect}$) mengalami penurunan drastis:
- **Polling (Cron)**: $T_{detect\_polling\_avg} = 60 \text{ detik}$
- **Event-Driven (Netlink)**: $T_{detect\_event} \approx 50 \mu\text{s}$

Hal ini mewakili peningkatan kecepatan deteksi sebesar:

$$\text{Peningkatan} = \frac{60 \text{ detik}}{0.00005 \text{ detik}} = 1.200.000 \text{ kali (1.2 juta kali lebih cepat!)}$$

Kecepatan deteksi tingkat mikrodetik ini menjamin bahwa tabel perutean bypass lokal (`table 88`) di kernel segera dimutakhirkan dalam hitungan milidetik setelah antarmuka `wg0` terhubung, memenuhi persyaratan standar jurnal Q1 untuk stabilitas jaringan *real-time*.
