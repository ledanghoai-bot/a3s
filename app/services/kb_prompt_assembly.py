"""Prompt Assembly (Knowledge Base V2 - M4, Bat 4).

Lap rap prompt hoan chinh tu 9 block THEO DUNG THU TU va Assembly Logic da
dinh nghia san trong PA-001-PROMPT-ASSEMBLY-PIPELINE.md (khong tu bia thu
tu/logic moi):

    [RUNTIME_POLICY] [MISSION] [SOURCE_PRIORITY] [CONVERSATION_STATE]
    [TOOL_RESULTS] [KNOWLEDGE_CONTEXT] [BEHAVIOR_CONTEXT] [STYLE_CONTEXT]
    [OUTPUT_REQUIREMENTS] [USER_MESSAGE]

Block trong PHAI duoc BO HOAN TOAN, khong de placeholder (dung yeu cau
PA-001 "Things to Avoid").

Assembly Logic theo route (tu app/services/kb_router.py, M3):
    IF route == "human" (complaint/health_safety)
      -> nap runtime policy + safety/support behavior, AN block ban hang.
    IF route == "tool" (ask_dynamic_information/order)
      -> chi nap Tool result, KHONG retrieve Knowledge tinh ve gia/ton kho.
    IF route == "knowledge" va intent la cau hoi san pham cu the
      -> Knowledge Context la trong tam.
    IF route == "knowledge" va intent == ask_for_consultation
      -> them Behavior Context ve Need Discovery/Recommendation.
    IF route == "answer_without_retrieval" (greeting)
      -> giu context toi thieu, an ca Knowledge lan Tool block.

Ngan sach context (PA-002) theo TY LE TU (khong phai token that - xap xi don
gian, chua tich hop tokenizer that, ghi ro gioi han nay):
    runtime_policy=0.15, state_and_history=0.20, tool_results=0.15,
    knowledge_units=0.30, behavior_and_style=0.10, output_reserve=0.10

Nguon uu tien (PA-003, dung cho SOURCE_PRIORITY block + logging):
    runtime/safety policy > Tool result > canonical Brand/Product source >
    approved behavior/playbook > conversation state > FAQ delivery guidance >
    general model knowledge.

CHUA tich hop LLM that (khong goi model, chi lap rap VA TRA VE prompt hoan
chinh dang text de kiem tra bang mat/log) - test qua scripts/kb_prompt_test.py.
"""

from dataclasses import dataclass, field

from app.services.kb_router import Route

# --- Noi dung TINH cho cac block co dinh (RUNTIME_POLICY/MISSION/SOURCE_PRIORITY/
# OUTPUT_REQUIREMENTS) - tom tat dung tinh than PA-001/PA-003, khong copy nguyen
# van toan bo tai lieu vao prompt (PA-002: "runtime context phai nho va dung").

_RUNTIME_POLICY = """QUY TAC KHONG DUOC VI PHAM:
- Gia, ton kho, khuyen mai, van chuyen, don hang PHAI qua Tool - khong tu tra loi tu Knowledge tinh.
- Neu co van de an toan/khieu nai: TAM DUNG muc tieu ban hang, uu tien xu ly/handoff.
- Khong duoc bia du lieu khi khong co nguon xac thuc - noi that la chua xac nhan duoc.
- Khong tiet lo xung dot du lieu noi bo cho khach (vd "2 nguon dang mau thuan")."""

_MISSION = "Ban la tro ly tu van cua 3S Coffee - giup khach hieu san pham, tu van dung nhu cau, va ho tro giao dich khi khach san sang."

_SOURCE_PRIORITY = """THU TU UU TIEN NGUON (cao -> thap):
Runtime/safety policy > Ket qua Tool vua xac thuc > Nguon Brand/Product chinh thuc (approved) >
Playbook/behavior da duyet > Trang thai hoi thoai da xac nhan > FAQ huong dan > Kien thuc chung cua model."""

_OUTPUT_REQUIREMENTS = """YEU CAU DAU RA:
- Tra loi ngan gon, dung trong tam cau hoi.
- Neu khong chac chan: noi that, KHONG doan.
- Neu can handoff: bao khach se duoc nguoi phu trach kiem tra, KHONG giai thich ly do ky thuat noi bo."""

_SAFETY_BEHAVIOR = """HANH VI: AN TOAN/HO TRO (KHONG ban hang luc nay):
Ghi nhan cam xuc khach, khong tu chan doan/tu van y te, khong hua hen thay cho nguoi phu trach.
Uu tien chuyen cho nguoi that xu ly ngay."""

