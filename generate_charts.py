#!/usr/bin/env python3
import os

# Gunakan non-interactive backend 'Agg' agar berjalan di headless server
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def create_directory():
    os.makedirs("/root/riset/img", exist_ok=True)

def generate_throughput_chart():
    # Perbandingan Throughput (64.8 Mbps vs 23.5 Gbps = 23,500 Mbps)
    categories = ['Sebelum (Hub-Spoke VPN)', 'Sesudah (L2 Local Bypass)']
    throughput_mbps = [64.8, 23500.0]  # Dalam Mbps

    plt.figure(figsize=(8, 6))
    colors = ['#f43f5e', '#10b981']  # Merah rose dan hijau emerald
    
    # Plot dengan skala logaritmik agar terlihat jelas perbedaannya yang sangat ekstrem
    bars = plt.bar(categories, throughput_mbps, color=colors, width=0.5)
    plt.yscale('log')
    
    plt.title('Perbandingan Network Throughput (Skala Logaritmik)', fontsize=14, fontweight='bold', pad=15)
    plt.ylabel('Throughput (Mbps) - Skala Log', fontsize=12)
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    
    # Tambahkan label nilai di atas bar
    for bar in bars:
        height = bar.get_height()
        if height >= 1000:
            label = f"{height/1000:.1f} Gbps"
        else:
            label = f"{height:.1f} Mbps"
        plt.annotate(label,
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 5),  # offset 5 points vertical
                     textcoords="offset points",
                     ha='center', va='bottom', fontsize=11, fontweight='bold')

    plt.tight_layout()
    plt.savefig("/root/riset/img/throughput_chart.png", dpi=300)
    plt.close()
    print(" -> Throughput chart successfully saved to /root/riset/img/throughput_chart.png")

def generate_latency_chart():
    # Perbandingan Latensi MTR Ping (5.2 ms vs 0.4 ms)
    # Perbandingan Latensi PGBench DB (85.61 ms vs 3.89 ms)
    # Perbandingan Latensi WRK HTTP (~450 ms vs 266.11 ms)
    categories = ['MTR Ping (ms)', 'PGBench DB (ms)', 'WRK HTTP (ms)']
    before_latency = [5.2, 85.61, 450.0]
    after_latency = [0.4, 3.89, 266.11]

    x = range(len(categories))
    width = 0.35  # Lebar bar

    plt.figure(figsize=(9, 6))
    
    # Plot bar berdampingan (Before vs After)
    bars_before = plt.bar([i - width/2 for i in x], before_latency, width, label='Sebelum (Trombone Routing)', color='#f43f5e')
    bars_after = plt.bar([i + width/2 for i in x], after_latency, width, label='Sesudah (L2 Local Bypass)', color='#10b981')

    plt.title('Perbandingan Penurunan Latensi Jaringan & Aplikasi', fontsize=14, fontweight='bold', pad=15)
    plt.ylabel('Latensi (Milidetik, ms)', fontsize=12)
    plt.xticks(x, categories)
    plt.legend(fontsize=11)
    plt.grid(axis='y', linestyle='--', alpha=0.5)

    # Tambahkan nilai label untuk before
    for bar in bars_before:
        height = bar.get_height()
        plt.annotate(f"{height:.2f} ms" if height < 10 else f"{int(height)} ms",
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 3),
                     textcoords="offset points",
                     ha='center', va='bottom', fontsize=9)

    # Tambahkan nilai label untuk after
    for bar in bars_after:
        height = bar.get_height()
        plt.annotate(f"{height:.2f} ms" if height < 10 else f"{int(height)} ms",
                     xy=(bar.get_x() + bar.get_width() / 2, height),
                     xytext=(0, 3),
                     textcoords="offset points",
                     ha='center', va='bottom', fontsize=9, fontweight='bold')

    plt.tight_layout()
    plt.savefig("/root/riset/img/latency_chart.png", dpi=300)
    plt.close()
    print(" -> Latency chart successfully saved to /root/riset/img/latency_chart.png")

def main():
    create_directory()
    print("Memulai pembuatan chart data visualisasi riset...")
    generate_throughput_chart()
    generate_latency_chart()
    print("Selesai men-generate seluruh grafik visualisasi!")

if __name__ == "__main__":
    main()
