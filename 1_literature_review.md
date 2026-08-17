# State-of-the-Art (SOTA) Literature Review: SDN-based Local Bypass in Edge-Cloud Hybrids

## 1. Perbandingan dengan Warrens dan EdgeVPN (P2P Overlays)

Dalam lanskap jaringan edge-cloud hibrida, interkoneksi antar-node sering kali mengandalkan jaringan overlay Peer-to-Peer (P2P) yang kompleks seperti **Warrens** dan **EdgeVPN**. Warrens mengimplementasikan overlay terdesentralisasi berbasis protokol gosip untuk mengelola keanggotaan grup dan tabel perutean secara dinamis. Di sisi lain, EdgeVPN mengandalkan jaringan overlay terdistribusi berbasis WebRTC atau libp2p untuk membangun terowongan (tunnels) *connectionless* langsung antar-node edge guna menembus Network Address Translation (NAT) dan firewall tanpa memerlukan server perantara.

Meskipun arsitektur P2P overlay tersebut sangat andal untuk skalabilitas jaringan WAN yang sangat dinamis, mereka memperkenalkan overhead kontrol (*control plane overhead*) dan latensi pemrosesan paket yang signifikan di tingkat pengguna (*user-space*). Negosiasi jalur, pemeliharaan tabel keanggotaan P2P, serta enkapsulasi paket di user-space membebani CPU dan meningkatkan latensi dasar inter-VM.

Pendekatan yang kami usulkan menawarkan paradigma alternatif yang berfungsi sebagai **lightweight, decentralized Software-Defined Networking (SDN) control plane**. Alih-alih membangun overlay P2P penuh di user-space, solusi kami menggunakan kontrol terdistribusi ringan yang mendeteksi perubahan topologi secara dinamis dan memprogram ulang *data plane* kernel Linux (routing table dan kebijakan perutean lokal) secara langsung pada Layer 2 virtual switch (`vmbr0`). Dengan memanfaatkan aturan perutean kebijakan (`ip rule src`), paket data lokal antar-VM diarahkan langsung ke sakelar virtual hypervisor tanpa perlu melalui enkapsulasi overlay, mempertahankan efisiensi *native* dari virtual switch L2 Proxmox.

---

## 2. Analisis Hambatan Kriptografis (Cryptographic Bottleneck) pada WireGuard

WireGuard menggunakan algoritma kriptografi modern **ChaCha20-Poly1305** untuk enkripsi dan otentikasi pesan (AEAD). Meskipun ChaCha20-Poly1305 jauh lebih cepat daripada enkripsi berbasis AES-GCM pada prosesor tanpa akselerasi perangkat keras AES-NI, proses enkripsi dan dekripsi ini tetap menjadi **Cryptographic Bottleneck** utama ketika menangani throughput data yang sangat tinggi (dalam skala gigabit per detik).

Setiap paket yang dikirim melalui antarmuka WireGuard (`wg0`) harus dienkripsi menggunakan ChaCha20 dan diotentikasi dengan Poly1305. Pada skenario hibrida edge-cloud tradisional di mana semua trafik dialihkan melalui VPN Hub (Trombone Routing), trafik lokal dari VM database (DB) ke VM aplikasi pada hypervisor fisik yang sama akan dipaksa untuk:
1. Dienkripsi oleh CPU virtual (vCPU) VM Sumber.
2. Dikirim keluar melalui jaringan fisik ke VPS Publik (Hub).
3. Didekripsi oleh CPU VPS Publik.
4. Dienkripsi kembali oleh CPU VPS untuk dikirim ke VM Tujuan.
5. Didekripsi oleh vCPU VM Tujuan.

Siklus enkripsi/dekripsi ganda ini mengonsumsi resource CPU hypervisor secara masif dan menurunkan efisiensi throughput jaringan lokal ke tingkat sub-optimal (terbatas pada kapasitas pemrosesan kriptografi CPU tunggal).

Solusi perutean bypass lokal (*local-bypass*) kami menghilangkan bottleneck kriptografis ini untuk lalu lintas lokal. Dengan mengidentifikasi bahwa kedua VM berada pada segmen Layer 2 (`vmbr0`) yang sama, kebijakan perutean diarahkan langsung melintasi switch virtual tanpa menyentuh antarmuka `wg0` untuk trafik lokal. Hasilnya, lalu lintas VM-to-VM terhindar dari overhead enkripsi ChaCha20-Poly1305, yang secara signifikan menghemat siklus instruksi CPU Hypervisor. Sumber daya CPU yang sebelumnya terbuang untuk pemrosesan enkripsi VPN kini dapat dialokasikan sepenuhnya untuk beban kerja aplikasi inti (seperti query database atau kalkulasi inferensi LLM), meningkatkan performa sistem secara keseluruhan.