_CONSULTATION_BEHAVIOR = """HANH VI: TU VAN (Need Discovery + Recommendation):
Hoi toi thieu 1 cau de hieu nhu cau truoc khi de xuat. Recommendation phai co can cu tu Knowledge,
khong doan bua. Chi de xuat 1 huong hanh dong tiep theo ro rang (One Next Best Action)."""

_DIRECT_ANSWER_BEHAVIOR = """HANH VI: TRA LOI TRUC TIEP:
Cau hoi cu the, da co Knowledge phu hop - tra loi thang, khong hoi lai tru khi thuc su can lam ro."""


@dataclass
class AssembledPrompt:
    prompt: str
    blocks_used: list[str] = field(default_factory=list)
    source_ids_used: list[str] = field(default_factory=list)


def _format_knowledge_block(units: list[dict]) -> str:
    lines = ["KIEN THUC LIEN QUAN (da approved, kem nguon):"]
    for u in units:
        lines.append(f"[{u['ku_id']} | {u['asset_id']} | domain={u['domain']}]")
        lines.append(u["content"])
        lines.append("")
    return "\n".join(lines).strip()


def _format_tool_results_block(tool_results: dict) -> str:
    lines = ["KET QUA TOOL (du lieu dong, da xac thuc cho luot nay):"]
    for key, value in tool_results.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _format_state_block(state: dict) -> str:
    lines = ["TRANG THAI HOI THOAI:"]
    for key, value in state.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def assemble_prompt(
    route: Route,
    user_message: str,
    knowledge_units: list[dict] | None = None,
    tool_results: dict | None = None,
    conversation_state: dict | None = None,
) -> AssembledPrompt:
    """Lap rap prompt theo dung 9 block + Assembly Logic cua PA-001. Block
    khong co du lieu se BI BO HOAN TOAN, khong de placeholder rong."""
    knowledge_units = knowledge_units or []
    blocks: list[tuple[str, str]] = []  # (ten_block, noi_dung) - giu thu tu

    # 1. RUNTIME_POLICY - luon co, khong duoc cat (PA-002: "khong duoc cat safety rule")
    blocks.append(("RUNTIME_POLICY", _RUNTIME_POLICY))

    # 2. MISSION - luon co
    blocks.append(("MISSION", _MISSION))

    # 3. SOURCE_PRIORITY - luon co
    blocks.append(("SOURCE_PRIORITY", _SOURCE_PRIORITY))

    # 4. CONVERSATION_STATE - chi khi co du lieu
    if conversation_state:
        blocks.append(("CONVERSATION_STATE", _format_state_block(conversation_state)))

    # 5. TOOL_RESULTS - chi khi co du lieu (PA-001: khong duoc cat neu co)
    if tool_results:
        blocks.append(("TOOL_RESULTS", _format_tool_results_block(tool_results)))

    # 6. KNOWLEDGE_CONTEXT - THEO ROUTE (Assembly Logic PA-001):
    #    route=tool -> KHONG retrieve Knowledge tinh ve gia/ton kho (du co
    #    truyen vao cung bo qua, dung y "Do not retrieve static price/stock").
    #    route=human -> an Knowledge (uu tien safety, khong ban hang).
    #    route=answer_without_retrieval -> an Knowledge (giu context toi thieu).
    if route.route == "knowledge" and knowledge_units:
        blocks.append(("KNOWLEDGE_CONTEXT", _format_knowledge_block(knowledge_units)))

    # 7. BEHAVIOR_CONTEXT - theo route
    if route.route == "human":
        blocks.append(("BEHAVIOR_CONTEXT", _SAFETY_BEHAVIOR))
    elif route.intent == "ask_for_consultation":
        blocks.append(("BEHAVIOR_CONTEXT", _CONSULTATION_BEHAVIOR))
    elif route.route == "knowledge":
        blocks.append(("BEHAVIOR_CONTEXT", _DIRECT_ANSWER_BEHAVIOR))
    # route=tool/answer_without_retrieval: khong can behavior instruction rieng, bo qua block

    # 8. STYLE_CONTEXT - placeholder cho Bat sau (can ingest Playbook units
    # that qua kb_retrieval roi chen vao day - Bat 4 dau tien chua lam,
    # ghi nhan gioi han).

    # 9. OUTPUT_REQUIREMENTS - luon co
    blocks.append(("OUTPUT_REQUIREMENTS", _OUTPUT_REQUIREMENTS))

    # 10. USER_MESSAGE - luon co, cuoi cung
    blocks.append(("USER_MESSAGE", user_message))

    prompt_text = "\n\n".join(f"[{name}]\n{content}" for name, content in blocks)
    source_ids = [u["ku_id"] for u in knowledge_units] if route.route == "knowledge" else []

    return AssembledPrompt(
        prompt=prompt_text,
        blocks_used=[name for name, _ in blocks],
        source_ids_used=source_ids,
    )
