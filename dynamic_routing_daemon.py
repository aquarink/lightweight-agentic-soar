#!/usr/bin/env python3
import socket
import struct
import os
import sys
import subprocess

# Konstanta Protokol Netlink
NETLINK_ROUTE = 0
RTMGRP_IPV4_IFADDR = 0x10  # Multicast group untuk perubahan alamat IPv4

# Tipe Pesan Netlink
RTM_NEWADDR = 20  # Alamat baru ditambahkan
RTM_DELADDR = 21  # Alamat dihapus

# Path ke script optimasi yang sudah ada
OPTIMIZE_SCRIPT = "/root/optimize_local_routing.py"

def trigger_routing_optimization(event_type, ip_address):
    """Menjalankan skrip optimasi perutean ketika terjadi perubahan IP"""
    print(f"[NETLINK EVENT] Terdeteksi perubahan IP: {ip_address} (Event Type: {event_type})")
    print(" -> Memicu optimasi rute bypass lokal secara real-time...")
    
    if os.path.exists(OPTIMIZE_SCRIPT):
        try:
            res = subprocess.run([sys.executable, OPTIMIZE_SCRIPT], capture_output=True, text=True)
            if res.returncode == 0:
                print(" -> [SUCCESS] Optimasi rute berhasil diterapkan secara instan.")
            else:
                print(f" -> [ERROR] Kegagalan eksekusi skrip: {res.stderr.strip()}")
        except Exception as e:
            print(f" -> [ERROR] Gagal memicu skrip: {str(e)}")
    else:
        print(f" -> [WARNING] Skrip {OPTIMIZE_SCRIPT} tidak ditemukan.")

def parse_nlmsg(data):
    """Mengurai header pesan Netlink dasar"""
    # Header Netlink berukuran 16 bytes:
    # Length (4B), Type (2B), Flags (2B), Seq (4B), PID (4B)
    if len(data) < 16:
        return None
    
    nlmsg_len, nlmsg_type, nlmsg_flags, nlmsg_seq, nlmsg_pid = struct.unpack("=IHHII", data[:16])
    return nlmsg_len, nlmsg_type, data[16:nlmsg_len]

def parse_ifaddrmsg(payload, nlmsg_type):
    """Mengurai payload pesan ifaddrmsg (struktur alamat interface)"""
    # Struktur ifaddrmsg berukuran 8 bytes:
    # family (1B), prefixlen (1B), flags (1B), scope (1B), index (4B)
    if len(payload) < 8:
        return
    
    ifa_family, ifa_prefixlen, ifa_flags, ifa_scope, ifa_index = struct.unpack("=BBBBI", payload[:8])
    
    # Hanya proses IPv4 (AF_INET = 2)
    if ifa_family != 2:
        return
        
    # Membaca atribut alamat (RTAs - Routing Attributes)
    # Setiap RTA memiliki header 4 bytes: length (2B), type (2B)
    rta_payload = payload[8:]
    offset = 0
    ip_address = None
    
    while offset + 4 <= len(rta_payload):
        rta_len, rta_type = struct.unpack("=HH", rta_payload[offset:offset+4])
        if rta_len < 4:
            break
            
        # IFA_ADDRESS (1) atau IFA_LOCAL (2) berisi alamat IP
        if rta_type in (1, 2) and rta_len >= 8:
            ip_bytes = rta_payload[offset+4 : offset+rta_len]
            if len(ip_bytes) >= 4:
                ip_address = socket.inet_ntoa(ip_bytes[:4])
                
        # Align ke batas 4-byte (alignment Netlink)
        offset += ((rta_len + 3) & ~3)
        
    if ip_address:
        event_name = "NEW_ADDR" if nlmsg_type == RTM_NEWADDR else "DEL_ADDR"
        trigger_routing_optimization(event_name, ip_address)

def main():
    print("[DAEMON] Memulai Netlink Routing Daemon (Event-Driven)...")
    print("[DAEMON] Mendengarkan perubahan konfigurasi IP pada Kernel space...")
    
    try:
        # Buka socket Netlink Route
        s = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_ROUTE)
        s.bind((0, RTMGRP_IPV4_IFADDR))
    except PermissionError:
        print("[CRITICAL] Membutuhkan hak akses root untuk membuka Socket Netlink Raw.")
        sys.exit(1)
    except Exception as e:
        print(f"[CRITICAL] Gagal inisialisasi socket Netlink: {str(e)}")
        sys.exit(1)
        
    try:
        while True:
            # Membaca event dari kernel space
            data, ancest = s.recvfrom(65535)
            
            # Proses pesan Netlink (bisa terdapat beberapa pesan tergabung)
            offset = 0
            while offset < len(data):
                msg_data = data[offset:]
                parsed = parse_nlmsg(msg_data)
                if not parsed:
                    break
                    
                nlmsg_len, nlmsg_type, payload = parsed
                if nlmsg_len == 0:
                    break
                    
                # Hanya proses event penambahan/penghapusan alamat IP
                if nlmsg_type in (RTM_NEWADDR, RTM_DELADDR):
                    parse_ifaddrmsg(payload, nlmsg_type)
                    
                # Align ke batas 4-byte
                offset += ((nlmsg_len + 3) & ~3)
                
    except KeyboardInterrupt:
        print("\n[DAEMON] Menghentikan Daemon...")
    finally:
        s.close()

if __name__ == "__main__":
    main()
