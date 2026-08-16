# Manifest v5 — Inventory cho staff 5 review

Cột `span_text` là kết quả cắt `canonical_text[start:end]` **thật sự** — offset sai thì
đoạn này lệch ngay, reviewer đối chiếu bằng mắt được mà không phải đếm ký tự.

`no-slot` **cũng là ground truth** và phải được review: cột `note` giải thích vì sao
không gán nhãn (Directive §3).

| # | key | psid | nguồn | nhóm F-NUM-03 | slot | span | span_text | canonical_text | note |
|---|---|---|---|---|---|---|---|---|---|
| 1 | RE011 | m4synthrehearsalv1_000181 | v4_retained | — | national_id | (16, 28) | `079000012345` | CCCD của tôi là 079000012345 đây nhé | sensitive identity CCCD |
| 2 | RE012 | m4synthrehearsalv1_000182 | v4_retained | — | national_id | (16, 28) | `079000012346` | CCCD của tôi là 079000012346 đây nhé | sensitive identity CCCD |
| 3 | RE013 | m4synthrehearsalv1_000183 | v4_retained | — | national_id | (16, 28) | `079000012347` | CCCD của tôi là 079000012347 đây nhé | sensitive identity CCCD |
| 4 | RE014 | m4synthrehearsalv1_000184 | v4_retained | — | national_id | (16, 28) | `079000012348` | CCCD của tôi là 079000012348 đây nhé | sensitive identity CCCD |
| 5 | RE015 | m4synthrehearsalv1_000185 | v4_retained | — | national_id | (16, 28) | `079000012349` | CCCD của tôi là 079000012349 đây nhé | sensitive identity CCCD |
| 6 | RN001 | m4synthrehearsalv1_000226 | v4_retained | — | national_id | (16, 28) | `079300010001` | CCCD của tôi là 079300010001 nhé shop | nid cue CCCD hoa, co dau |
| 7 | RN002 | m4synthrehearsalv1_000227 | v4_retained | — | national_id | (16, 28) | `079300010002` | cccd của tôi là 079300010002 nhé shop | nid cue cccd thuong, co dau |
| 8 | RN003 | m4synthrehearsalv1_000228 | v4_retained | — | national_id | (17, 29) | `079300010003` | Cccd của mình là 079300010003 ạ | nid cue Cccd hoa dau |
| 9 | RN004 | m4synthrehearsalv1_000229 | v4_retained | — | national_id | (20, 32) | `079300010004` | căn cước của tôi là 079300010004 nhé | nid cue 'can cuoc' co dau |
| 10 | RN005 | m4synthrehearsalv1_000230 | v4_retained | — | national_id | (12, 24) | `079300010005` | số căn cước 079300010005 của mình | nid cue 'so can cuoc' |
| 11 | RN006 | m4synthrehearsalv1_000231 | v4_retained | — | national_id | (20, 32) | `079300010006` | chứng minh nhân dân 079300010006 nhé | nid cue CMND day du chu |
| 12 | RN007 | m4synthrehearsalv1_000232 | v4_retained | — | national_id | (16, 28) | `079300010007` | cccd cua toi la 079300010007 nhe shop | nid khong dau |
| 13 | RN008 | m4synthrehearsalv1_000233 | v4_retained | — | national_id | (14, 26) | `079300010008` | CCCD cua minh 079300010008 nhe | nid khong dau, cue hoa |
| 14 | RN009 | m4synthrehearsalv1_000234 | v4_retained | — | national_id | (20, 32) | `079300010009` | can cuoc cua toi la 079300010009 a | nid khong dau 'can cuoc' |
| 15 | RN010 | m4synthrehearsalv1_000235 | v4_retained | — | national_id | (12, 24) | `079300010010` | so can cuoc 079300010010 nhe | nid khong dau 'so can cuoc' |
| 16 | RN011 | m4synthrehearsalv1_000236 | v4_retained | — | national_id | (20, 32) | `079300010011` | chung minh nhan dan 079300010011 nhe | nid khong dau CMND |
| 17 | RN012 | m4synthrehearsalv1_000237 | v4_retained | — | national_id | (5, 17) | `079300010012` | CMND 079300010012 cua minh day | nid cue CMND ngan |
| 18 | RN013 | m4synthrehearsalv1_000238 | v4_retained | — | national_id | (16, 30) | `079 300 010013` | CCCD của tôi là 079 300 010013 nhé | nid separator khoang trang |
| 19 | RN014 | m4synthrehearsalv1_000239 | v4_retained | — | national_id | (16, 30) | `079.300.010014` | CCCD của tôi là 079.300.010014 nhé | nid separator dau cham |
| 20 | RN015 | m4synthrehearsalv1_000240 | v4_retained | — | national_id | (16, 30) | `079-300-010015` | CCCD của tôi là 079-300-010015 nhé | nid separator gach ngang |
| 21 | RN016 | m4synthrehearsalv1_000241 | v4_retained | — | national_id | (9, 23) | `079 300 010016` | can cuoc 079 300 010016 nhe shop | nid khong dau + khoang trang |
| 22 | RN017 | m4synthrehearsalv1_000242 | v4_retained | — | national_id | (5, 19) | `079.300.010017` | cccd 079.300.010017 nhe | nid khong dau + cham |
| 23 | RN018 | m4synthrehearsalv1_000243 | v4_retained | — | national_id | (5, 14) | `079300018` | CMND 079300018 nhé shop | CMND 9 so co cue |
| 24 | RN019 | m4synthrehearsalv1_000244 | v4_retained | — | national_id | (20, 29) | `079300019` | chứng minh nhân dân 079300019 của mình | CMND 9 so co dau |
| 25 | RN020 | m4synthrehearsalv1_000245 | v4_retained | — | national_id | (5, 14) | `079300020` | cmnd 079300020 nhe | CMND 9 so khong dau |
| 26 | RN021 | m4synthrehearsalv1_000246 | v4_retained | — | national_id | (8, 17) | `079300021` | số CMND 079300021 nhé shop | CMND 9 so + tu 'so' |
| 27 | RN022 | m4synthrehearsalv1_000247 | v4_retained | — | national_id | (18, 27) | `079300022` | can cuoc cong dan 079300022 nhe | CMND 9 so cue dai |
| 28 | RN023 | m4synthrehearsalv1_000248 | v4_retained | — | national_id | (5, 17) | `079300010023` | CCCD 079300010023 | nid o CUOI cau, khong tu thua |
| 29 | RN024 | m4synthrehearsalv1_000249 | v4_retained | — | national_id | (5, 17) | `079300010024` | cccd 079300010024 shop kiem tra giup | nid gan DAU cau |
| 30 | RN025 | m4synthrehearsalv1_000250 | v4_retained | — | national_id | (14, 26) | `079300010025` | mình gửi CCCD 079300010025 để xác minh nhé | nid GIUA cau |
| 31 | RN026 | m4synthrehearsalv1_000251 | v4_retained | — | national_id | (24, 36) | `079300010026` | xác minh giúp mình CCCD 079300010026 | nid cuoi cau, cue sat |
| 32 | RN027 | m4synthrehearsalv1_000252 | v4_retained | — | national_id | (0, 12) | `079300010027` | 079300010027 là số của mình nhé | bare 12 so, khong cue |
| 33 | RN028 | m4synthrehearsalv1_000253 | v4_retained | — | national_id | (0, 12) | `079300010028` | 079300010028 | bare 12 so, mot minh |
| 34 | RN029 | m4synthrehearsalv1_000254 | v4_retained | — | national_id | (9, 21) | `079300010029` | mình gửi 079300010029 nhé shop | bare 12 so giua cau |
| 35 | RN030 | m4synthrehearsalv1_000255 | v4_retained | — | national_id | (12, 24) | `079300010030` | so cua minh 079300010030 nhe | bare 12 so, cue mo ho 'so' |
| 36 | RE016 | m4synthrehearsalv1_000186 | v4_retained | — | bank_account | (21, 32) | `71000123456` | chuyển khoản tới STK 71000123456 đúng không shop | sensitive finance STK |
| 37 | RE017 | m4synthrehearsalv1_000187 | v4_retained | — | bank_account | (21, 32) | `71000123457` | chuyển khoản tới STK 71000123457 đúng không shop | sensitive finance STK |
| 38 | RE018 | m4synthrehearsalv1_000188 | v4_retained | — | bank_account | (21, 32) | `71000123458` | chuyển khoản tới STK 71000123458 đúng không shop | sensitive finance STK |
| 39 | RE019 | m4synthrehearsalv1_000189 | v4_retained | — | bank_account | (21, 32) | `71000123459` | chuyển khoản tới STK 71000123459 đúng không shop | sensitive finance STK |
| 40 | RE020 | m4synthrehearsalv1_000190 | v4_retained | — | bank_account | (21, 32) | `71000123460` | chuyển khoản tới STK 71000123460 đúng không shop | sensitive finance STK |
| 41 | BA001 | m4synthrehearsalv1_000256 | v4_retained | — | bank_account | (21, 29) | `71000123` | chuyển khoản tới STK 71000123 nhé | bank do dai 8 so |
| 42 | BA002 | m4synthrehearsalv1_000257 | v4_retained | — | bank_account | (21, 30) | `710001234` | chuyển khoản tới STK 710001234 nhé | bank do dai 9 so |
| 43 | BA003 | m4synthrehearsalv1_000258 | v4_retained | — | bank_account | (21, 31) | `7100012345` | chuyển khoản tới STK 7100012345 nhé | bank do dai 10 so |
| 44 | BA004 | m4synthrehearsalv1_000259 | v4_retained | — | bank_account | (21, 32) | `71000123456` | chuyển khoản tới STK 71000123456 nhé | bank do dai 11 so |
| 45 | BA005 | m4synthrehearsalv1_000260 | v4_retained | — | bank_account | (21, 33) | `710001234567` | chuyển khoản tới STK 710001234567 nhé | bank do dai 12 so |
| 46 | BA006 | m4synthrehearsalv1_000261 | v4_retained | — | bank_account | (21, 34) | `7100012345678` | chuyển khoản tới STK 7100012345678 nhé | bank do dai 13 so |
| 47 | BA007 | m4synthrehearsalv1_000262 | v4_retained | — | bank_account | (21, 35) | `71000123456789` | chuyển khoản tới STK 71000123456789 nhé | bank do dai 14 so |
| 48 | BA008 | m4synthrehearsalv1_000263 | v4_retained | — | bank_account | (21, 36) | `710001234567890` | chuyển khoản tới STK 710001234567890 nhé | bank do dai 15 so |
| 49 | BA009 | m4synthrehearsalv1_000264 | v4_retained | — | bank_account | (21, 37) | `7100012345678901` | chuyển khoản tới STK 7100012345678901 nhé | bank do dai 16 so |
| 50 | BA010 | m4synthrehearsalv1_000265 | v4_retained | — | bank_account | (21, 38) | `71000123456789012` | chuyển khoản tới STK 71000123456789012 nhé | bank do dai 17 so |
| 51 | BA011 | m4synthrehearsalv1_000266 | v4_retained | — | bank_account | (21, 39) | `710001234567890123` | chuyển khoản tới STK 710001234567890123 nhé | bank do dai 18 so |
| 52 | BA012 | m4synthrehearsalv1_000267 | v4_retained | — | bank_account | (21, 40) | `7100012345678901234` | chuyển khoản tới STK 7100012345678901234 nhé | bank do dai 19 so |
| 53 | BA013 | m4synthrehearsalv1_000268 | v4_retained | — | bank_account | (13, 24) | `71001000001` | số tài khoản 71001000001 của mình | cue 'so tai khoan' |
| 54 | BA014 | m4synthrehearsalv1_000269 | v4_retained | — | bank_account | (10, 22) | `710010000021` | tài khoản 710010000021 nhé shop | cue 'tai khoan' (12 so) |
| 55 | BA015 | m4synthrehearsalv1_000270 | v4_retained | — | bank_account | (7, 20) | `7100100000312` | số thẻ 7100100000312 của mình | cue 'so the' |
| 56 | BA016 | m4synthrehearsalv1_000271 | v4_retained | — | bank_account | (4, 15) | `71001000004` | stk 71001000004 nhe | cue stk thuong khong dau |
| 57 | BA017 | m4synthrehearsalv1_000272 | v4_retained | — | bank_account | (4, 15) | `71001000005` | STK 71001000005 Techcombank nhé | cue STK + ten ngan hang |
| 58 | BA018 | m4synthrehearsalv1_000273 | v4_retained | — | bank_account | (22, 33) | `71001000006` | so tai khoan cua minh 71001000006 nhe | cue khong dau |
| 59 | BA019 | m4synthrehearsalv1_000274 | v4_retained | — | bank_account | (4, 17) | `7100 1000 007` | STK 7100 1000 007 nhé | bank separator khoang trang |
| 60 | BA020 | m4synthrehearsalv1_000275 | v4_retained | — | bank_account | (13, 26) | `7100.1000.008` | số tài khoản 7100.1000.008 nhé | bank separator cham |
| 61 | BA021 | m4synthrehearsalv1_000276 | v4_retained | — | bank_account | (10, 23) | `7100-1000-009` | tài khoản 7100-1000-009 nhé | bank separator gach |
| 62 | BA022 | m4synthrehearsalv1_000277 | v4_retained | — | bank_account | (4, 22) | `7100 1000 0010 123` | STK 7100 1000 0010 123 nhé | bank 15 so + khoang trang |
| 63 | BA023 | m4synthrehearsalv1_000278 | v4_retained | — | bank_account | (13, 32) | `7100-1000-0011-2345` | so tai khoan 7100-1000-0011-2345 nhe | bank 18 so + gach |
| 64 | BA024 | m4synthrehearsalv1_000279 | v4_retained | — | bank_account | (10, 30) | `7100.1000.0012.34567` | tai khoan 7100.1000.0012.34567 nhe | bank 19 so + cham |
| 65 | BA025 | m4synthrehearsalv1_000280 | v4_retained | — | bank_account | (4, 15) | `71001000013` | STK 71001000013 | bank o CUOI cau |
| 66 | BA026 | m4synthrehearsalv1_000281 | v4_retained | — | bank_account | (10, 21) | `71001000014` | tài khoản 71001000014 shop chuyển giúp | bank gan DAU cau |
| 67 | BA027 | m4synthrehearsalv1_000282 | v4_retained | — | bank_account | (13, 24) | `71001000015` | mình gửi STK 71001000015 để shop chuyển nhé | bank GIUA cau |
| 68 | BA028 | m4synthrehearsalv1_000283 | v4_retained | — | bank_account | (24, 35) | `71001000016` | chuyển vào số tài khoản 71001000016 giúp mình | bank cuoi, cue dai |
| 69 | BA029 | m4synthrehearsalv1_000284 | v4_retained | — | bank_account | (16, 27) | `71001000017` | STK của mình là 71001000017 nha | bank cue + 'cua minh la' |
| 70 | BA030 | m4synthrehearsalv1_000285 | v4_retained | — | bank_account | (18, 29) | `71001000018` | shop ơi tài khoản 71001000018 nhé | bank sau tu goi |
| 71 | RD001 | m4synthrehearsalv1_000151 | v4_retained | — | name | (35, 48) | `Nguyễn Văn An` | Đặt giúp em 2 gói 500g. Người nhận Nguyễn Văn An, 0911223344, số 12 đường Lê Lợi, phường 5, quận 3, TPHCM | combo 1-message |
| 71 | RD001 | m4synthrehearsalv1_000151 | v4_retained | — | phone | (50, 60) | `0911223344` | Đặt giúp em 2 gói 500g. Người nhận Nguyễn Văn An, 0911223344, số 12 đường Lê Lợi, phường 5, quận 3, TPHCM | combo 1-message |
| 71 | RD001 | m4synthrehearsalv1_000151 | v4_retained | — | address | (62, 105) | `số 12 đường Lê Lợi, phường 5, quận 3, TPHCM` | Đặt giúp em 2 gói 500g. Người nhận Nguyễn Văn An, 0911223344, số 12 đường Lê Lợi, phường 5, quận 3, TPHCM | combo 1-message |
| 72 | RD002 | m4synthrehearsalv1_000152 | v4_retained | — | name | (35, 48) | `Trần Thị Bích` | Đặt giúp em 2 gói 500g. Người nhận Trần Thị Bích, 0911223345, 78/9 đường Quang Trung, phường 10, quận Gò Vấp | combo 1-message |
| 72 | RD002 | m4synthrehearsalv1_000152 | v4_retained | — | phone | (50, 60) | `0911223345` | Đặt giúp em 2 gói 500g. Người nhận Trần Thị Bích, 0911223345, 78/9 đường Quang Trung, phường 10, quận Gò Vấp | combo 1-message |
| 72 | RD002 | m4synthrehearsalv1_000152 | v4_retained | — | address | (62, 108) | `78/9 đường Quang Trung, phường 10, quận Gò Vấp` | Đặt giúp em 2 gói 500g. Người nhận Trần Thị Bích, 0911223345, 78/9 đường Quang Trung, phường 10, quận Gò Vấp | combo 1-message |
| 73 | RD003 | m4synthrehearsalv1_000153 | v4_retained | — | name | (35, 47) | `Lê Hoàng Nam` | Đặt giúp em 2 gói 500g. Người nhận Lê Hoàng Nam, 0911223346, 45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội | combo 1-message |
| 73 | RD003 | m4synthrehearsalv1_000153 | v4_retained | — | phone | (49, 59) | `0911223346` | Đặt giúp em 2 gói 500g. Người nhận Lê Hoàng Nam, 0911223346, 45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội | combo 1-message |
| 73 | RD003 | m4synthrehearsalv1_000153 | v4_retained | — | address | (61, 116) | `45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội` | Đặt giúp em 2 gói 500g. Người nhận Lê Hoàng Nam, 0911223346, 45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội | combo 1-message |
| 74 | RD004 | m4synthrehearsalv1_000154 | v4_retained | — | name | (35, 46) | `Phạm Thu Hà` | Đặt giúp em 2 gói 500g. Người nhận Phạm Thu Hà, 0911223347, số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn | combo 1-message |
| 74 | RD004 | m4synthrehearsalv1_000154 | v4_retained | — | phone | (48, 58) | `0911223347` | Đặt giúp em 2 gói 500g. Người nhận Phạm Thu Hà, 0911223347, số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn | combo 1-message |
| 74 | RD004 | m4synthrehearsalv1_000154 | v4_retained | — | address | (60, 103) | `số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn` | Đặt giúp em 2 gói 500g. Người nhận Phạm Thu Hà, 0911223347, số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn | combo 1-message |
| 75 | RD005 | m4synthrehearsalv1_000155 | v4_retained | — | name | (35, 50) | `Hoàng Minh Tuấn` | Đặt giúp em 2 gói 500g. Người nhận Hoàng Minh Tuấn, 0911223348, 56B đường Trần Phú, phường Lộc Thọ, Nha Trang | combo 1-message |
| 75 | RD005 | m4synthrehearsalv1_000155 | v4_retained | — | phone | (52, 62) | `0911223348` | Đặt giúp em 2 gói 500g. Người nhận Hoàng Minh Tuấn, 0911223348, 56B đường Trần Phú, phường Lộc Thọ, Nha Trang | combo 1-message |
| 75 | RD005 | m4synthrehearsalv1_000155 | v4_retained | — | address | (64, 109) | `56B đường Trần Phú, phường Lộc Thọ, Nha Trang` | Đặt giúp em 2 gói 500g. Người nhận Hoàng Minh Tuấn, 0911223348, 56B đường Trần Phú, phường Lộc Thọ, Nha Trang | combo 1-message |
| 76 | RD006 | m4synthrehearsalv1_000156 | v4_retained | — | name | (35, 48) | `Huỳnh Gia Bảo` | Đặt giúp em 2 gói 500g. Người nhận Huỳnh Gia Bảo, 0911223349, 123 đường Điện Biên Phủ, phường 15, quận Bình Thạnh | combo 1-message |
| 76 | RD006 | m4synthrehearsalv1_000156 | v4_retained | — | phone | (50, 60) | `0911223349` | Đặt giúp em 2 gói 500g. Người nhận Huỳnh Gia Bảo, 0911223349, 123 đường Điện Biên Phủ, phường 15, quận Bình Thạnh | combo 1-message |
| 76 | RD006 | m4synthrehearsalv1_000156 | v4_retained | — | address | (62, 113) | `123 đường Điện Biên Phủ, phường 15, quận Bình Thạnh` | Đặt giúp em 2 gói 500g. Người nhận Huỳnh Gia Bảo, 0911223349, 123 đường Điện Biên Phủ, phường 15, quận Bình Thạnh | combo 1-message |
| 77 | RD007 | m4synthrehearsalv1_000157 | v4_retained | — | name | (35, 47) | `Phan Thị Mai` | Đặt giúp em 2 gói 500g. Người nhận Phan Thị Mai, 0911223350, 34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng | combo 1-message |
| 77 | RD007 | m4synthrehearsalv1_000157 | v4_retained | — | phone | (49, 59) | `0911223350` | Đặt giúp em 2 gói 500g. Người nhận Phan Thị Mai, 0911223350, 34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng | combo 1-message |
| 77 | RD007 | m4synthrehearsalv1_000157 | v4_retained | — | address | (61, 113) | `34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng` | Đặt giúp em 2 gói 500g. Người nhận Phan Thị Mai, 0911223350, 34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng | combo 1-message |
| 78 | RD008 | m4synthrehearsalv1_000158 | v4_retained | — | name | (35, 45) | `Vũ Đức Anh` | Đặt giúp em 2 gói 500g. Người nhận Vũ Đức Anh, 0911223351, số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình | combo 1-message |
| 78 | RD008 | m4synthrehearsalv1_000158 | v4_retained | — | phone | (47, 57) | `0911223351` | Đặt giúp em 2 gói 500g. Người nhận Vũ Đức Anh, 0911223351, số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình | combo 1-message |
| 78 | RD008 | m4synthrehearsalv1_000158 | v4_retained | — | address | (59, 108) | `số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình` | Đặt giúp em 2 gói 500g. Người nhận Vũ Đức Anh, 0911223351, số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình | combo 1-message |
| 79 | RD009 | m4synthrehearsalv1_000159 | v4_retained | — | name | (35, 48) | `Võ Thành Long` | Đặt giúp em 2 gói 500g. Người nhận Võ Thành Long, 0911223352, 67 đường Cách Mạng Tháng 8, phường 6, quận 3 | combo 1-message |
| 79 | RD009 | m4synthrehearsalv1_000159 | v4_retained | — | phone | (50, 60) | `0911223352` | Đặt giúp em 2 gói 500g. Người nhận Võ Thành Long, 0911223352, 67 đường Cách Mạng Tháng 8, phường 6, quận 3 | combo 1-message |
| 79 | RD009 | m4synthrehearsalv1_000159 | v4_retained | — | address | (62, 106) | `67 đường Cách Mạng Tháng 8, phường 6, quận 3` | Đặt giúp em 2 gói 500g. Người nhận Võ Thành Long, 0911223352, 67 đường Cách Mạng Tháng 8, phường 6, quận 3 | combo 1-message |
| 80 | RD010 | m4synthrehearsalv1_000160 | v4_retained | — | name | (35, 49) | `Đặng Quỳnh Anh` | Đặt giúp em 2 gói 500g. Người nhận Đặng Quỳnh Anh, 0911223353, 88 đường Lý Thường Kiệt, phường 7, quận 11 | combo 1-message |
| 80 | RD010 | m4synthrehearsalv1_000160 | v4_retained | — | phone | (51, 61) | `0911223353` | Đặt giúp em 2 gói 500g. Người nhận Đặng Quỳnh Anh, 0911223353, 88 đường Lý Thường Kiệt, phường 7, quận 11 | combo 1-message |
| 80 | RD010 | m4synthrehearsalv1_000160 | v4_retained | — | address | (63, 105) | `88 đường Lý Thường Kiệt, phường 7, quận 11` | Đặt giúp em 2 gói 500g. Người nhận Đặng Quỳnh Anh, 0911223353, 88 đường Lý Thường Kiệt, phường 7, quận 11 | combo 1-message |
| 81 | RD011 | m4synthrehearsalv1_000161 | v4_retained | — | name | (35, 48) | `Nguyễn Văn An` | Đặt giúp em 2 gói 500g. Người nhận Nguyễn Văn An, 0911223354, 21 đường Phan Đăng Lưu, phường 3, quận Phú Nhuận | combo 1-message |
| 81 | RD011 | m4synthrehearsalv1_000161 | v4_retained | — | phone | (50, 60) | `0911223354` | Đặt giúp em 2 gói 500g. Người nhận Nguyễn Văn An, 0911223354, 21 đường Phan Đăng Lưu, phường 3, quận Phú Nhuận | combo 1-message |
| 81 | RD011 | m4synthrehearsalv1_000161 | v4_retained | — | address | (62, 110) | `21 đường Phan Đăng Lưu, phường 3, quận Phú Nhuận` | Đặt giúp em 2 gói 500g. Người nhận Nguyễn Văn An, 0911223354, 21 đường Phan Đăng Lưu, phường 3, quận Phú Nhuận | combo 1-message |
| 82 | RD012 | m4synthrehearsalv1_000162 | v4_retained | — | name | (35, 48) | `Trần Thị Bích` | Đặt giúp em 2 gói 500g. Người nhận Trần Thị Bích, 0911223355, 9 đường Nguyễn Huệ, phường Bến Nghé, quận 1 | combo 1-message |
| 82 | RD012 | m4synthrehearsalv1_000162 | v4_retained | — | phone | (50, 60) | `0911223355` | Đặt giúp em 2 gói 500g. Người nhận Trần Thị Bích, 0911223355, 9 đường Nguyễn Huệ, phường Bến Nghé, quận 1 | combo 1-message |
| 82 | RD012 | m4synthrehearsalv1_000162 | v4_retained | — | address | (62, 105) | `9 đường Nguyễn Huệ, phường Bến Nghé, quận 1` | Đặt giúp em 2 gói 500g. Người nhận Trần Thị Bích, 0911223355, 9 đường Nguyễn Huệ, phường Bến Nghé, quận 1 | combo 1-message |
| 83 | RD013 | m4synthrehearsalv1_000163 | v4_retained | — | name | (35, 47) | `Lê Hoàng Nam` | Đặt giúp em 2 gói 500g. Người nhận Lê Hoàng Nam, 0911223356, 156 đường Hai Bà Trưng, phường Đa Kao, quận 1 | combo 1-message |
| 83 | RD013 | m4synthrehearsalv1_000163 | v4_retained | — | phone | (49, 59) | `0911223356` | Đặt giúp em 2 gói 500g. Người nhận Lê Hoàng Nam, 0911223356, 156 đường Hai Bà Trưng, phường Đa Kao, quận 1 | combo 1-message |
| 83 | RD013 | m4synthrehearsalv1_000163 | v4_retained | — | address | (61, 106) | `156 đường Hai Bà Trưng, phường Đa Kao, quận 1` | Đặt giúp em 2 gói 500g. Người nhận Lê Hoàng Nam, 0911223356, 156 đường Hai Bà Trưng, phường Đa Kao, quận 1 | combo 1-message |
| 84 | RD014 | m4synthrehearsalv1_000164 | v4_retained | — | name | (35, 46) | `Phạm Thu Hà` | Đặt giúp em 2 gói 500g. Người nhận Phạm Thu Hà, 0911223357, 43 đường Trường Chinh, phường Khương Mai, Thanh Xuân | combo 1-message |
| 84 | RD014 | m4synthrehearsalv1_000164 | v4_retained | — | phone | (48, 58) | `0911223357` | Đặt giúp em 2 gói 500g. Người nhận Phạm Thu Hà, 0911223357, 43 đường Trường Chinh, phường Khương Mai, Thanh Xuân | combo 1-message |
| 84 | RD014 | m4synthrehearsalv1_000164 | v4_retained | — | address | (60, 112) | `43 đường Trường Chinh, phường Khương Mai, Thanh Xuân` | Đặt giúp em 2 gói 500g. Người nhận Phạm Thu Hà, 0911223357, 43 đường Trường Chinh, phường Khương Mai, Thanh Xuân | combo 1-message |
| 85 | RD015 | m4synthrehearsalv1_000165 | v4_retained | — | name | (35, 50) | `Hoàng Minh Tuấn` | Đặt giúp em 2 gói 500g. Người nhận Hoàng Minh Tuấn, 0911223358, 12 đường Bạch Đằng, phường 2, quận Tân Bình | combo 1-message |
| 85 | RD015 | m4synthrehearsalv1_000165 | v4_retained | — | phone | (52, 62) | `0911223358` | Đặt giúp em 2 gói 500g. Người nhận Hoàng Minh Tuấn, 0911223358, 12 đường Bạch Đằng, phường 2, quận Tân Bình | combo 1-message |
| 85 | RD015 | m4synthrehearsalv1_000165 | v4_retained | — | address | (64, 107) | `12 đường Bạch Đằng, phường 2, quận Tân Bình` | Đặt giúp em 2 gói 500g. Người nhận Hoàng Minh Tuấn, 0911223358, 12 đường Bạch Đằng, phường 2, quận Tân Bình | combo 1-message |
| 86 | RD016 | m4synthrehearsalv1_000166 | v4_retained | — | name | (35, 48) | `Huỳnh Gia Bảo` | Đặt giúp em 2 gói 500g. Người nhận Huỳnh Gia Bảo, 0911223359, 76 đường Lạc Long Quân, phường 5, quận 11 | combo 1-message |
| 86 | RD016 | m4synthrehearsalv1_000166 | v4_retained | — | phone | (50, 60) | `0911223359` | Đặt giúp em 2 gói 500g. Người nhận Huỳnh Gia Bảo, 0911223359, 76 đường Lạc Long Quân, phường 5, quận 11 | combo 1-message |
| 86 | RD016 | m4synthrehearsalv1_000166 | v4_retained | — | address | (62, 103) | `76 đường Lạc Long Quân, phường 5, quận 11` | Đặt giúp em 2 gói 500g. Người nhận Huỳnh Gia Bảo, 0911223359, 76 đường Lạc Long Quân, phường 5, quận 11 | combo 1-message |
| 87 | RD017 | m4synthrehearsalv1_000167 | v4_retained | — | name | (35, 47) | `Phan Thị Mai` | Đặt giúp em 2 gói 500g. Người nhận Phan Thị Mai, 0911223360, 29 đường Kim Mã, phường Kim Mã, Ba Đình | combo 1-message |
| 87 | RD017 | m4synthrehearsalv1_000167 | v4_retained | — | phone | (49, 59) | `0911223360` | Đặt giúp em 2 gói 500g. Người nhận Phan Thị Mai, 0911223360, 29 đường Kim Mã, phường Kim Mã, Ba Đình | combo 1-message |
| 87 | RD017 | m4synthrehearsalv1_000167 | v4_retained | — | address | (61, 100) | `29 đường Kim Mã, phường Kim Mã, Ba Đình` | Đặt giúp em 2 gói 500g. Người nhận Phan Thị Mai, 0911223360, 29 đường Kim Mã, phường Kim Mã, Ba Đình | combo 1-message |
| 88 | RD018 | m4synthrehearsalv1_000168 | v4_retained | — | name | (35, 45) | `Vũ Đức Anh` | Đặt giúp em 2 gói 500g. Người nhận Vũ Đức Anh, 0911223361, 58 đường Nguyễn Thị Minh Khai, phường 6, quận 3 | combo 1-message |
| 88 | RD018 | m4synthrehearsalv1_000168 | v4_retained | — | phone | (47, 57) | `0911223361` | Đặt giúp em 2 gói 500g. Người nhận Vũ Đức Anh, 0911223361, 58 đường Nguyễn Thị Minh Khai, phường 6, quận 3 | combo 1-message |
| 88 | RD018 | m4synthrehearsalv1_000168 | v4_retained | — | address | (59, 106) | `58 đường Nguyễn Thị Minh Khai, phường 6, quận 3` | Đặt giúp em 2 gói 500g. Người nhận Vũ Đức Anh, 0911223361, 58 đường Nguyễn Thị Minh Khai, phường 6, quận 3 | combo 1-message |
| 89 | RD019 | m4synthrehearsalv1_000169 | v4_retained | — | name | (35, 48) | `Võ Thành Long` | Đặt giúp em 2 gói 500g. Người nhận Võ Thành Long, 0911223362, 14 đường Hùng Vương, phường 9, quận 5 | combo 1-message |
| 89 | RD019 | m4synthrehearsalv1_000169 | v4_retained | — | phone | (50, 60) | `0911223362` | Đặt giúp em 2 gói 500g. Người nhận Võ Thành Long, 0911223362, 14 đường Hùng Vương, phường 9, quận 5 | combo 1-message |
| 89 | RD019 | m4synthrehearsalv1_000169 | v4_retained | — | address | (62, 99) | `14 đường Hùng Vương, phường 9, quận 5` | Đặt giúp em 2 gói 500g. Người nhận Võ Thành Long, 0911223362, 14 đường Hùng Vương, phường 9, quận 5 | combo 1-message |
| 90 | RD020 | m4synthrehearsalv1_000170 | v4_retained | — | name | (35, 49) | `Đặng Quỳnh Anh` | Đặt giúp em 2 gói 500g. Người nhận Đặng Quỳnh Anh, 0911223363, 37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1 | combo 1-message |
| 90 | RD020 | m4synthrehearsalv1_000170 | v4_retained | — | phone | (51, 61) | `0911223363` | Đặt giúp em 2 gói 500g. Người nhận Đặng Quỳnh Anh, 0911223363, 37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1 | combo 1-message |
| 90 | RD020 | m4synthrehearsalv1_000170 | v4_retained | — | address | (63, 109) | `37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1` | Đặt giúp em 2 gói 500g. Người nhận Đặng Quỳnh Anh, 0911223363, 37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1 | combo 1-message |
| 91 | RA001 | m4synthrehearsalv1_000001 | v4_retained | — | phone | (16, 26) | `0301234567` | sđt của mình là 0301234567 nhé shop | phone mobile plain |
| 92 | RA002 | m4synthrehearsalv1_000002 | v4_retained | — | phone | (8, 18) | `0301234568` | lien he 0301234568 gap nha | phone mobile plain |
| 93 | RA004 | m4synthrehearsalv1_000004 | v4_retained | — | phone | (15, 25) | `0301234570` | shop ơi gọi số 0301234570 giúp mình | phone mobile plain |
| 94 | RA005 | m4synthrehearsalv1_000005 | v4_retained | — | phone | (10, 20) | `0301234571` | zalo mình 0301234571 add giúp | phone mobile plain |
| 95 | RA008 | m4synthrehearsalv1_000008 | v4_retained | — | phone | (19, 29) | `0501234568` | alo gọi giúp em số 0501234568 trước khi giao | phone mobile plain |
| 96 | RA010 | m4synthrehearsalv1_000010 | v4_retained | — | phone | (10, 20) | `0501234570` | zalo mình 0501234570 add giúp | phone mobile plain |
| 97 | RA012 | m4synthrehearsalv1_000012 | v4_retained | — | phone | (8, 18) | `0501234572` | lien he 0501234572 gap nha | phone mobile plain |
| 98 | RA014 | m4synthrehearsalv1_000014 | v4_retained | — | phone | (15, 25) | `0701234568` | shop ơi gọi số 0701234568 giúp mình | phone mobile plain |
| 99 | RA015 | m4synthrehearsalv1_000015 | v4_retained | — | phone | (10, 20) | `0701234569` | zalo mình 0701234569 add giúp | phone mobile plain |
| 100 | RA018 | m4synthrehearsalv1_000018 | v4_retained | — | phone | (19, 29) | `0701234572` | alo gọi giúp em số 0701234572 trước khi giao | phone mobile plain |
| 101 | RA020 | m4synthrehearsalv1_000020 | v4_retained | — | phone | (10, 20) | `0801234568` | zalo mình 0801234568 add giúp | phone mobile plain |
| 102 | RA021 | m4synthrehearsalv1_000021 | v4_retained | — | phone | (16, 26) | `0801234569` | sđt của mình là 0801234569 nhé shop | phone mobile plain |
| 103 | RA024 | m4synthrehearsalv1_000024 | v4_retained | — | phone | (15, 25) | `0801234572` | shop ơi gọi số 0801234572 giúp mình | phone mobile plain |
| 104 | RA025 | m4synthrehearsalv1_000025 | v4_retained | — | phone | (10, 20) | `0901234567` | zalo mình 0901234567 add giúp | phone mobile plain |
| 105 | RA027 | m4synthrehearsalv1_000027 | v4_retained | — | phone | (8, 18) | `0901234569` | lien he 0901234569 gap nha | phone mobile plain |
| 106 | RA030 | m4synthrehearsalv1_000030 | v4_retained | — | phone | (10, 20) | `0901234572` | zalo mình 0901234572 add giúp | phone mobile plain |
| 107 | RA031 | m4synthrehearsalv1_000031 | v4_retained | — | phone | (11, 21) | `0283812345` | số cố định 0283812345 gọi giờ hành chính giúp em | phone landline |
| 108 | RA034 | m4synthrehearsalv1_000034 | v4_retained | — | phone | (11, 21) | `0283812348` | số cố định 0283812348 gọi giờ hành chính giúp em | phone landline |
| 109 | RA035 | m4synthrehearsalv1_000035 | v4_retained | — | phone | (11, 21) | `0283812349` | số cố định 0283812349 gọi giờ hành chính giúp em | phone landline |
| 110 | RA037 | m4synthrehearsalv1_000037 | v4_retained | — | phone | (11, 21) | `0283812351` | số cố định 0283812351 gọi giờ hành chính giúp em | phone landline |
| 111 | RA040 | m4synthrehearsalv1_000040 | v4_retained | — | phone | (11, 21) | `0283812354` | số cố định 0283812354 gọi giờ hành chính giúp em | phone landline |
| 112 | RA041 | m4synthrehearsalv1_000041 | v4_retained | — | phone | (11, 23) | `0912 345 670` | đổi số mới 0912 345 670 nhé shop, số cũ mất sim | phone format spaced |
| 113 | RA043 | m4synthrehearsalv1_000043 | v4_retained | — | phone | (11, 23) | `0912-345-672` | đổi số mới 0912-345-672 nhé shop, số cũ mất sim | phone format dash |
| 114 | RA045 | m4synthrehearsalv1_000045 | v4_retained | — | phone | (11, 26) | `+84 912 345 674` | đổi số mới +84 912 345 674 nhé shop, số cũ mất sim | phone format +84 space |
| 115 | RA047 | m4synthrehearsalv1_000047 | v4_retained | — | phone | (11, 25) | `(+84)912345676` | đổi số mới (+84)912345676 nhé shop, số cũ mất sim | phone format ngoac |
| 116 | RA050 | m4synthrehearsalv1_000050 | v4_retained | — | phone | (11, 22) | `0912 345679` | đổi số mới 0912 345679 nhé shop, số cũ mất sim | phone format spaced2 |
| 117 | RA051 | m4synthrehearsalv1_000051 | v4_retained | — | phone | (24, 34) | `0987654321` | so dien thoai cua minh: 0987654321 | phone extra template |
| 118 | RA053 | m4synthrehearsalv1_000053 | v4_retained | — | phone | (10, 20) | `0987654323` | để lại số 0987654323 liên hệ khi giao hàng | phone extra template |
| 119 | RA054 | m4synthrehearsalv1_000054 | v4_retained | — | phone | (27, 37) | `0987654324` | cần đặt hàng, số của em là 0987654324 | phone extra template |
| 120 | RA057 | m4synthrehearsalv1_000057 | v4_retained | — | phone | (23, 33) | `0987654327` | liên hệ giúp em qua số 0987654327 buổi tối | phone extra template |
| 121 | RA059 | m4synthrehearsalv1_000059 | v4_retained | — | phone | (30, 40) | `0987654329` | gọi giúp em trước 10 phút, số 0987654329 | phone extra template |
| 122 | RG003 | m4synthrehearsalv1_000223 | v4_retained | — | phone | (0, 12) | `0912🌟345🌟678` | 0912🌟345🌟678 nha shop | phone chen emoji — ground truth van danh dau du dia chi that |
| 123 | CX002 | m4synthrehearsalv1_000309 | v4_retained | — | phone | (4, 16) | `+84912345602` | gọi +84912345602 giúp mình | intl phone lien: negative cho nid/bank |
| 124 | RB001 | m4synthrehearsalv1_000061 | v4_retained | — | name | (12, 25) | `Nguyễn Văn An` | tên mình là Nguyễn Văn An | name template 0 |
| 125 | RB002 | m4synthrehearsalv1_000062 | v4_retained | — | name | (12, 25) | `Trần Thị Bích` | tên mình là Trần Thị Bích | name template 0 |
| 126 | RB003 | m4synthrehearsalv1_000063 | v4_retained | — | name | (12, 24) | `Lê Hoàng Nam` | tên mình là Lê Hoàng Nam | name template 0 |
| 127 | RB004 | m4synthrehearsalv1_000064 | v4_retained | — | name | (12, 23) | `Phạm Thu Hà` | tên mình là Phạm Thu Hà | name template 0 |
| 128 | RB007 | m4synthrehearsalv1_000067 | v4_retained | — | name | (12, 24) | `Phan Thị Mai` | tên mình là Phan Thị Mai | name template 0 |
| 129 | RB008 | m4synthrehearsalv1_000068 | v4_retained | — | name | (12, 22) | `Vũ Đức Anh` | tên mình là Vũ Đức Anh | name template 0 |
| 130 | RB009 | m4synthrehearsalv1_000069 | v4_retained | — | name | (12, 25) | `Võ Thành Long` | tên mình là Võ Thành Long | name template 0 |
| 131 | RB012 | m4synthrehearsalv1_000072 | v4_retained | — | name | (6, 19) | `Trần Thị Bích` | em là Trần Thị Bích ạ | name template 1 |
| 132 | RB013 | m4synthrehearsalv1_000073 | v4_retained | — | name | (6, 18) | `Lê Hoàng Nam` | em là Lê Hoàng Nam ạ | name template 1 |
| 133 | RB014 | m4synthrehearsalv1_000074 | v4_retained | — | name | (6, 17) | `Phạm Thu Hà` | em là Phạm Thu Hà ạ | name template 1 |
| 134 | RB017 | m4synthrehearsalv1_000077 | v4_retained | — | name | (6, 18) | `Phan Thị Mai` | em là Phan Thị Mai ạ | name template 1 |
| 135 | RB018 | m4synthrehearsalv1_000078 | v4_retained | — | name | (6, 16) | `Vũ Đức Anh` | em là Vũ Đức Anh ạ | name template 1 |
| 136 | RB019 | m4synthrehearsalv1_000079 | v4_retained | — | name | (6, 19) | `Võ Thành Long` | em là Võ Thành Long ạ | name template 1 |
| 137 | RB022 | m4synthrehearsalv1_000082 | v4_retained | — | name | (14, 27) | `Trần Thị Bích` | người nhận là Trần Thị Bích | name template 2 |
| 138 | RB023 | m4synthrehearsalv1_000083 | v4_retained | — | name | (14, 26) | `Lê Hoàng Nam` | người nhận là Lê Hoàng Nam | name template 2 |
| 139 | RB024 | m4synthrehearsalv1_000084 | v4_retained | — | name | (14, 25) | `Phạm Thu Hà` | người nhận là Phạm Thu Hà | name template 2 |
| 140 | RB027 | m4synthrehearsalv1_000087 | v4_retained | — | name | (14, 26) | `Phan Thị Mai` | người nhận là Phan Thị Mai | name template 2 |
| 141 | RB028 | m4synthrehearsalv1_000088 | v4_retained | — | name | (14, 24) | `Vũ Đức Anh` | người nhận là Vũ Đức Anh | name template 2 |
| 142 | RB029 | m4synthrehearsalv1_000089 | v4_retained | — | name | (14, 27) | `Võ Thành Long` | người nhận là Võ Thành Long | name template 2 |
| 143 | RB032 | m4synthrehearsalv1_000092 | v4_retained | — | name | (18, 31) | `Trần Thị Bích` | tên người nhận là Trần Thị Bích | name template 3 |
| 144 | RB033 | m4synthrehearsalv1_000093 | v4_retained | — | name | (18, 30) | `Lê Hoàng Nam` | tên người nhận là Lê Hoàng Nam | name template 3 |
| 145 | RB034 | m4synthrehearsalv1_000094 | v4_retained | — | name | (18, 29) | `Phạm Thu Hà` | tên người nhận là Phạm Thu Hà | name template 3 |
| 146 | RB037 | m4synthrehearsalv1_000097 | v4_retained | — | name | (18, 30) | `Phan Thị Mai` | tên người nhận là Phan Thị Mai | name template 3 |
| 147 | RB038 | m4synthrehearsalv1_000098 | v4_retained | — | name | (18, 28) | `Vũ Đức Anh` | tên người nhận là Vũ Đức Anh | name template 3 |
| 148 | RB039 | m4synthrehearsalv1_000099 | v4_retained | — | name | (18, 31) | `Võ Thành Long` | tên người nhận là Võ Thành Long | name template 3 |
| 149 | RB042 | m4synthrehearsalv1_000102 | v4_retained | — | name | (13, 26) | `Trần Thị Bích` | người đặt là Trần Thị Bích | name template 4 |
| 150 | RB043 | m4synthrehearsalv1_000103 | v4_retained | — | name | (13, 25) | `Lê Hoàng Nam` | người đặt là Lê Hoàng Nam | name template 4 |
| 151 | RB044 | m4synthrehearsalv1_000104 | v4_retained | — | name | (13, 24) | `Phạm Thu Hà` | người đặt là Phạm Thu Hà | name template 4 |
| 152 | RB047 | m4synthrehearsalv1_000107 | v4_retained | — | name | (13, 25) | `Phan Thị Mai` | người đặt là Phan Thị Mai | name template 4 |
| 153 | RB048 | m4synthrehearsalv1_000108 | v4_retained | — | name | (13, 23) | `Vũ Đức Anh` | người đặt là Vũ Đức Anh | name template 4 |
| 154 | RB049 | m4synthrehearsalv1_000109 | v4_retained | — | name | (13, 26) | `Võ Thành Long` | người đặt là Võ Thành Long | name template 4 |
| 155 | RC001 | m4synthrehearsalv1_000111 | v4_retained | — | address | (8, 51) | `số 12 đường Lê Lợi, phường 5, quận 3, TPHCM` | giao về số 12 đường Lê Lợi, phường 5, quận 3, TPHCM nhé shop | address template 0 |
| 156 | RC002 | m4synthrehearsalv1_000112 | v4_retained | — | address | (8, 54) | `78/9 đường Quang Trung, phường 10, quận Gò Vấp` | giao về 78/9 đường Quang Trung, phường 10, quận Gò Vấp nhé shop | address template 0 |
| 157 | RC003 | m4synthrehearsalv1_000113 | v4_retained | — | address | (8, 63) | `45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội` | giao về 45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội nhé shop | address template 0 |
| 158 | RC005 | m4synthrehearsalv1_000115 | v4_retained | — | address | (8, 53) | `56B đường Trần Phú, phường Lộc Thọ, Nha Trang` | giao về 56B đường Trần Phú, phường Lộc Thọ, Nha Trang nhé shop | address template 0 |
| 159 | RC007 | m4synthrehearsalv1_000117 | v4_retained | — | address | (8, 60) | `34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng` | giao về 34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng nhé shop | address template 0 |
| 160 | RC008 | m4synthrehearsalv1_000118 | v4_retained | — | address | (8, 57) | `số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình` | giao về số 5 đường Hoàng Diệu, phường Quán Thánh, Ba Đình nhé shop | address template 0 |
| 161 | RC010 | m4synthrehearsalv1_000120 | v4_retained | — | address | (8, 50) | `88 đường Lý Thường Kiệt, phường 7, quận 11` | giao về 88 đường Lý Thường Kiệt, phường 7, quận 11 nhé shop | address template 0 |
| 162 | RC012 | m4synthrehearsalv1_000122 | v4_retained | — | address | (8, 51) | `9 đường Nguyễn Huệ, phường Bến Nghé, quận 1` | giao về 9 đường Nguyễn Huệ, phường Bến Nghé, quận 1 nhé shop | address template 0 |
| 163 | RC014 | m4synthrehearsalv1_000124 | v4_retained | — | address | (8, 60) | `43 đường Trường Chinh, phường Khương Mai, Thanh Xuân` | giao về 43 đường Trường Chinh, phường Khương Mai, Thanh Xuân nhé shop | address template 0 |
| 164 | RC015 | m4synthrehearsalv1_000125 | v4_retained | — | address | (8, 51) | `12 đường Bạch Đằng, phường 2, quận Tân Bình` | giao về 12 đường Bạch Đằng, phường 2, quận Tân Bình nhé shop | address template 0 |
| 165 | RC016 | m4synthrehearsalv1_000126 | v4_retained | — | address | (8, 49) | `76 đường Lạc Long Quân, phường 5, quận 11` | giao về 76 đường Lạc Long Quân, phường 5, quận 11 nhé shop | address template 0 |
| 166 | RC019 | m4synthrehearsalv1_000129 | v4_retained | — | address | (8, 45) | `14 đường Hùng Vương, phường 9, quận 5` | giao về 14 đường Hùng Vương, phường 9, quận 5 nhé shop | address template 0 |
| 167 | RC020 | m4synthrehearsalv1_000130 | v4_retained | — | address | (8, 54) | `37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1` | giao về 37 đường Trần Hưng Đạo, phường Cầu Kho, quận 1 nhé shop | address template 0 |
| 168 | RC023 | m4synthrehearsalv1_000133 | v4_retained | — | address | (19, 74) | `45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội` | địa chỉ giao hàng: 45 đường Nguyễn Trãi, phường 7, quận Thanh Xuân, Hà Nội | address template 1 |
| 169 | RC024 | m4synthrehearsalv1_000134 | v4_retained | — | address | (19, 62) | `số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn` | địa chỉ giao hàng: số 9, thôn Đoài, xã Phú Minh, huyện Sóc Sơn | address template 1 |
| 170 | RC025 | m4synthrehearsalv1_000135 | v4_retained | — | address | (19, 64) | `56B đường Trần Phú, phường Lộc Thọ, Nha Trang` | địa chỉ giao hàng: 56B đường Trần Phú, phường Lộc Thọ, Nha Trang | address template 1 |
| 171 | RC027 | m4synthrehearsalv1_000137 | v4_retained | — | address | (19, 71) | `34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng` | địa chỉ giao hàng: 34 ngõ 78 phố Huế, phường Ngô Thì Nhậm, Hai Bà Trưng | address template 1 |
| 172 | RC029 | m4synthrehearsalv1_000139 | v4_retained | — | address | (19, 63) | `67 đường Cách Mạng Tháng 8, phường 6, quận 3` | địa chỉ giao hàng: 67 đường Cách Mạng Tháng 8, phường 6, quận 3 | address template 1 |
| 173 | RC030 | m4synthrehearsalv1_000140 | v4_retained | — | address | (19, 61) | `88 đường Lý Thường Kiệt, phường 7, quận 11` | địa chỉ giao hàng: 88 đường Lý Thường Kiệt, phường 7, quận 11 | address template 1 |
| 174 | RC032 | m4synthrehearsalv1_000142 | v4_retained | — | address | (19, 62) | `9 đường Nguyễn Huệ, phường Bến Nghé, quận 1` | địa chỉ giao hàng: 9 đường Nguyễn Huệ, phường Bến Nghé, quận 1 | address template 1 |
| 175 | RC034 | m4synthrehearsalv1_000144 | v4_retained | — | address | (19, 71) | `43 đường Trường Chinh, phường Khương Mai, Thanh Xuân` | địa chỉ giao hàng: 43 đường Trường Chinh, phường Khương Mai, Thanh Xuân | address template 1 |
| 176 | RC036 | m4synthrehearsalv1_000146 | v4_retained | — | address | (19, 60) | `76 đường Lạc Long Quân, phường 5, quận 11` | địa chỉ giao hàng: 76 đường Lạc Long Quân, phường 5, quận 11 | address template 1 |
| 177 | RC037 | m4synthrehearsalv1_000147 | v4_retained | — | address | (19, 58) | `29 đường Kim Mã, phường Kim Mã, Ba Đình` | địa chỉ giao hàng: 29 đường Kim Mã, phường Kim Mã, Ba Đình | address template 1 |
| 178 | RC038 | m4synthrehearsalv1_000148 | v4_retained | — | address | (19, 66) | `58 đường Nguyễn Thị Minh Khai, phường 6, quận 3` | địa chỉ giao hàng: 58 đường Nguyễn Thị Minh Khai, phường 6, quận 3 | address template 1 |
| 179 | CX005 | m4synthrehearsalv1_000312 | v4_retained | — | address | (8, 56) | `45 đường Trần Hưng Đạo, phường 6, quận Long Biên` | giao về 45 đường Trần Hưng Đạo, phường 6, quận Long Biên nhé | so nha trong dia chi: negative cho nid/bank |
| 180 | CX006 | m4synthrehearsalv1_000313 | v4_retained | — | address | (8, 57) | `số 12 đường Hai Bà Trưng, phường 8, quận Tân Bình` | giao về số 12 đường Hai Bà Trưng, phường 8, quận Tân Bình nhé | so nha + quan: negative cho nid/bank |
| 181 | RE001 | m4synthrehearsalv1_000171 | v4_retained | — | **no-slot** | — | — | mình bị tiểu đường uống cà phê này được không shop | sensitive health, no PII slot |
| 182 | RE003 | m4synthrehearsalv1_000173 | v4_retained | — | **no-slot** | — | — | mẹ mình huyết áp cao, cà phê decaf có không? | sensitive health, no PII slot |
| 183 | RE005 | m4synthrehearsalv1_000175 | v4_retained | — | **no-slot** | — | — | bé nhà em còn cho con bú thì mẹ uống được không | sensitive health, no PII slot |
| 184 | RE008 | m4synthrehearsalv1_000178 | v4_retained | — | **no-slot** | — | — | mình hay bị trào ngược dạ dày có uống được không | sensitive health, no PII slot |
| 185 | RE010 | m4synthrehearsalv1_000180 | v4_retained | — | **no-slot** | — | — | mình bị rối loạn lo âu, cà phê có ảnh hưởng không | sensitive health, no PII slot |
| 186 | RF002 | m4synthrehearsalv1_000192 | v4_retained | — | **no-slot** | — | — | đơn A123 tới đâu rồi shop | negative, no PII |
| 187 | RF005 | m4synthrehearsalv1_000195 | v4_retained | — | **no-slot** | — | — | cà phê này chua quá, đổi vị khác được không | negative, no PII |
| 188 | RF007 | m4synthrehearsalv1_000197 | v4_retained | — | **no-slot** | — | — | máy pha bị hỏng rồi, không lên nước | negative, no PII |
| 189 | RF010 | m4synthrehearsalv1_000200 | v4_retained | — | **no-slot** | — | — | giao 10 giờ 30 sáng mai nhé | negative, no PII |
| 190 | RF012 | m4synthrehearsalv1_000202 | v4_retained | — | **no-slot** | — | — | đà nẵng đường xa vậy phí ship nhiêu | negative, no PII |
| 191 | RF014 | m4synthrehearsalv1_000204 | v4_retained | — | **no-slot** | — | — | cho 1 ly cà phê sữa với 2 ly đen đá | negative, no PII |
| 192 | RF017 | m4synthrehearsalv1_000207 | v4_retained | — | **no-slot** | — | — | gói 250g với gói 1kg lệch nhau nhiêu tiền | negative, no PII |
| 193 | RF019 | m4synthrehearsalv1_000209 | v4_retained | — | **no-slot** | — | — | cà phê phin với cà phê pha máy khác gì nhau | negative, no PII |
| 194 | RF022 | m4synthrehearsalv1_000212 | v4_retained | — | **no-slot** | — | — | đóng gói có chống ẩm không shop | negative, no PII |
| 195 | RF024 | m4synthrehearsalv1_000214 | v4_retained | — | **no-slot** | — | — | vận chuyển mất mấy ngày vậy shop | negative, no PII |
| 196 | RF026 | m4synthrehearsalv1_000216 | v4_retained | — | **no-slot** | — | — | cà phê rang mộc với rang xay khác nhau sao shop | negative, no PII |
| 197 | RF029 | m4synthrehearsalv1_000219 | v4_retained | — | **no-slot** | — | — | đơn hàng có xuất hoá đơn không shop | negative, no PII |
| 198 | RG001 | m4synthrehearsalv1_000221 | v4_retained | — | **no-slot** | — | — | số mình là không chín một hai ba bốn năm sáu bảy tám nhé | phone doc bang chu — khong co digit substring de gan span, ground truth rong co y |
| 199 | RX001 | m4synthrehearsalv1_000286 | v4_retained | — | **no-slot** | — | — | đơn hàng 079400010001 tới chưa shop | neg order code 12 so co dau |
| 200 | RX002 | m4synthrehearsalv1_000287 | v4_retained | — | **no-slot** | — | — | don hang 079400010002 giao chua | neg order code khong dau |
| 201 | RX003 | m4synthrehearsalv1_000288 | v4_retained | — | **no-slot** | — | — | mã đơn 079400010003 kiểm tra giúp mình | neg ma don co dau |
| 202 | RX004 | m4synthrehearsalv1_000289 | v4_retained | — | **no-slot** | — | — | ma don 079400010004 sao roi shop | neg ma don khong dau |
| 203 | RX005 | m4synthrehearsalv1_000290 | v4_retained | — | **no-slot** | — | — | mã giao dịch 079400010005 đã chuyển | neg ma giao dich co dau |
| 204 | RX006 | m4synthrehearsalv1_000291 | v4_retained | — | **no-slot** | — | — | ma giao dich 079400010006 nhe | neg ma giao dich khong dau |
| 205 | RX007 | m4synthrehearsalv1_000292 | v4_retained | — | **no-slot** | — | — | order 079400010007 status thế nào | neg order tieng Anh |
| 206 | RX008 | m4synthrehearsalv1_000293 | v4_retained | — | **no-slot** | — | — | transaction 079400010008 pending nhé | neg transaction tieng Anh |
| 207 | RX009 | m4synthrehearsalv1_000294 | v4_retained | — | **no-slot** | — | — | mã giao dịch 07940001000900011 đã chuyển tiền | neg ma giao dich 17 so |
| 208 | RX010 | m4synthrehearsalv1_000295 | v4_retained | — | **no-slot** | — | — | mã tham chiếu chuyển khoản 079400010010000112 nhé | neg ma tham chieu 18 so |
| 209 | RX011 | m4synthrehearsalv1_000296 | v4_retained | — | **no-slot** | — | — | nội dung chuyển khoản 0794000100110001123 đã gửi | neg noi dung CK 19 so |
| 210 | RX012 | m4synthrehearsalv1_000297 | v4_retained | — | **no-slot** | — | — | hóa đơn 07940001001200011 đã thanh toán | neg hoa don 17 so |
| 211 | RX013 | m4synthrehearsalv1_000298 | v4_retained | — | **no-slot** | — | — | mã vận đơn 079400010013000112 giao rồi | neg ma van don 18 so |
| 212 | RX014 | m4synthrehearsalv1_000299 | v4_retained | — | **no-slot** | — | — | ma don 0794000100140001123 da chuyen khoan | neg ma don 19 so |
| 213 | RX015 | m4synthrehearsalv1_000300 | v4_retained | — | **no-slot** | — | — | chuyển 71000123456 đồng nhé | neg so tien 11 so |
| 214 | RX016 | m4synthrehearsalv1_000301 | v4_retained | — | **no-slot** | — | — | tổng đơn 1.250.000đ nhé shop | neg so tien co dau cham |
| 215 | RX017 | m4synthrehearsalv1_000302 | v4_retained | — | **no-slot** | — | — | giá 120000 đồng thôi | neg so tien ngan |
| 216 | RX018 | m4synthrehearsalv1_000303 | v4_retained | — | **no-slot** | — | — | thanh toán 7100012345678 đồng | neg so tien 13 so |
| 217 | RX019 | m4synthrehearsalv1_000304 | v4_retained | — | **no-slot** | — | — | phí ship 35000 nhé | neg phi ship |
| 218 | RX020 | m4synthrehearsalv1_000305 | v4_retained | — | **no-slot** | — | — | năm 2026 hết hạn nhé | neg nam |
| 219 | RX021 | m4synthrehearsalv1_000306 | v4_retained | — | **no-slot** | — | — | đơn A123 tới đâu rồi | neg ma don chu+so |
| 220 | RX022 | m4synthrehearsalv1_000307 | v4_retained | — | **no-slot** | — | — | lô hàng LOT20260813 tới chưa | neg ma lo chu+so |
| 221 | FNA001 | m4synthrehearsalv1_000401 | fnum03_new | A same-clause nid/bank collision | bank_account | (12, 24) | `079000012371` | cccd va stk 079000012371 nhe shop | A/collision: `stk` gan so hon `cccd` -> bank (decision B) |
| 222 | FNA002 | m4synthrehearsalv1_000402 | fnum03_new | A same-clause nid/bank collision | national_id | (12, 24) | `079000012372` | STK và CCCD 079000012372 ạ | A/collision: `CCCD` gan hon -> national_id; chieu nguoc cua FNA001 |
| 223 | FNA003 | m4synthrehearsalv1_000403 | fnum03_new | A same-clause nid/bank collision | national_id | (18, 30) | `079000012373` | so tai khoan cccd 079000012373 | A/collision: cue bank dai hon nhung `cccd` van gan so hon -> national_id |
| 224 | FNA004 | m4synthrehearsalv1_000404 | fnum03_new | A same-clause nid/bank collision | bank_account | (21, 33) | `079000012374` | cmnd va so tai khoan 079000012374 nhe | A/collision: `so tai khoan` gan hon `cmnd` -> bank |
| 225 | FNA005 | m4synthrehearsalv1_000405 | fnum03_new | A same-clause nid/bank collision | bank_account | (13, 25) | `079000012375` | can cuoc stk 079000012375 | A/collision: `stk` gan hon `can cuoc` -> bank |
| 226 | FNA006 | m4synthrehearsalv1_000406 | fnum03_new | A same-clause nid/bank collision | national_id | (13, 25) | `079000012376` | stk can cuoc 079000012376 | A/collision: `can cuoc` gan hon -> national_id; chieu nguoc cua FNA005 |
| 227 | FNA007 | m4synthrehearsalv1_000407 | fnum03_new | A same-clause nid/bank collision | national_id | (22, 34) | `079000012377` | tài khoản và căn cước 079000012377 nhé | A/collision CO DAU: `căn cước` gan hon -> national_id |
| 228 | FNA008 | m4synthrehearsalv1_000408 | fnum03_new | A same-clause nid/bank collision | bank_account | (18, 30) | `079000012378` | chứng minh và STK 079000012378 | A/collision CO DAU: `STK` gan hon -> bank |
| 229 | FNB001 | m4synthrehearsalv1_000409 | fnum03_new | B window / boundary | bank_account | (33, 44) | `71000123421` | stk cua em o ngan hang ben do la 71000123421 | B/window: cue cach ~29-35 ky tu, TRONG cua so 80 -> bank |
| 230 | FNB002 | m4synthrehearsalv1_000410 | fnum03_new | B window / boundary | bank_account | (43, 54) | `71000123422` | so tai khoan cua minh ben ngan hang ACB la 71000123422 | B/window: cue cach ~42 ky tu -> bank |
| 231 | FNB003 | m4synthrehearsalv1_000411 | fnum03_new | B window / boundary | bank_account | (56, 67) | `71000123423` | stk minh dang dung o ngan hang thuong mai co phan do la 71000123423 | B/window: cue cach ~55 ky tu -> bank |
| 232 | FNB004 | m4synthrehearsalv1_000412 | fnum03_new | B window / boundary | bank_account | (64, 75) | `71000123424` | stk cua em mo tai chi nhanh ngan hang gan nha ba ngoai o que la 71000123424 | B/window: cue cach ~63 ky tu, van trong 80 -> bank |
| 233 | FNB005 | m4synthrehearsalv1_000413 | fnum03_new | B window / boundary | **no-slot** | — | — | stk cua em mo tai chi nhanh ngan hang gan nha ba ngoai o duoi que mien tay xa lam la 71000123425 | B/window: cue cach >80 ky tu -> NGOAI cua so -> no-slot. So 11 chu so nen KHONG roi vao fallback national_id 12 so |
| 234 | FNB006 | m4synthrehearsalv1_000414 | fnum03_new | B window / boundary | **no-slot** | — | — | stk nha em mo tu hoi con o duoi que ngoai kia lau lam roi khong nho ro nam nao nua la 71000123426 | B/window: cue cach xa hon nua -> no-slot |
| 235 | FNB007 | m4synthrehearsalv1_000415 | fnum03_new | B window / boundary | national_id | (40, 52) | `079000012427` | cccd cua minh dang cam theo trong vi la 079000012427 | B/window: cue giay to cach ~38 ky tu -> national_id |
| 236 | FNB008 | m4synthrehearsalv1_000416 | fnum03_new | B window / boundary | national_id | (56, 68) | `079000012428` | can cuoc cua em vua lam lai o phuong hoi thang truoc la 079000012428 | B/window: cue giay to cach ~55 ky tu -> national_id |
| 237 | FNC001 | m4synthrehearsalv1_000417 | fnum03_new | C clause asymmetry | bank_account | (23, 34) | `71000123431` | so tai khoan cua minh, 71000123431 | C/clause: cue CUNG loai vuot dau phay -> bank (kieu viet rat pho bien) |
| 238 | FNC002 | m4synthrehearsalv1_000418 | fnum03_new | C clause asymmetry | bank_account | (12, 23) | `71000123432` | stk cua em,\n71000123432 | C/clause: cue CUNG loai vuot XUONG DONG -> bank |
| 239 | FNC003 | m4synthrehearsalv1_000419 | fnum03_new | C clause asymmetry | bank_account | (25, 36) | `71000123433` | stk cua em, vietcombank, 71000123433 | C/clause: cue CUNG loai vuot HAI menh de -> bank |
| 240 | FNC004 | m4synthrehearsalv1_000420 | fnum03_new | C clause asymmetry | bank_account | (30, 41) | `71000123434` | ma giao dich da xong roi, stk 71000123434 | C/clause: cue CANH TRANH o menh de TRUOC -> khong chan duoc -> bank |
| 241 | FNC005 | m4synthrehearsalv1_000421 | fnum03_new | C clause asymmetry | **no-slot** | — | — | so tai khoan, ma giao dich 71000123435 | C/clause: cue canh tranh `ma giao dich` gan hon trong CUNG menh de; cue bank o menh de truoc -> no-slot |
| 242 | FNC006 | m4synthrehearsalv1_000422 | fnum03_new | C clause asymmetry | national_id | (15, 27) | `079000012436` | cccd cua minh, 079000012436 | C/clause: cue giay to CUNG loai vuot dau phay -> national_id |
| 243 | FNC007 | m4synthrehearsalv1_000423 | fnum03_new | C clause asymmetry | national_id | (26, 38) | `079000012437` | ma don da giao xong, cccd 079000012437 | C/clause: cue loai tru o menh de truoc -> khong chan -> national_id |
| 244 | FNC008 | m4synthrehearsalv1_000424 | fnum03_new | C clause asymmetry | national_id | (5, 17) | `079000012438` | cccd 079000012438, stk 71000123439 | C/clause: HAI PII, moi so lay cue cua menh de rieng -> khong ro ri cheo menh de |
| 244 | FNC008 | m4synthrehearsalv1_000424 | fnum03_new | C clause asymmetry | bank_account | (23, 34) | `71000123439` | cccd 079000012438, stk 71000123439 | C/clause: HAI PII, moi so lay cue cua menh de rieng -> khong ro ri cheo menh de |
| 245 | FND001 | m4synthrehearsalv1_000425 | fnum03_new | D reference exclusion | **no-slot** | — | — | ma tham chieu 079000012441 nhe | D/reference: `ma tham chieu` -> KHONG fallback national_id (so 12 chu so) |
| 246 | FND002 | m4synthrehearsalv1_000426 | fnum03_new | D reference exclusion | **no-slot** | — | — | mã vận đơn 079000012442 đâu rồi shop | D/reference CO DAU: `mã vận đơn` -> no-slot |
| 247 | FND003 | m4synthrehearsalv1_000427 | fnum03_new | D reference exclusion | **no-slot** | — | — | ma tra cuu 079000012443 la gi vay | D/reference: `ma tra cuu` -> no-slot |
| 248 | FND004 | m4synthrehearsalv1_000428 | fnum03_new | D reference exclusion | **no-slot** | — | — | mã hóa đơn 079000012444 shop ơi | D/reference CO DAU: `mã hóa đơn` -> no-slot |
| 249 | FND005 | m4synthrehearsalv1_000429 | fnum03_new | D reference exclusion | **no-slot** | — | — | cho em xin lai ma van don 079000012445 | D/reference: cue nam giua cau -> no-slot |
| 250 | FND006 | m4synthrehearsalv1_000430 | fnum03_new | D reference exclusion | **no-slot** | — | — | ma tham chieu giao dich 079000012446 | D/reference: cue tham chieu ghep voi tu tai chinh -> van no-slot |
| 251 | FND007 | m4synthrehearsalv1_000431 | fnum03_new | D reference exclusion | **no-slot** | — | — | ma tra cuu don hang 079000012447 nhe | D/reference: hai cue loai tru cung luc -> no-slot |
| 252 | FND008 | m4synthrehearsalv1_000432 | fnum03_new | D reference exclusion | **no-slot** | — | — | mã hóa đơn của em là 079000012448 | D/reference CO DAU: cue cach so vai tu -> no-slot |
| 253 | FNE001 | m4synthrehearsalv1_000433 | fnum03_new | E bank-cue override + realistic | bank_account | (22, 33) | `71000123451` | ma tham chieu cho stk 71000123451 | E/override: `stk` gan hon `ma tham chieu` -> bank (rang buoc PO §1.4) |
| 254 | FNE002 | m4synthrehearsalv1_000434 | fnum03_new | E bank-cue override + realistic | bank_account | (24, 35) | `71000123452` | ma van don xong roi stk 71000123452 nhe | E/override KHONG DAU CAU: cue bank gan hon -> bank |
| 255 | FNE003 | m4synthrehearsalv1_000435 | fnum03_new | E bank-cue override + realistic | bank_account | (6, 17) | `71000123453` | stk 🌟 71000123453 | E/emoji: emoji ngoai BMP chen giua cue va so -> bank |
| 256 | FNE004 | m4synthrehearsalv1_000436 | fnum03_new | E bank-cue override + realistic | bank_account | (13, 24) | `71000123454` | số tài khoản 71000123454 nhé | E/co dau: bien the co dau -> bank |
| 257 | FNE005 | m4synthrehearsalv1_000437 | fnum03_new | E bank-cue override + realistic | bank_account | (13, 24) | `71000123455` | so tai khoan 71000123455 nhe | E/khong dau: bien the khong dau cua FNE004 -> bank |
| 258 | FNE006 | m4synthrehearsalv1_000438 | fnum03_new | E bank-cue override + realistic | bank_account | (17, 28) | `71000123456` | stk so tai khoan 71000123456 | E/tie cung nhom: hai cue CUNG nhom bank ke nhau -> bank, ket qua xac dinh |
| 259 | FNE007 | m4synthrehearsalv1_000439 | fnum03_new | E bank-cue override + realistic | bank_account | (18, 29) | `71000123457` | ma hoa don va stk 71000123457 | E/override: `stk` gan hon `ma hoa don` -> bank |
| 260 | FNE008 | m4synthrehearsalv1_000440 | fnum03_new | E bank-cue override + realistic | bank_account | (21, 32) | `71000123458` | chuyen khoan qua stk 71000123458 giup em | E/thuc te: cau chuyen khoan thong thuong -> bank |
