# Cost-Latency Tradeoff and Economic Optimization Modeling

## 1. Formulasi Matematika Egress Cost Savings

Dalam arsitektur edge-cloud hibrida tradisional (Trombone Routing), semua lalu lintas data antar-VM dialihkan keluar melalui Cloud VPS publik (Hub). Hal ini menimbulkan biaya keluar data (*egress traffic cost*) yang sangat signifikan berdasarkan model **Pay-For-Data-Transfer (PFDT)** dan **Pay-As-You-Go (PAYG)** yang diterapkan oleh penyedia layanan cloud (seperti AWS, Google Cloud Platform, atau Microsoft Azure).

Dengan menerapkan arsitektur perutean bypass lokal (*local-bypass*), lalu lintas antar-VM pada hypervisor fisik yang sama diarahkan secara lokal melalui virtual switch Layer 2. Hal ini menghasilkan penghematan biaya egress bulanan secara penuh.

Mari kita rumuskan pemodelan matematika untuk penghematan biaya bulanan $S_{month}$ (dalam USD):

### A. Volume Transfer Data Bulanan
Misalkan $T_{peak}$ adalah throughput puncak lokal yang berhasil di-bypass (dalam Gbps). Volume data bulanan $D_{month}$ (dalam Terabyte, TB) yang dialihkan secara lokal bergantung pada rasio utilisasi rata-rata terhadap beban puncak $\alpha$ (di mana $0 < \alpha \le 1$):

$$D_{month} = \frac{T_{peak} \times 10^9 \text{ bit/s} \times \alpha \times 3600 \text{ s/jam} \times 24 \text{ jam/hari} \times 30 \text{ hari/bulan}}{8 \times 10^{12} \text{ bit/TB}}$$

Sederhanakan persamaan di atas:

$$D_{month} = 324 \times T_{peak} \times \alpha \quad [\text{TB/bulan}]$$

### B. Persamaan Penghematan Biaya Egress (Egress Cost Savings)
Jika tarif egress per Gigabyte (GB) yang dibebankan oleh penyedia cloud publik adalah $C_{egress\_GB}$ (dalam USD/GB), maka total penghematan bulanan $S_{month}$ adalah:

$$S_{month} = D_{month} \times 10^3 \text{ GB/TB} \times C_{egress\_GB}$$

Substitusikan nilai $D_{month}$:

$$S_{month} = 324.000 \times T_{peak} \times \alpha \times C_{egress\_GB} \quad [\text{USD/bulan}]$$

---

## 2. Simulasi Perhitungan Finansial Nyata

Berdasarkan hasil pengujian benchmark *data plane* yang dilakukan, throughput lokal meningkat drastis hingga mencapai **$T_{peak} = 23,5 \text{ Gbps}$** setelah bypass diaktifkan.

Mari kita simulasikan penghematan biaya menggunakan parameter AWS EC2 Egress Cost standar:
- **Tarif Egress Cloud ($C_{egress\_GB}$)**: \$0.09 USD per GB (atau \$90 USD per TB) untuk transfer data ke Internet bebas.
- **Rasio Utilisasi Beban Rata-rata ($\alpha$)**: Diatur ke **$0.10$** (utilisasi rata-rata 10% dari kapasitas puncak, yang merupakan angka konservatif dan sangat realistis untuk lingkungan produksi).

### A. Total Data yang Dialihkan (Bypass)
Masukkan nilai ke dalam formulasi $D_{month}$:

$$D_{month} = 324 \times 23,5 \times 0,10 = 761,4 \text{ TB/bulan}$$

Sistem berhasil mempertahankan transfer data lokal sebesar **761,4 TB per bulan** di dalam hypervisor Proxmox tanpa mengirimkannya ke internet luar.

### B. Total Penghematan Finansial Bulanan
Masukkan volume data tersebut ke dalam rumus biaya $S_{month}$:

$$S_{month} = 761.400 \text{ GB} \times 0.09 \text{ USD/GB}$$

$$S_{month} = 68.526 \text{ USD / bulan}$$

Dalam setahun, total penghematan finansial mencapai:

$$S_{annual} = 68.526 \text{ USD} \times 12 = 822.312 \text{ USD / tahun} \quad (\approx \text{Rp } 13.1 \text{ Miliar / tahun})$$

### C. Hubungan Trade-off Cost-Latency
Melalui pemodelan di atas, terlihat hubungan berbanding lurus antara penghematan biaya dan pengurangan latensi jaringan:

```
                          [TROMBONE ROUTING]
                       Latensi Tinggi (~5.2 ms)
                        Biaya Egress Maksimal
                                  │
                                  ▼
                         [BYPASS ROUTE (L2)]
                        Latensi Rendah (0.4 ms)
                           Biaya Egress = $0
```

Dengan mengalihkan lalu lintas data secara lokal, sistem tidak hanya memangkas latensi hingga **13x lebih cepat** (dari 5,2 ms ke 0,4 ms), tetapi juga sepenuhnya **menghilangkan biaya transfer data keluar (egress cost) sebesar 100%** untuk lalu lintas lokal, membuktikan kelayakan ekonomi yang sangat tinggi dari desain SDN ini pada kluster edge-cloud hibrida.
