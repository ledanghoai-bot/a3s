-- 012: Dinh luong phuc vu quy doi don gia ly (quyet dinh PO 23/7/2026)
-- PO: phep quy doi "170k/50 ly = ~3.400d/ly" KHONG duoc hardcode trong
-- system_prompt.md — so ly/hu va don gia ly phai tinh tu du lieu products
-- (tool search_products tra ve serving_info). Theo KB V2 (SKL-PRD-004):
-- dung cu do luong la muong di kem, 1 muong ~ 1g.
--
-- DB dang chay da duoc ap tay ngay 23/7/2026 (docker exec psql) — file nay
-- de dam bao DB dung moi (initdb) co cung schema.

ALTER TABLE products ADD COLUMN IF NOT EXISTS net_weight_g INTEGER;
ALTER TABLE products ADD COLUMN IF NOT EXISTS serving_size_g NUMERIC(5,2);

-- Seed 3S-100G: hu 100g, dinh luong tham khao 2g/ly (~2 muong)
-- -> tool tu tinh ~50 ly/hu, khong hardcode o bat ky prompt/mo ta nao
UPDATE products SET net_weight_g = 100, serving_size_g = 2 WHERE sku = '3S-100G';

-- Bo phep quy doi cung "~50 ly/hu (2g/ly)" trong description seed cu (001).
-- Guard LIKE: DB dang chay da co description moi (sua qua dashboard) — khong de len.
UPDATE products
SET description = 'Cà phê sấy lạnh nguyên chất, 100% Robusta (phôi Ro-Express R100). Hòa tan 3 giây với nước nguội/đá.'
WHERE sku = '3S-100G' AND description LIKE '%50 ly%';
