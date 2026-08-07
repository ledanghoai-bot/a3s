---
document_id: PHASE1B-M4-PIN-TOOL-ACTIVATION-CYCLE-SUMMARY-VI
title: "Phase 1B M4 — Tổng kết chu kỳ Merge/Deploy/Preflight/Activation Gate (PIN Tool)"
document_type: summary
owner: Dev
status: FINAL — chu kỳ đã đóng, chờ chu kỳ mới nếu muốn thử lại rehearsal
created_at: 2026-08-07
covers_period: "2026-08-06T13:10Z – 2026-08-07T07:30Z"
final_production_head: 405e75e29dd9792e732c0d6280ee3bf4e67c7a89
rehearsal_completed: false
language: vi-VN
---

# M4 — Tổng kết chu kỳ Merge/Deploy/Preflight/Activation Gate (PIN Tool)

Tài liệu tổng hợp toàn bộ chu kỳ từ lúc merge PR #7 (secure PIN provisioning tool) tới lúc CA
đóng Internal Synthetic Activation Gate mà không có rehearsal nào được thực thi. Mục đích: 1 điểm
tham chiếu duy nhất, không cần lật lại từng file CA-Docs/docs riêng lẻ để hiểu toàn bộ trình tự.

## 1. Kết quả cuối cùng (tóm tắt 1 dòng)

**PIN provisioning tool đã merge + deploy an toàn lên production ở trạng thái bất hoạt (dormant)
hoàn toàn — nhưng rehearsal thật (225 synthetic conversations) CHƯA từng chạy, PIN thật CHƯA
từng được đặt cho ai.** Gate đã đóng vì hết cửa sổ mà không ai ra lệnh bắt đầu, không phải vì lỗi
kỹ thuật hay vi phạm bảo mật.

## 2. Timeline đầy đủ

