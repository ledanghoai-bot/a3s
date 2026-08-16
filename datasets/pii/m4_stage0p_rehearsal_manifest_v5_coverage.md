# Manifest v5 — Coverage matrix F-NUM-03

Ánh xạ 40 ca chuyên biệt → nhóm / cue / mệnh đề / kết quả mong đợi.

| key | nhóm | kết quả mong đợi | lý do (theo policy, KHÔNG theo detector) | câu |
|---|---|---|---|---|
| FNA001 | A same-clause nid/bank collision | bank_account | A/collision: `stk` gan so hon `cccd` -> bank (decision B) | cccd va stk 079000012371 nhe shop |
| FNA002 | A same-clause nid/bank collision | national_id | A/collision: `CCCD` gan hon -> national_id; chieu nguoc cua FNA001 | STK và CCCD 079000012372 ạ |
| FNA003 | A same-clause nid/bank collision | national_id | A/collision: cue bank dai hon nhung `cccd` van gan so hon -> national_id | so tai khoan cccd 079000012373 |
| FNA004 | A same-clause nid/bank collision | bank_account | A/collision: `so tai khoan` gan hon `cmnd` -> bank | cmnd va so tai khoan 079000012374 nhe |
| FNA005 | A same-clause nid/bank collision | bank_account | A/collision: `stk` gan hon `can cuoc` -> bank | can cuoc stk 079000012375 |
| FNA006 | A same-clause nid/bank collision | national_id | A/collision: `can cuoc` gan hon -> national_id; chieu nguoc cua FNA005 | stk can cuoc 079000012376 |
| FNA007 | A same-clause nid/bank collision | national_id | A/collision CO DAU: `căn cước` gan hon -> national_id | tài khoản và căn cước 079000012377 nhé |
| FNA008 | A same-clause nid/bank collision | bank_account | A/collision CO DAU: `STK` gan hon -> bank | chứng minh và STK 079000012378 |
| FNB001 | B window / boundary | bank_account | B/window: cue cach ~29-35 ky tu, TRONG cua so 80 -> bank | stk cua em o ngan hang ben do la 71000123421 |
| FNB002 | B window / boundary | bank_account | B/window: cue cach ~42 ky tu -> bank | so tai khoan cua minh ben ngan hang ACB la 71000123422 |
| FNB003 | B window / boundary | bank_account | B/window: cue cach ~55 ky tu -> bank | stk minh dang dung o ngan hang thuong mai co phan do la 71000123423 |
| FNB004 | B window / boundary | bank_account | B/window: cue cach ~63 ky tu, van trong 80 -> bank | stk cua em mo tai chi nhanh ngan hang gan nha ba ngoai o que la 71000123424 |
| FNB005 | B window / boundary | **no-slot** | B/window: cue cach >80 ky tu -> NGOAI cua so -> no-slot. So 11 chu so nen KHONG roi vao fallback national_id 12 so | stk cua em mo tai chi nhanh ngan hang gan nha ba ngoai o duoi que mien tay xa lam la 71000123425 |
| FNB006 | B window / boundary | **no-slot** | B/window: cue cach xa hon nua -> no-slot | stk nha em mo tu hoi con o duoi que ngoai kia lau lam roi khong nho ro nam nao nua la 71000123426 |
| FNB007 | B window / boundary | national_id | B/window: cue giay to cach ~38 ky tu -> national_id | cccd cua minh dang cam theo trong vi la 079000012427 |
| FNB008 | B window / boundary | national_id | B/window: cue giay to cach ~55 ky tu -> national_id | can cuoc cua em vua lam lai o phuong hoi thang truoc la 079000012428 |
| FNC001 | C clause asymmetry | bank_account | C/clause: cue CUNG loai vuot dau phay -> bank (kieu viet rat pho bien) | so tai khoan cua minh, 71000123431 |
| FNC002 | C clause asymmetry | bank_account | C/clause: cue CUNG loai vuot XUONG DONG -> bank | stk cua em,\n71000123432 |
| FNC003 | C clause asymmetry | bank_account | C/clause: cue CUNG loai vuot HAI menh de -> bank | stk cua em, vietcombank, 71000123433 |
| FNC004 | C clause asymmetry | bank_account | C/clause: cue CANH TRANH o menh de TRUOC -> khong chan duoc -> bank | ma giao dich da xong roi, stk 71000123434 |
| FNC005 | C clause asymmetry | **no-slot** | C/clause: cue canh tranh `ma giao dich` gan hon trong CUNG menh de; cue bank o menh de truoc -> no-slot | so tai khoan, ma giao dich 71000123435 |
| FNC006 | C clause asymmetry | national_id | C/clause: cue giay to CUNG loai vuot dau phay -> national_id | cccd cua minh, 079000012436 |
| FNC007 | C clause asymmetry | national_id | C/clause: cue loai tru o menh de truoc -> khong chan -> national_id | ma don da giao xong, cccd 079000012437 |
| FNC008 | C clause asymmetry | national_id, bank_account | C/clause: HAI PII, moi so lay cue cua menh de rieng -> khong ro ri cheo menh de | cccd 079000012438, stk 71000123439 |
| FND001 | D reference exclusion | **no-slot** | D/reference: `ma tham chieu` -> KHONG fallback national_id (so 12 chu so) | ma tham chieu 079000012441 nhe |
| FND002 | D reference exclusion | **no-slot** | D/reference CO DAU: `mã vận đơn` -> no-slot | mã vận đơn 079000012442 đâu rồi shop |
| FND003 | D reference exclusion | **no-slot** | D/reference: `ma tra cuu` -> no-slot | ma tra cuu 079000012443 la gi vay |
| FND004 | D reference exclusion | **no-slot** | D/reference CO DAU: `mã hóa đơn` -> no-slot | mã hóa đơn 079000012444 shop ơi |
| FND005 | D reference exclusion | **no-slot** | D/reference: cue nam giua cau -> no-slot | cho em xin lai ma van don 079000012445 |
| FND006 | D reference exclusion | **no-slot** | D/reference: cue tham chieu ghep voi tu tai chinh -> van no-slot | ma tham chieu giao dich 079000012446 |
| FND007 | D reference exclusion | **no-slot** | D/reference: hai cue loai tru cung luc -> no-slot | ma tra cuu don hang 079000012447 nhe |
| FND008 | D reference exclusion | **no-slot** | D/reference CO DAU: cue cach so vai tu -> no-slot | mã hóa đơn của em là 079000012448 |
| FNE001 | E bank-cue override + realistic | bank_account | E/override: `stk` gan hon `ma tham chieu` -> bank (rang buoc PO §1.4) | ma tham chieu cho stk 71000123451 |
| FNE002 | E bank-cue override + realistic | bank_account | E/override KHONG DAU CAU: cue bank gan hon -> bank | ma van don xong roi stk 71000123452 nhe |
| FNE003 | E bank-cue override + realistic | bank_account | E/emoji: emoji ngoai BMP chen giua cue va so -> bank | stk 🌟 71000123453 |
| FNE004 | E bank-cue override + realistic | bank_account | E/co dau: bien the co dau -> bank | số tài khoản 71000123454 nhé |
| FNE005 | E bank-cue override + realistic | bank_account | E/khong dau: bien the khong dau cua FNE004 -> bank | so tai khoan 71000123455 nhe |
| FNE006 | E bank-cue override + realistic | bank_account | E/tie cung nhom: hai cue CUNG nhom bank ke nhau -> bank, ket qua xac dinh | stk so tai khoan 71000123456 |
| FNE007 | E bank-cue override + realistic | bank_account | E/override: `stk` gan hon `ma hoa don` -> bank | ma hoa don va stk 71000123457 |
| FNE008 | E bank-cue override + realistic | bank_account | E/thuc te: cau chuyen khoan thong thuong -> bank | chuyen khoan qua stk 71000123458 giup em |

## Tổng hợp theo nhóm

| nhóm | số ca | bank | national_id | no-slot |
|---|---|---|---|---|
| A same-clause nid/bank collision | 8 | 4 | 4 | 0 |
| B window / boundary | 8 | 4 | 2 | 2 |
| C clause asymmetry | 8 | 5 | 3 | 1 |
| D reference exclusion | 8 | 0 | 0 | 8 |
| E bank-cue override + realistic | 8 | 8 | 0 | 0 |
