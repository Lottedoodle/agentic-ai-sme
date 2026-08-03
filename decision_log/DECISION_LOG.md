# Decision Log

> Keep this short (~1 page). Bullet points are fine. This is what we'll dig into during the interview.

## 1. Architecture (a few sentences + one sketch)

*How does one customer message flow through your system to a reply? Add a quick sketch — ASCII, a diagram, or a photo of a whiteboard.*

```
┌──────────────┐   HTTPS    ┌─────────────────────────┐
│   Browser    │ ─────────► │ CloudFront + S3         │  Next.js (frontend)
│   Chat UI    │ ◄───────── │                         │
└──────┬───────┘            └─────────────────────────┘
       │
       │ 1) Supabase Auth → JWT
       │ 2) POST {NEXT_PUBLIC_API_URL}/api/sessions/{id}/messages/stream
       │    Authorization: Bearer <jwt>
       │    body: { "content": "..." }          ← frontend/lib/stream-api.ts
       ▼
┌──────────────────────────────────────────────────────┐
│ AWS ALB                                              │
│   └─► ECS Fargate  (หรือ EKS ถ้ามี cluster เดิม)    │
│       FastAPI  backend/api/main.py                   │
│         • get_authenticated_user (verify JWT)        │
│         • chat_service.send_message_stream()         │
└────────────┬─────────────────────────────────────────┘
             │
             ▼
      LangGraph agent  (backend/agent/graph.py)
             │
             ▼
        SSE: status / start / token / done
             │
             └──────────► Browser อัปเดตแชท
```

Agentic AI Workflow

```
Customer message
       │
       ▼
 chat_service._send_message_stream()
       │  graph.astream_events / ainvoke
       ▼
┌─────────────────┐
│ ① planner_node  │  สร้าง ExecutionPlan + product_filters / quote_filters
└────────┬────────┘
         ▼
┌─────────────────┐
│ prepare_reasoning│
└────────┬────────┘
         ▼
┌─────────────────┐     tool_calls ตามแผน
│ ② reasoning_    │ ──────────────────────┐
│    action_node  │ ◄───── วนกลับ ───────┤
└────────┬────────┘                      │
         │                               ▼
         │                    ┌──────────────────┐
         │                    │ tools_node       │
         │                    │ (ToolNode)       │
         │                    └────────┬─────────┘
         │                             │
         │   ┌─────────────────────────┼──────────────────────────┐
         │   ▼                         ▼                          ▼
         │ search_product_catalog   calculate_pricing      search_store_knowledge
         │      → Supabase             → pricing.py             → Bedrock KB
         │ lookup_order_status
         │      → mock order + Kerry URL
         │
         ▼ (ไม่มี tool_calls แล้ว)
┌─────────────────┐
│ ③ synthesizer_  │  ตอบภาษาไทยจาก evidence เท่านั้น
│    node         │  (OOS/not_found ใช้ template ได้)
└────────┬────────┘
         ▼
  SSE events → frontend
```



## 2. Three most important decisions


