# Glow Beauty Shop Chatbot

แชทบอทร้านความงาม (PoC) ที่ตอบคำถามลูกค้าจากข้อมูลจริงของร้านเท่านั้น — ไม่เดาราคา สต็อก หรือโปรโมชัน

| ส่วน | เทคโนโลยี |
|------|-----------|
| Frontend | Next.js |
| Backend API | FastAPI |
| Agent | LangGraph (`Plan → ReAct → Synthesizer`) |
| สินค้า | Supabase / Postgres |
| ความรู้ร้าน | AWS Bedrock Knowledge Base |
| สถานะออเดอร์ | Mock + ลิงก์ Kerry |

## สารบัญ

- [ระบบทำงานยังไง](#ระบบทำงานยังไง-แบบสั้น)
- [Quick start](#quick-start)
- [เตรียมข้อมูล (สินค้า + Knowledge Base)](#เตรียมข้อมูล-สินค้า--knowledge-base)
- [บอทตอบอะไรได้บ้าง](#บอทตอบอะไรได้บ้าง)
- [โครงสร้างโฟลเดอร์](#โครงสร้างโฟลเดอร์)
- [Environment variables](#environment-variables)
- [ทดสอบ](#ทดสอบ)
- [Docker (backend → ECR)](#docker-backend--ecr)
- [กฎการตอบของบอท](#กฎการตอบของบอท)
- [แก้ปัญหาที่พบบ่อย](#แก้ปัญหาที่พบบ่อย)

---

## ระบบทำงานยังไง (แบบสั้น)

ลูกค้าถาม → ระบบวางแผน → ไปดึงข้อมูลจาก tool ที่ถูกต้อง → สรุปคำตอบกลับ

```text
คำถามลูกค้า
    │
    ▼
① Planner     ตัดสินใจว่าจะใช้ tool ไหน (ยังไม่ดึงข้อมูล)
    │
    ▼
② ReAct       เรียก tool จริงตามแผน (วนได้จนกว่าจะครบ)
    │
    ├── search_product_catalog   → ตารางสินค้า (ราคา / สต็อก / เฉด)
    ├── search_store_knowledge   → Knowledge Base (โปร / FAQ / คุณสมบัติ)
    ├── lookup_order_status      → สถานะออเดอร์ mock + URL Kerry
    └── calculate_pricing        → คิดราคารวม / ส่วนลด (local หรือ API quote)
    │
    ▼
③ Synthesizer สรุปเป็นภาษาไทย จากข้อมูลที่ได้มาเท่านั้น
    │
    ▼
คำตอบลูกค้า
```

**หลักสำคัญ:** ถ้า tool ไม่เจอข้อมูล บอทจะบอกว่าไม่พบ — ไม่แต่งคำตอบเอง

---

## Quick start

### สิ่งที่ต้องมี

- Python **3.13+** และ [uv](https://docs.astral.sh/uv/)
- Node.js **20+**
- บัญชี **Supabase** (Auth + Postgres) — เปิด Email/Password หรือ provider ที่ใช้ login
- บัญชี **AWS** — Bedrock Knowledge Base + **model access** สำหรับ `AWS_BEDROCK_MODEL_ID`

### 1. Clone และติดตั้ง (ครั้งแรก)

```bash
git clone <repo-url>
cd ecom-project-v1
npm run setup
```

`setup` จะ copy `.env.example` → `.env`, ติดตั้ง deps (root + backend + frontend)  
จากนั้นแก้ `.env` และ `frontend/.env` ใส่ค่าจริง

| ไฟล์ | ใส่อะไร |
|------|---------|
| `.env` (root) | AWS, `DATABASE_URL`, Supabase URL/key — **backend ใช้ทั้งหมดนี้** |
| `frontend/.env` | เฉพาะ `NEXT_PUBLIC_*` (public vars สำหรับ browser) |

> **สำคัญ:** Backend ต้องมี `NEXT_PUBLIC_SUPABASE_URL` และ `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` ใน **root `.env`** ด้วย — ใช้ verify JWT ตอนเรียก API  
> อย่า commit ไฟล์ `.env` ที่มี secret จริง

### 2. สร้างตารางสินค้า

รัน `backend/sql/products.sql` ใน **Supabase → SQL Editor**

### 3. เตรียมข้อมูล

ดู [เตรียมข้อมูล (สินค้า + Knowledge Base)](#เตรียมข้อมูล-สินค้า--knowledge-base) — ถ้าไม่ import สินค้าและไม่ sync KB บอทจะตอบไม่ได้หลายคำถาม

### 4. เปิด Backend + Frontend (คำสั่งเดียว)

จาก **root ของโปรเจกต์**:

```bash
npm run dev
```

- Backend API: http://127.0.0.1:8000 (Swagger: http://127.0.0.1:8000/docs)
- Frontend: http://localhost:3000

รันแยกได้: `npm run dev:backend` หรือ `npm run dev:frontend`

### 5. Login แล้วค่อยแชท

API ทุก endpoint ต้องมี **Supabase JWT** — ถ้ายังไม่ login จะได้ 401

1. เปิด http://localhost:3000  
2. **Login / สมัคร** ผ่าน Supabase Auth  
3. สร้างแชทใหม่ แล้วลองถามคำถามตัวอย่างด้านล่าง  

---

## เตรียมข้อมูล (สินค้า + Knowledge Base)

### สินค้า (Supabase)

`products.sql` สร้างตารางเท่านั้น — **ต้อง import ข้อมูลสินค้าเอง**

1. Supabase → **Table Editor** → `products` → Import CSV  
2. หรือใส่ row ด้วย SQL / Dashboard  

คอลัมน์ที่รองรับ (ตาม `products.sql`):

```text
sku, name_th, category, shade, price_thb, stock_qty
```

ถ้าไม่มีข้อมูลในตาราง คำถามเรื่องราคา/สต็อกจะได้ "ไม่พบสินค้า"

### Knowledge Base (AWS Bedrock)

FAQ, โปรโมชัน, คุณสมบัติสินค้า มาจาก **Bedrock Knowledge Base** ไม่ใช่ตาราง `products`

1. อัปโหลดเอกสารไป S3 ที่ผูกกับ KB (เช่น `faq.md`, `products.md`)  
2. ใน Bedrock Console → Knowledge Base → **Sync** data source (ingestion)  
3. ตรวจ `AWS_KNOWLEDGE_BASE_ID` ใน `.env` ให้ตรงกับ KB ที่ใช้  

ถ้า KB ว่างหรือยังไม่ sync คำถามโปร/FAQ จะได้ข้อความแนะนำติดต่อ admin

---

## บอทตอบอะไรได้บ้าง

| ลูกค้าถามเกี่ยวกับ | Tool ที่ใช้ | แหล่งข้อมูล |
|--------------------|-------------|-------------|
| ราคาต่อชิ้น / สต็อก / SKU / เฉดสี | `search_product_catalog` | ตาราง `products` |
| ราคารวม / คิดเงิน / ส่วนลดจากยอด | `calculate_pricing` | Pricing engine (local) หรือ quote API |
| โปรโมชัน / คุณสมบัติ / นโยบายร้าน | `search_store_knowledge` | AWS Knowledge Base |
| พัสดุถึงไหน / สถานะออเดอร์ | `lookup_order_status` | Mock order |

โปรส่วนลดใน PoC (hardcode ใน pricing engine): **ซื้อเกิน 500 บาท ลด 10%**  
สลับไป API quote ทีหลังได้ด้วย `PRICING_QUOTE_BACKEND=api` + `PRICING_QUOTE_API_URL` (input/output JSON รูปแบบเดียวกัน)

### ตัวอย่างคำถาม

```text
ลิปแมตต์เบอร์ 1 ราคาเท่าไหร่คะ
ลิปแมตต์เบอร์ 1 ขอ 2 แท่ง ราคารวมเท่าไหร่ ได้ส่วนลดไหม
เซรั่ม vit c กับ ไฮยา อันไหนดีกว่า ราคาต่างกันไหม
ส่งฟรีเมื่อไหร่ / มีโค้ดส่วนลดไหม
พัสดุของฉันถึงไหนแล้ว
ออเดอร์ GB-1002 ส่งถึงไหนแล้ว
```

### Order mock (สำหรับ demo)

| Order ID | สถานะ |
|----------|--------|
| `GB-1001` | กำลังจัดส่ง — default ถ้าไม่ระบุเลขออเดอร์ |
| `GB-1002` | เตรียมจัดส่ง |
| `GB-1003` | จัดส่งสำเร็จ |

---

## โครงสร้างโฟลเดอร์

```text
ecom-project-v1/
├── backend/
│   ├── api/              # FastAPI endpoints
│   ├── agent/graph.py    # logic หลักของ agent
│   ├── repositories/     # เชื่อม DB / order mock
│   ├── rag/              # เรียก Knowledge Base
│   ├── services/         # chat session + stream
│   ├── sql/products.sql  # schema ตารางสินค้า
│   └── tests/
├── frontend/             # หน้าแชท (Next.js)
├── scripts/setup.mjs     # npm run setup
├── package.json          # npm run dev (backend + frontend)
├── .env.example          # env สำหรับ backend (+ Supabase verify)
├── frontend/.env.example # env สำหรับ frontend (public vars เท่านั้น)
└── README.md
```

---

## Environment variables

คัดลอกจาก `.env.example` / `frontend/.env.example` — **อย่า commit `.env`**

### Root `.env` (backend)

| ตัวแปร | ใช้ทำอะไร |
|--------|-----------|
| `AWS_KNOWLEDGE_BASE_ID` | ID ของ Bedrock Knowledge Base |
| `AWS_REGION` | เช่น `ap-southeast-2` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | credentials เรียก AWS |
| `AWS_BEDROCK_MODEL_ID` | โมเดล LLM บน Bedrock (ต้องเปิด model access) |
| `DATABASE_URL` | เชื่อม Postgres ตาราง `products` |
| `PRICING_QUOTE_BACKEND` | `local` (default) หรือ `api` สำหรับ quote ภายนอก |
| `PRICING_QUOTE_API_URL` | URL ของ quote API เมื่อ `PRICING_QUOTE_BACKEND=api` |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase URL — **backend ใช้ verify JWT** |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase key — **backend ใช้ verify JWT** |

### `frontend/.env`

| ตัวแปร | ใช้ทำอะไร |
|--------|-----------|
| `NEXT_PUBLIC_SUPABASE_URL` | login ฝั่ง browser |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | login ฝั่ง browser |
| `NEXT_PUBLIC_API_URL` | ที่อยู่ backend เช่น `http://localhost:8000` |

รายละเอียดครบอยู่ใน `.env.example`

---

## ทดสอบ

```bash
npm test
# หรือ
uv run --project backend python -m unittest discover -s backend/tests -v
```

---

## Docker (backend → ECR)

Frontend ไป S3/CloudFront แยก — image นี้เป็น **FastAPI สำหรับ ECS**

```bash
# จาก root ของโปรเจกต์
docker build -t glow-beauty-api .
docker run --env-file .env -p 8000:8000 glow-beauty-api
```

### CI/CD (GitHub Actions → ECR → ECS Fargate)

| Workflow | ไฟล์ | เหตุการณ์ | ทำอะไร |
|----------|------|-----------|--------|
| **CI** | `.github/workflows/test.yml` | PR → `main` | unit tests |
| **CI** | `.github/workflows/test.yml` | push/merge → `main` | tests → build Docker → **push ECR** |
| **CD** | `.github/workflows/deploy.yml` | หลัง CI บน `main` สำเร็จ | อัปเดต task def → **deploy ECS Fargate** |

CD ยังรันมือได้ (`workflow_dispatch`) โดยใส่ image tag เช่น `latest` หรือ sha 12 ตัว

ตั้งค่าใน GitHub repo:

| ชนิด | ชื่อ | ความหมาย |
|------|------|----------|
| Secret | `AWS_ROLE_TO_ASSUME` | IAM role ARN สำหรับ OIDC จาก GitHub Actions |
| Variable | `AWS_REGION` | เช่น `ap-southeast-2` |
| Variable | `ECR_REPOSITORY` | ชื่อ repo ใน ECR เช่น `glow-beauty-api` |
| Variable | `ECS_CLUSTER` | ชื่อ ECS cluster |
| Variable | `ECS_SERVICE` | ชื่อ ECS service |
| Variable | `ECS_TASK_DEFINITION` | ชื่อ task definition family |
| Variable | `ECS_CONTAINER_NAME` | ชื่อ container ใน task def (ต้องตรงกับที่ render) |

ต้องมี ECR repo + ECS cluster/service/task definition บน AWS ไว้ก่อน  
Role ต้อง trust GitHub OIDC ของ repo นี้ และมีสิทธิ์ ECR push + ECS update

Image tags ที่ CI push: `<sha12>` และ `latest` — CD ใช้ `<sha12>` จาก commit ที่ CI รัน

---

## กฎการตอบของบอท

- ใช้เฉพาะข้อมูลจาก tool — ไม่เดา
- เปรียบเทียบสินค้า: **ราคา → คุณสมบัติ → แนะนำ → ข้อควรระวัง**
- ไม่ให้คำแนะนำทางการแพทย์
- สินค้าไม่เจอ → แนะนำสินค้าหมวดใกล้เคียง (ถ้ามี)
- Knowledge Base ไม่เจอ → แนะนำติดต่อ admin (เบอร์ 1234567890)

---

## แก้ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|-------|---------|
| `No module named 'backend'` | รัน uvicorn จาก **root** ตาม Quick start |
| 401 / Missing token | Login ผ่าน Supabase ก่อนแชท |
| `Supabase auth is not configured` | ใส่ `NEXT_PUBLIC_SUPABASE_*` ใน **root `.env`** |
| Frontend เรียก API ไม่ได้ | ตรวจ `NEXT_PUBLIC_API_URL=http://localhost:8000` ใน `frontend/.env` |
| หาสินค้าไม่เจอทั้งที่ DB มี | ตรวจ `DATABASE_URL` + import ข้อมูลเข้า `products` |
| คำตอบโปร/FAQ เพี้ยนหรือไม่เจอ | ตรวจ KB id, เอกสารใน S3, และ **Sync** ingestion |
| Bedrock error | ตรวจ region, credentials, และ model access ใน AWS Console |

---

## License

Internal PoC
