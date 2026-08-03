# Frontend (Next.js)

หน้าแชทของ Glow Beauty Shop Chatbot

คู่มือติดตั้งและรันโปรเจกต์ทั้งหมดอยู่ที่ **[../README.md](../README.md)**

## รันเฉพาะ frontend

```bash
cp .env.example .env   # ใส่ NEXT_PUBLIC_* จริง
npm install
npm run dev
```

เปิด http://localhost:3000 — ต้อง **login ผ่าน Supabase** ก่อนแชท และ backend ต้องรันอยู่ที่ `NEXT_PUBLIC_API_URL`