| #                                                                                                                      | Decision                                                                                                                                                                                                                                    | Alternative(s) I rejected                                                                                                                                        | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1.การเชื่อมต่อ API กับ Cloud Provider หรือ Model Provider เพื่อให้สอดคล้องกับ AI Governance, data privacy และ secutity | เลือกการเชื่อมต่อ API ไปยัง **Model Provider ผ่าน Cloud Provider**                                                                                                                                                                          | เลือกการเชื่อมต่อ API ตรงไปยัง **Model Provider** โดยตรง (เช่น OpenAI, Gemini เป็นต้น)                                                                           | **•** เนื่องจาก Model Provider บางราย (เช่น OpenAI) อาจมีนโยบายนำข้อมูลผู้ใช้ไปฝึกฝนโมเดลใหม่ (Re-train) แม้จะสามารถปิดการตั้งค่าได้ แต่ยังคงมีความเสี่ยงด้าน **AI Governance** และความเสี่ยงที่ข้อมูลสำคัญอาจรั่วไหลสู่สาธารณะ                                                                                                                                                                                                                                                                   |
| 2.การออกแบบ agentic workflow สำหรับการทำ chatbot                                                                       | เลือกการออกแบบ Architecture แบบ **Multi-Agent** โดยแบ่งออกเป็น 3 Agents ได้แก่: 1. **Plan & Execution Agent** 2. **ReAct Agent**3. **Synthesizer Agent**                                                                                 | เลือกการออกแบบ Architecture แบบ **Single Agent** (ใช้ Agent เพียง 1 ตัว ในการรับ Request จาก User, ผูกเข้ากับ Tools ทั้งหมด และประมวลผลทุกขั้นตอนด้วยตัวคนเดียว) | **•** เนื่องจากระบบมีฟีเจอร์ที่มีความซับซ้อน เช่น การดึงข้อมูล, การเปรียบเทียบราคา และการคำนวณราคา ก่อนที่จะสรุปคำตอบให้แก่ User จึงจำเป็นต้องใช้ **Multi-Agent Architecture** เพื่อแบ่งแยกหน้าที่การทำงานอย่างชัดเจน ช่วย **ลดโอกาสเกิด Hallucination** และทำหน้าที่เป็น **Guardrail** เพิ่มความแม่นยำให้กับ LLM                                                                                                                                                                                 |
| 3. การออกแบบ Architecture บน Production                                                                                | **Frontend:** เลือกใช้ **Amazon CloudFront + S3****Backend:** เลือกใช้ **AWS ALB** ร่วมกับ **ECS Fargate** หรือ **EKS** *(พิจารณาเลือก EKS หากองค์กรมี Cluster เดิมอยู่แล้ว แต่หากไม่มีจะเลือก ECS เนื่องจากมีค่าใช้จ่ายที่ประหยัดกว่า)* | การรวม Frontend และ Backend ไว้ใน Container เดียวกัน แล้วนำไป Deploy บน Virtual Machine (VM)                                                                     | **• Security:** ใช้ CloudFront บน AWS ช่วยลด Latency และมี SSL/TLS (HTTPS) ช่วยในการ Encrypt ข้อมูลระหว่างการรับ-ส่ง**• Scalability:** การแยก Frontend ออกจาก Backend ช่วยให้การ Scale Resource ฝั่ง Backend บน Container Service (ECS/EKS) ทำได้อย่างมีประสิทธิภาพและคุ้มค่าใช้จ่าย (Cost-effective)**• High Availability:** การ Deploy บน Container Orchestrator ช่วยให้ระบบพร้อมใช้งาน (24/7 Availability), รองรับ Auto-scaling, การทำ Blue-Green Deployment และ Zero-downtime Deployment |




## 3. Where I chose NOT to use an LLM (and why)

*ระบบจะไม่ใช้  LLM ในการคำนวณราคาโปรโมชั่น ส่วนลด ของผลิตภัณฑ์ จะทำการ intregrate เข้ากับระบบหลังบ้านและใช้ api แทน* 

*LLM มีหน้าที่รับข้อมูลมาสรุปผลและตอบกลับ user*

## 4. Biggest production risk + mitigation

1.การโดน Prompt Injection  
--> ป้องกัน 2 ชั้น: (1) **Synthesizer** เป็น guardrail layer สุดท้ายก่อนตอบกลับ user เพื่อตรวจว่าคำตอบตรงกับ scope ที่ระบบควรตอบไหม (ไม่มีข้อมูลหลุด ไม่มีคำสั่งแปลกปลอมที่ inject มา) (2) **จำกัดสิทธิ์ระดับ tool/action** โดยไม่ให้ LLM เข้าถึง database โดยตรง แต่ต้องผ่าน Lambda เป็นตัวกลาง ซึ่งกำหนดสิทธิ์การอ่าน/เขียน/ลบไว้ล่วงหน้าแบบ rule-based (ไม่ใช่ LLM ตัดสินใจ) ทำให้ต่อให้ Agent โดน injection ก็ไม่สามารถทำ action นอกเหนือ scope ที่กำหนดได้จริง — ครอบคลุมทั้งฝั่ง output (คำตอบผิด) และฝั่ง action (agent ทำสิ่งที่ไม่ควรทำ)

