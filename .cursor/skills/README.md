# Project skills (Glow Beauty Shop)

Skills ที่ agent ควรใช้กับ repo นี้ — เรียงตามความจำเป็น

| Skill | จำเป็น? | ใช้เมื่อ |
|-------|---------|---------|
| [shop-agent](shop-agent/SKILL.md) | **Yes** | แตะ agent / tool / prompt / grounding / OOS |
| [pricing-quote](pricing-quote/SKILL.md) | **Yes** | คิดเงิน ส่วนลด quote API |
| [add-agent-tool](add-agent-tool/SKILL.md) | **Yes** | เพิ่ม tool ใหม่ใน LangGraph |
| [test](test/SKILL.md) | **Yes** | feature / bugfix — รัน TDD |
| [plan](plan/SKILL.md) | Recommended | งานใหญ่ก่อนลงมือ |
| [spec](spec/SKILL.md) | Recommended | feature ใหม่ที่ยังไม่มีสเปก |
| [code-simplify](code-simplify/SKILL.md) | Optional | รีแฟกเตอร์หลังทำเสร็จ |

## ลำดับงานแนะนำ

1. `spec` → เขียน SPEC (ถ้ายังไม่มี)
2. `plan` → หั่นงานเล็กๆ
3. `shop-agent` / `pricing-quote` / `add-agent-tool` ตามโดเมน
4. `test` → เขียนเทสก่อนหรือคู่กับการ implement
5. `code-simplify` → เก็บกวาดก่อนจบ
