# Catatan Panduan: Penerapan untuk VM Baru (Internal & Eksternal)

Dokumen ini menjelaskan langkah-langkah konfigurasi apabila terdapat penambahan Virtual Machine (VM) baru di dalam topologi hybrid Anda, agar sistem optimasi routing lokal tetap berjalan dengan benar.

---

## Skenario A: Penambahan VM Baru di INTERNAL Proxmox (Satu Hypervisor)

Jika VM baru tersebut berada di dalam server Proxmox yang sama dan kartu jaringannya terhubung ke bridge lokal (`vmbr0`), Anda dapat memasukkannya ke dalam sistem optimasi lokal agar komunikasi ke VM DB/Redis/MinIO langsung mengalir via jalur lokal (< 0.5 ms) secara otomatis.

### Langkah-langkah Penerapan:

1. **Dapatkan MAC Address VM Baru:**
   * Di host Proxmox, baca file konfigurasi VM baru tersebut untuk mendapatkan MAC address kartu jaringan lokal (`net0` yang terhubung ke `vmbr0`).
   * Misalkan VM baru tersebut memiliki VM ID `105`:
     ```bash
     cat /etc/pve/qemu-server/105.conf | grep net0
     ```
     *Contoh output:* `net0: virtio=BC:24:11:AA:BB:CC,bridge=vmbr0,...`

2. **Daftarkan VM Baru di Skrip Python:**
   * Edit berkas skrip `/root/optimize_local_routing.py` di host Proxmox.
   * Tambahkan profil VM baru tersebut ke dalam list `vms` di bagian atas berkas:
     ```python
     {
         "name": "VM (105) - Layanan Baru",
         "mac": "bc:24:11:aa:bb:cc", # MAC address ens18 VM baru (huruf kecil)
         "wg_ip": "10.88.0.12",       # IP WireGuard statis yang dialokasikan di wg0
         "user": "username_ssh",      # Username SSH VM baru
         "password": "password_ssh"   # Password SSH VM baru
     }
     ```

3. **Prasyarat pada VM Baru:**
   * Pastikan service SSH (`sshd`) aktif di VM baru pada port `22`.
   * Pastikan user SSH tersebut memiliki hak akses `sudo` tanpa memerlukan interaksi prompt tambahan (gunakan password yang didaftarkan di skrip).
   * Pastikan WireGuard (`wg0`) sudah terkonfigurasi dan aktif di VM baru tersebut.

4. **Jalankan Skrip/Tunggu Cron Job:**
   * Anda bisa langsung mengeksekusi skrip di host Proxmox untuk instan konfigurasi:
     ```bash
     /root/optimize_local_routing.py
     ```
   * Atau, Anda cukup menunggu maksimal 2 menit karena cron job di Proxmox akan mendeteksi VM baru tersebut, mencari IP DHCP lokalnya, dan secara otomatis menyuntikkan rute bypass lokal dari dan ke VM baru tersebut ke seluruh VM aktif lainnya.

---

## Skenario B: Penambahan VM Baru di EKSTERNAL (Di Luar Proxmox)

Jika VM baru berada di luar server fisik Proxmox Anda (misalnya di Cloud AWS, DigitalOcean, atau server fisik di kantor cabang/lokasi lain), VM tersebut **hanya** terhubung melalui internet via VPN WireGuard (`wg0`) ke VPS.

### Langkah-langkah & Konsep Penerapan:

1. **Kenapa Tidak Dimasukkan ke Skrip Python?**
   * VM Eksternal **tidak memiliki** koneksi fisik/Layer 2 ke bridge `vmbr0` Proxmox. Oleh karena itu, lalu lintas datanya **tidak bisa dibelokkan secara lokal**.
   * Anda **TIDAK PERLU** mendaftarkan VM eksternal ini ke dalam list `vms` pada berkas `/root/optimize_local_routing.py`.

2. **Bagaimana Cara VM Eksternal Mengakses Database/Redis?**
   * Di dalam berkas `.env` aplikasi Laravel pada VM Eksternal, Anda tetap mengonfigurasi host database ke IP WireGuard statis VM DB:
     ```env
     DB_HOST=10.88.0.7
     REDIS_HOST=10.88.0.7
     ```
   * Karena WireGuard di VM DB (`10.88.0.7`) dikonfigurasi untuk mendengarkan di interface `wg0`, paket dari VM eksternal akan diterima dan didekripsi dengan aman secara normal via internet.

3. **Bagaimana Rute Balik dari VM DB ke VM Eksternal?**
   * Karena VM Eksternal tidak terdaftar di skrip Python, VM DB **tidak memiliki** rute bypass lokal `/32` khusus untuk IP VM Eksternal tersebut di tabel routing-nya.
   * Akibatnya, ketika VM DB mengirimkan paket balasan, paket tersebut akan secara otomatis dirutekan menggunakan default route WireGuard (`dev wg0`) di tabel `88` menuju VPS, lalu diteruskan oleh VPS ke VM Eksternal.
   * Sistem ini berjalan secara asimetris/simetris yang aman di atas VPN WireGuard murni secara otomatis.

---

## Visualisasi Aliran Trafik

```mermaid
graph TD
    subgraph Host Proxmox (Fisik)
        subgraph Bridge Lokal (vmbr0 - Layer 2)
            VM_DB[VM DB/Redis <br> 10.88.0.7 / 172.20.32.91]
            VM_OBE[VM OBE <br> 10.88.0.6 / 172.20.32.86]
            VM_LAYANAN[VM Layanan <br> 10.88.0.5 / 172.20.32.23]
            VM_BARU_INT[VM Baru Internal <br> 10.88.0.12 / DHCP]
        end
    end

    subgraph Internet / Cloud
        VPS[VPS Arus Balik <br> WireGuard Hub 10.88.0.1]
        VM_EXT[VM Baru Eksternal <br> 10.88.0.20]
    end

    %% Jalur Lokal (Cepat)
    VM_OBE <-->|Bypass L2 via ens18 < 0.5ms| VM_DB
    VM_LAYANAN <-->|Bypass L2 via ens18 < 0.5ms| VM_DB
    VM_BARU_INT <-->|Otomatis Bypass L2 setelah didaftarkan| VM_DB

    %% Jalur Internet WG (Normal)
    VM_EXT <==>|WireGuard Tunnel via Internet| VPS <==>|WireGuard Tunnel| VM_DB
```