2.ส่วนของ backend เช่น เกิดปัญหาไฟฟ้าขัดข้อง ทำให้ data center ไม่สามารถ operate ได้หรือ server down

--> เราสามารถ deploy แบบ Multi availability zone ได้ ทำให้ถึงแม้จะเกิดปัญหา app ก็ยังสามารถ run บน AZ อื่นได้ 

3.Agentic AI วนลูปแล้วไม่ยอมจบ loop

--> กรณีที่ agentic ai วนลูปนานเนื่องจาก synthesizer ไม่ approve คำตอบ เช่น กรณีดึง chunk ที่ไม่เกี่ยวข้องทำให้ข้อความที่ตอบกลับ user ไม่ตรงประเด็น synthesizer จะสั่งให้วน loop จนกว่าจะได้ chunk ที่ถูกต้อง อาจเกิดปัญหาไม่จบ loop สักที วิธีแก้คือเราจะกำหนด max_iteration ของแต่ละ node ถ้าถึง max แล้วยังไม่ได้คำตอบให้ handoff ไปให้ admin

4.Cascading Failure

--> คือการที่ตัว system ของเรารอ API จากทาง cloud provider แล้วระบบไม่ส่ง API กลับมาสักที ทำให้ระบบค้างไม่สามารถทำงานต่อได้ วิธีการแก้ปัญหา เราจะกำหนด time_out ของการรอ api ถ้ารอเกินเวลาที่กำหนดให้จบ loop ทันที เพื่อป้องกันไม่ให้ระบบค้าง

5.Model Provider มีปัญหา

--> กรณีที่เกิดปัญหาเช่น rate limit หรือส่ง api แล้ว fail ทำให้มีโอกาสระบบล่มเพราะไม่ได้ข้อมูลกลับมาหรือ structure ไม่ตรงทำให้โปรแกรม error เราจะแก้ปัญหาโดยการตั้ง max retries กับ fallback โดยให้ ai ลองส่ง api ซ้ำถ้ายังไม่ได้ให้เปลี่ยน model ไป model provider อื่นแทนเช่น OpenAI ไปเป็น Anthropic แทน

## 5. With another week, I would... / I deliberately skipped...

1.ปรับขนาดของ model และเปลี่ยน model เพื่อลด cost และ latency ของตัวระบบ เนื่องจาก model ที่มีขนาดใหญ่หรือโมเดลประเภท resoning จะทำให้ latency สูงและ cost สูงเกินความจำเป็น จึงจำเป็นมีการเปลี่ยน model ให้เหมาะสมกับการใช้งาน หลังจากนั้นทำ regression+performance test และทำ evaluation เพื่อตรวจสอบความถูกต้องและความพร้อมก่อน deploy ครับ

2.เก็บ user preference เพื่อจะทำ hyper personalized ซื่งจะหาช่วงเวลาที่เหมาะสมจากนั้นส่ง notification เกี่ยวกับ promotion ของผลิตภัณฑ์ที่ user อาจจะสนใจ โดยอ้างอิงจากข้อมูลที่ AI เก็บจากพฤติกรรมของ user

3.ทำระบบสมาชิกในการเก็บสะสมคะแนน โดยเราสามารถทำโปรโมชั่นหรือเพิ่มคะแนนหากลูกค้าสั่งซื้อ โดยจะเป็นเกี่ยวกับผลิตภัณฑ์ที่ลูกค้าใช้เป็นประจำหรือสินค้าที่ใช้ได้ดีหากใช้ร่วมกับสินค้าที่ลูกค้าใช้เป็นประจำ การทำแบบนี้จะช่วยเพิ่มยอดขายต่อหัวของลูกค้าและเป็นการทำให้ลูกค้าคุ้นชินและมี engagement ร่วมกันกับทางร้าน จากนั้นนำคะแนนมาแลกของรางวัลที่เป็นรางวัลเล็กๆน่ารักๆ unique ของร้าน หรือทำแต้มที่เก็บได้ไปใช้เป็นส่วนลดในการซื้อสินค้าครั้งถัดไป