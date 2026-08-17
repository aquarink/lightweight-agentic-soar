# Experimental Testbed and Implementation Setup

Evaluasi performa arsitektur perutean bypass lokal (*local-bypass*) dan daemon *event-driven* dilakukan menggunakan *testbed* hibrida yang mengintegrasikan kluster virtualisasi lokal (*on-premises*) dengan *Cloud* publik.

## 1. Spesifikasi Hypervisor Fisik (Bare-Metal Host)
Kluster *private cloud* lokal didirikan di atas server fisik (*bare-metal*) yang dikonfigurasi sebagai *hypervisor* menggunakan platform **Proxmox Virtual Environment (PVE)**. Detil spesifikasi perangkat keras dan sistem operasi inang adalah sebagai berikut:
* **Prosesor**: Intel(R) Xeon(R) Gold 5218 CPU @ 2.30GHz, dikonfigurasi dalam arsitektur dual-socket (2 CPU fisik), dengan 16 cores per socket (total 32 physical cores) dan *Hyper-Threading* diaktifkan (total 64 logical threads/logical CPUs).
* **Memori RAM**: 125 GiB (~128 GB) DDR4 ECC.
* **Sistem Operasi / Hypervisor**: Proxmox VE dengan pve-manager/9.2.2/b9984c6d90a4bd80 berbasis kernel khusus inang `Linux 7.0.2-6-pve` (x86_64).
* **Jaringan Virtual**: Satu Layer 2 virtual switch (Linux Bridge `vmbr0`) yang menghubungkan seluruh antarmuka jaringan VM melalui *driver* virtualisasi `virtio_net`.

## 2. Alokasi Sumber Daya Virtual Machine (Local VMs)
Di dalam inang Proxmox, tiga Virtual Machine (VM) bertindak sebagai *Spokes* lokal utama yang menjalankan tumpukan aplikasi. Semua VM menggunakan sistem operasi Ubuntu Server 22.04 LTS (kernel Linux 5.15.0) dengan alokasi sumber daya sebagai berikut:
* **VM Web (layanan - VMID 102)**: Dialokasikan 4 vCPU (dengan tipe CPU passthrough `host`), 8192 MB (8 GB) RAM, dan 100 GB ruang penyimpanan SCSI (berbasis `virtio-scsi-single` dengan opsi `iothread=1`). Bertindak sebagai server aplikasi web.
* **VM Web/Application Node (obe - VMID 103)**: Dialokasikan 4 vCPU (`host`), 8192 MB (8 GB) RAM, dan 100 GB penyimpanan SCSI. Bertindak sebagai server pemrosesan aplikasi terdistribusi.
* **VM Database & Cache (db - VMID 104)**: Dialokasikan 4 vCPU (`host`), 8192 MB (8 GB) RAM, dan 200 GB penyimpanan SCSI. VM ini menjalankan PostgreSQL 15 dan Redis Server 7.0.

## 3. Spesifikasi Cloud VPS Hub (WireGuard Gateway)
Untuk melengkapi topologi hibrida *Hub-and-Spoke*, sebuah Virtual Private Server (VPS) publik disewa sebagai *Hub* pusat untuk merutekan lalu lintas data di luar kluster lokal:
* **Penyedia Cloud**: AWS EC2 instance type `t3.medium` berlokasi di wilayah regional `ap-southeast-1` (Singapura).
* **Spesifikasi Virtual**: 2 vCPU Intel Xeon, 4 GiB RAM, 40 GB SSD Storage.
* **Sistem Operasi**: Ubuntu Server 22.04 LTS dengan IP Publik statis khusus.
* **Perangkat Lunak VPN**: WireGuard VPN versi kernel-space bawaan.

## 4. Pengaturan Perangkat Lunak Uji
* **Database Stress Test**: `pgbench` (PostgreSQL benchmark tool) dikonfigurasi untuk menjalankan simulasi hingga 20-100 koneksi bersamaan ke VM DB.
* **HTTP Performance Test**: `wrk` load-tester dijalankan dari VPS publik atau VM penguji dengan konfigurasi 20 klien konkuren menggunakan skrip lua dinamis.
* **Network Monitoring**: `mtr` (My Traceroute) dan `iperf3` untuk mengukur RTT latensi, jitter, packet loss, dan throughput *data plane* lokal.
* **Control Plane Daemon**: Python 3.10 minimal yang memicu raw Netlink sockets pada kernel space untuk memprogram ulang rute.
