# Future Works: Transitioning to eBPF and XDP Data Paths

Sebagai bagian dari pengembangan berkelanjutan untuk mencapai optimasi performa jaringan yang lebih radikal pada arsitektur *Hybrid Edge-Cloud*, penelitian di masa depan akan difokuskan pada transisi mekanisme kontrol perutean dari daemon berbasis soket Netlink ke arsitektur **eBPF (Extended Berkeley Packet Filter)** dan **XDP (eXpress Data Path)** di tingkat kernel space Linux.

## 1. Keterbatasan Pendekatan Netlink Sockets Saat Ini
Meskipun arsitektur kontroler SDN berbasis soket Netlink yang diajukan dalam penelitian ini mampu mencapai waktu konvergensi deteksi tingkat mikrodetik ($50\,\mu\text{s}$) di *user space*, ia masih menghadapi beberapa batasan *data plane* yang melekat pada tumpukan jaringan (*networking stack*) kernel Linux standar:
* **Overhead Pemrosesan Stack Jaringan**: Paket bypass lokal yang masuk ke antarmuka `ens18` tetap harus melewati seluruh lapisan stack jaringan kernel Linux, termasuk alokasi struktur data `sk_buff` (*socket buffer*), evaluasi rantai aturan firewall Netfilter (iptables/nftables), serta pencarian rute pada *routing policy database* (RPDB).
* **Context Switch**: Ketika daemon Netlink mendeteksi event, ia memicu proses eksekusi skrip eksternal di *user space* yang melakukan pemanggilan perintah sistem `ip route`. Hal ini menimbulkan overhead pergantian konteks (*context switch*) antara *kernel space* dan *user space*.

## 2. Solusi Berbasis eBPF dan XDP
Integrasi eBPF dan XDP di masa depan ditujukan untuk mengatasi hambatan tersebut dengan memindahkan logika keputusan perutean bypass lokal langsung ke lapisan terbawah kernel, bahkan sebelum sistem operasi mengalokasikan memori untuk paket masuk:

```
                            [ Antarmuka Fisik (NIC) ]
                                        │
                                        ▼
                            [ XDP / eBPF Program ]  <── Redirection & L2 Bypass
                                        │               (Tanpa alokasi sk_buff)
                       ┌────────────────┴────────────────┐
                       │ (Bypass Lokal)                  │ (Trafik WAN)
                       ▼                                 ▼
           [ Direct Redirection ]             [ Linux TCP/IP Stack ]
           (Ke Virtual Interface VM)                     │
                                                         ▼
                                                [ WireGuard (wg0) ]
```

* **eXpress Data Path (XDP)**: Program XDP yang ditulis dalam kode C terkompilasi akan disuntikkan secara dinamis langsung ke penggerak kartu jaringan virtual (*virtio-net NIC driver*). Program ini akan mengevaluasi setiap paket masuk pada level Layer 2. Jika paket membawa IP tujuan lokal (subnet `10.88.0.0/24`), program XDP akan memodifikasi alamat MAC tujuan dan segera mengalihkan paket tersebut ke antarmuka VM tujuan menggunakan aksi `XDP_REDIRECT`.
* **Bypass Stack Jaringan Kernel Secara Penuh**: Pengalihan paket melalui `XDP_REDIRECT` melompati alokasi `sk_buff`, pencarian tabel perutean kernel, dan pemrosesan firewall global. Hal ini memangkas overhead pemrosesan per-paket secara signifikan, memungkinkan pencapaian latensi intra-hypervisor yang mendekati batas fisik perangkat keras inang ($< 0.1 \text{ ms}$) dan membebaskan siklus CPU virtual VM dari tumpukan instruksi jaringan.
* **Manajemen Peta Dinamis (eBPF Maps)**: Manajemen topologi IP tidak lagi memerlukan eksekusi skrip eksternal. Daemon kontroler SDN akan memperbarui tabel pemetaan IP-ke-MAC secara langsung pada memori bersama kernel-user (*eBPF Maps*), memangkas waktu pemutakhiran perutean ke skala nanodetik tanpa memerlukan *context switch*.

Transisi ke paradigma eBPF/XDP ini diharapkan tidak hanya menurunkan latensi pemrosesan paket lebih lanjut, tetapi juga meminimalkan konsumsi daya CPU hypervisor pada skenario lalu lintas data padat (skala multi-gigabit hingga terabit), menjadikannya kandidat arsitektur ideal untuk infrastruktur *edge computing* masa depan yang sangat hemat energi.