| # | Thời điểm (UTC) | Sự kiện | Tài liệu |
|---|---|---|---|
| 1 | trước phiên | PR #7 draft, head `7a7e92f`, CI xanh, đã qua 4 vòng CA review (REV1-4), F-M4-PIN-R3-01/02 đóng | `PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-4-VI.md` (CA) |
| 2 | — | CA phát hành handoff khôi phục (sau sự cố Claude Desktop) + Merge/Deploy-Dormant Gate cho exact head `7a7e92f` | `PHASE1B-M4-DEV-CONTINUATION-HANDOFF-VI.md`, `PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-GATE-VI.md` (CA) |
| 3 | `13:10:49Z` | PO merge PR #7 (do bộ lọc auto-mode chặn thao tác merge tự động) → merge commit `d8ef339d` | GitHub PR #7 |
| 4 | `13:12:39Z` | CI/CD tự động deploy code lên VPS thành công (run `31104714489`) | — |
| 5 | `~13:16Z`-`13:25Z` | Phát hiện CI/CD không tự chạy migration → backup DB thủ công → PO chạy tay `migrate.py up` (migrations 040-042) | — |
| 6 | `13:37:44Z` | Dev nộp evidence report đầy đủ, push lên `main` (`67fb9b0`) | `PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-EVIDENCE-VI.md` |
| 7 | `14:46:13Z` | CA Review 1: EVIDENCE_SUPPLEMENT_REQUIRED (F-E1-01/02/03 — thiếu CI/deploy provenance + bảng lệnh/exit-code chi tiết) | `...EVIDENCE-REVIEW-1-VI.md` (CA) |
| 8 | `~14:47Z` | Dev bổ sung report, push `main` (`405e75e`) — **push này vô tình trigger lại CI/CD deploy** (workflow không path-filter theo loại file), khiến production HEAD trôi từ `d8ef339d` sang `405e75e` | — |
| 9 | — | CA Review 2: ACCEPTED — evidence CLOSED | `...EVIDENCE-REVIEW-2-VI.md` (CA) |
| 10 | `~16:38Z` | PO Amendment 02 (approval_ref `...amendment-01`→`02`, khóa exact commit `d8ef339d`, staff 3/4/5, window `23:30Z`-`07:30Z` hôm sau) | `...APPROVAL-AMENDMENT-02-VI.md` (CA/PO) |
| 11 | — | CA Preflight Directive: cho phép Dev chạy fresh read-only preflight 14 mục | `...PREFLIGHT-DIRECTIVE-VI.md` (CA) |
| 12 | `23:51:37Z`-`23:52:04Z` | **Preflight #1: FAIL** — production HEAD (`405e75e`) không khớp exact commit Amendment 02 (`d8ef339d`) do drift ở bước 8; 13/14 mục kỹ thuật khác đều PASS, không có dấu hiệu activation | `...PREFLIGHT-EVIDENCE-VI.md` (Dev) |
| 13 | `2026-08-07` | CA Preflight Review 1: FAIL-CLOSED xác nhận Dev xử lý đúng; xác định đây là "governance drift" (chỉ đổi doc, 3 file vận hành — runner/manifest/PIN tool — không đổi blob); yêu cầu Amendment 03 + directive mới trước khi thử lại | `...PREFLIGHT-REVIEW-1-VI.md` (CA) |
| 14 | `04:00:10Z` | PO Amendment 03: khóa exact commit về đúng thực tế `405e75e`, giữ nguyên scope/principals/window (`00:15Z`-`07:30Z`) | `...APPROVAL-AMENDMENT-03-VI.md` (CA/PO) |
| 15 | — | CA Preflight Directive 2: cho phép chạy lại preflight, **yêu cầu rõ không push report lên `main`** (tránh lặp lại drift) | `...PREFLIGHT-DIRECTIVE-2-VI.md` (CA) |
| 16 | `04:09:06Z`-`04:09:12Z` | **Preflight #2: PASS** — 8/8 mục đạt, git blob SHA runner/manifest/PIN-tool khớp baseline, HEAD khớp `405e75e`, OFF-state sạch | `...PREFLIGHT-EVIDENCE-2-VI.md` (Dev, chỉ local `E:\Alpha3s\dev\`) |
| 17 | — | CA Preflight Review 2: ACCEPTED_PREFLIGHT_CLOSED | `...PREFLIGHT-REVIEW-2-VI.md` (CA) |
| 18 | `~04:31Z` | **CA mở Internal Synthetic Activation Gate** cho đúng 1 lần chạy full-lifecycle (225 synthetic conversations), cutoff bắt đầu run mới `06:45Z`, hết hạn `07:30Z`, trình tự 9 bước chi tiết (re-check → PIN ceremony → operational approval → key provisioning → dry-run → full run → review → cleanup → revoke) | `...ACTIVATION-GATE-VI.md` (CA) |
| 19 | `06:45Z`-`06:58Z` | **Không ai ra lệnh bắt đầu** — Dev không tự ý khởi động ceremony khi chưa có chỉ dẫn tường minh; cutoff trôi qua | — |
| 20 | `06:58Z` | CA phát hành No-Start Closure Directive: đóng cửa sổ run mới, yêu cầu Dev xác nhận không có write nào + nộp no-run post-snapshot trước `07:30Z` | `...NO-START-CLOSURE-DIRECTIVE-VI.md` (CA) |
| 21 | `07:01:14Z`-`07:01:15Z` | Dev chạy snapshot read-only cuối, xác nhận **0 dòng audit_log liên quan M4/PIN** kể từ lúc gate mở — dormant sạch tuyệt đối; nộp trước deadline | `...NO-RUN-CLOSURE-EVIDENCE-VI.md` (Dev, local) |
| 22 | `2026-08-07` | **CA đóng gate chính thức**: CLOSED_NO_EXECUTION_DORMANT_CONFIRMED — không phải rehearsal thành công, không đóng được yêu cầu rehearsal của Product Completion path | `...NO-RUN-CLOSURE-VI.md` (CA) |

## 3. Vì sao rehearsal không chạy — nguyên nhân gốc

**Không phải lỗi kỹ thuật hay lỗ hổng bảo mật.** Toàn bộ 3 nguyên nhân đều thuộc về quy trình
điều phối:

1. **Governance drift (mục 8 timeline):** GitHub Actions workflow deploy job hiện kích hoạt cho
   MỌI push lên `main`, kể cả docs-only — không path-filter. 2 lần nộp evidence/correction dạng
   Markdown đã vô tình đẩy production HEAD trôi khỏi commit đã được PO approve, buộc phải làm lại
   1 vòng Amendment + preflight từ đầu. **CA đã yêu cầu KHÔNG sửa workflow trong chuỗi activation
   hiện tại** (sửa sẽ tạo thêm 1 commit, lại làm mất hiệu lực gate) — đây là nợ kỹ thuật cần xử
   lý ở 1 change riêng, sau khi rehearsal xong.
2. **Gate mở nhưng không có lệnh thực thi:** CA mở Activation Gate hợp lệ, nhưng không kèm theo
   chỉ dẫn tường minh "bắt đầu ngay" cho Dev/3 principal. Dev tuân thủ đúng nguyên tắc "chỉ hành
   động khi có chỉ dẫn rõ ràng", không tự suy diễn quyền từ việc gate đang mở — kết quả là cửa sổ
   trôi qua mà không ai bắt đầu.
3. **Bài học CA tự ghi nhận** (trong `...NO-RUN-CLOSURE-VI.md` §4): lần sau, "PO/CA phải phát
   hành execution instruction rõ ràng cho DEV bắt đầu ceremony... không chỉ cấp quyền rồi chờ".

## 4. Trạng thái an toàn cuối cùng (đã verify độc lập nhiều lần)

| Hạng mục | Trạng thái |
|---|---|
| Production HEAD | `405e75e29dd9792e732c0d6280ee3bf4e67c7a89` |
| Migrations 040-042 (PIN bootstrap/bind/link) | `applied` — hạ tầng tồn tại nhưng bất hoạt |
| `capture_enabled` | `false` |
| PIN credential cho staff 3/4/5 | `0` — chưa ai có PIN thật |
| Bootstrap token / bind approval / capture approval | `0` / `0` / `0` |
| Synthetic residual (225 conversations) | `0` — chưa seed |
| Transcript/signing-auth key active | `0` / `0` |
| Health internal/external | `200` / `200` |
| DLQ | `0` |
| Audit log ghi nhận M4/PIN kể từ lúc gate mở | `0` dòng |

## 5. Việc còn tồn đọng nếu muốn thử rehearsal lần nữa

Theo đúng 5 điều kiện CA nêu ở `...NO-RUN-CLOSURE-VI.md` §4:

1. PO ban hành approval amendment mới (exact HEAD hiện tại, scope, principals, cửa sổ mới).
2. Fresh read-only preflight (Dev thực hiện, không push `main`).
3. CA phát hành Activation Gate mới.
4. **Quan trọng — khác lần trước:** sau khi gate mở, PO/CA phải ra lệnh thực thi rõ ràng cho Dev
   bắt đầu ceremony trong đúng cutoff, không chỉ mở gate rồi chờ.
5. Execution evidence + CA operational closure sau khi rehearsal thật sự chạy xong.

Nợ kỹ thuật riêng (không chặn rehearsal, xử lý khi thuận tiện): thêm `paths-ignore` cho thư mục
`docs/` vào GitHub Actions deploy workflow để các lần nộp tài liệu tương lai không tự trigger
redeploy production.

## 6. Ghi chú vận hành — ai chạy lệnh nào trong chu kỳ này

Bộ lọc auto-mode của Claude Code tự chặn các thao tác mutating trực tiếp lên production/GitHub dù
đã có xác nhận PO trong chat (merge PR, `migrate.py up`, `git push origin main` một vài lần,
`git cherry-pick` trên `main`) — những lệnh này do chính PO tự chạy tay theo đúng nguyên văn Dev
cung cấp. Toàn bộ backup, mọi truy vấn đọc, health check và thu thập evidence do Dev (Claude Code)
thực hiện qua SSH.
