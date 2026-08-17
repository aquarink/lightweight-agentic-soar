import psycopg2
from pgvector.psycopg2 import register_vector
import redis
import ollama
import json

# Konfigurasi Koneksi
import os

DB_HOST = os.environ.get("DB_HOST", "10.88.0.7")
DB_NAME = os.environ.get("DB_NAME", "llm_db")
DB_USER = os.environ.get("DB_USER", "llm_user")
DB_PASS = os.environ.get("DB_PASS", "your_secure_db_password_here")

REDIS_HOST = os.environ.get("REDIS_HOST", "10.88.0.7")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_PASS = os.environ.get("REDIS_PASS", "your_secure_redis_password_here")

EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "llama3.2:latest"

# 1. Koneksi ke Database & Inisialisasi Tabel
def init_db():
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    # Daftarkan tipe vector dengan psycopg2
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    
    register_vector(conn)
    
    # Buat tabel untuk menyimpan potongan dokumen dan embedding-nya
    # nomic-embed-text menghasilkan vector 768 dimensi
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kb_documents (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            embedding vector(768)
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Database PostgreSQL dan tabel Vector siap.")

# 2. Koneksi ke Redis untuk Chat Memory
def get_redis_client():
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASS,
        decode_responses=True
    )

# 3. Menghasilkan Embedding menggunakan Ollama
def get_embedding(text):
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response['embedding']

# 4. Menyimpan Dokumen baru ke DB
def add_document(content):
    embedding = get_embedding(content)
    # Konversi list ke format string pgvector '[x,y,z...]'
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    register_vector(conn)
    cur = conn.cursor()
    cur.execute("INSERT INTO kb_documents (content, embedding) VALUES (%s, %s)", (content, embedding_str))
    conn.commit()
    cur.close()
    conn.close()
    print(f"Berhasil menyimpan dokumen: '{content[:50]}...'")

# 5. Semantic Search menggunakan Vector Distance (<=>)
def search_similar_documents(query, limit=2):
    query_emb = get_embedding(query)
    # Konversi list ke format string pgvector '[x,y,z...]'
    query_emb_str = "[" + ",".join(map(str, query_emb)) + "]"
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    register_vector(conn)
    cur = conn.cursor()
    # <=> mewakili Cosine Distance
    cur.execute("SELECT content FROM kb_documents ORDER BY embedding <=> %s LIMIT %s", (query_emb_str, limit))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in results]

# 6. Simulasi RAG + Chat Memory via Redis
def ask_llm_with_rag_and_memory(session_id, user_query):
    r_client = get_redis_client()
    
    # Ambil chat history dari Redis (maksimal 5 pesan terakhir)
    history_key = f"chat_session:{session_id}"
    history_raw = r_client.lrange(history_key, 0, 4)
    history = [json.loads(h) for h in reversed(history_raw)]
    
    # Lakukan Semantic Search di PostgreSQL
    context_docs = search_similar_documents(user_query, limit=2)
    context_str = "\n---\n".join(context_docs)
    
    # Rancang System Prompt dengan Konteks Dokumen
    system_prompt = f"""Anda adalah asisten AI yang membantu. 
Gunakan informasi konteks berikut untuk menjawab pertanyaan pengguna. 
Jika Anda tidak tahu jawabannya berdasarkan konteks tersebut, jawablah dengan pengetahuan Anda namun tetap sopan.

Konteks Dokumen:
{context_str}
"""
    
    # Siapkan pesan untuk Ollama
    messages = [{"role": "system", "content": system_prompt}]
    
    # Tambahkan riwayat percakapan
    for msg in history:
        messages.append(msg)
        
    # Tambahkan pertanyaan baru
    messages.append({"role": "user", "content": user_query})
    
    print(f"\n[RAG Context] Menggunakan {len(context_docs)} dokumen pendukung...")
    print(f"[Ollama] Menghubungi model {LLM_MODEL}...")
    
    # Panggil Ollama Chat API
    response = ollama.chat(model=LLM_MODEL, messages=messages)
    assistant_response = response['message']['content']
    
    # Simpan pertanyaan dan jawaban baru ke Redis
    r_client.rpush(history_key, json.dumps({"role": "user", "content": user_query}))
    r_client.rpush(history_key, json.dumps({"role": "assistant", "content": assistant_response}))
    r_client.ltrim(history_key, -10, -1) # Batasi maksimal 10 riwayat (5 interaksi)
    
    return assistant_response

if __name__ == "__main__":
    init_db()
    
    # Tambahkan dokumen demo jika tabel masih kosong
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM kb_documents;")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    
    if count == 0:
        print("\nMenambahkan dokumen basis pengetahuan demo...")
        add_document("Penyimpanan model LLM paling maksimal ditaruh di SSD/NVMe lokal VM LLM (10.88.0.4) untuk kecepatan loading.")
        add_document("VM DB (10.88.0.7) berisi PostgreSQL dengan pgvector untuk menyimpan representasi vektor dokumen.")
        add_document("Redis di VM DB digunakan untuk session caching dan chat history agar latensi respon sangat rendah.")
    
    # Simulasi interaksi
    session = "test_user_session_1"
    query = "Bagaimana rekomendasi terbaik untuk mengoptimalkan performa response model LLM saya?"
    
    print(f"\n[User Query]: {query}")
    answer = ask_llm_with_rag_and_memory(session, query)
    print(f"\n[AI Response]:\n{answer}")
