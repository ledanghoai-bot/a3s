"use client";

import { useEffect, useState, Fragment } from "react";
import { apiFetch } from "../../lib/api";
import { useAuthGuard } from "../../lib/useAuthGuard";

function formatVnd(n) {
  return Number(n).toLocaleString("vi-VN") + "đ";
}

// Form them/sua 1 san pham - dung chung cho ca 2 truong hop (issue #8, Bat 2).
// Neu co `product` (object) -> mode sua, tu dien san; neu khong -> mode them moi.
function ProductForm({ product, onSaved, onCancel }) {
  const isEdit = !!product;
  const [sku, setSku] = useState(product?.sku || "");
  const [name, setName] = useState(product?.name || "");
  const [description, setDescription] = useState(product?.description || "");
  const [priceVnd, setPriceVnd] = useState(product?.price_vnd ?? "");
  const [stock, setStock] = useState(product?.stock ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function save() {
    setError(null);
    if (!name || priceVnd === "" || stock === "") {
      setError("Điền đủ tên, giá lẻ, tồn kho.");
      return;
    }
    if (!isEdit && !sku) {
      setError("Điền SKU cho sản phẩm mới.");
      return;
    }
    setBusy(true);
    try {
      if (isEdit) {
        await apiFetch(`/dashboard/products/${product.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name,
            description,
            price_vnd: Number(priceVnd),
            stock: Number(stock),
          }),
        });
      } else {
        await apiFetch("/dashboard/products", {
          method: "POST",
          body: JSON.stringify({
            sku,
            name,
            description,
            price_vnd: Number(priceVnd),
            stock: Number(stock),
          }),
        });
      }
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, background: "#fff", marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
        {isEdit ? `Sửa sản phẩm ${product.sku}` : "Thêm sản phẩm mới"}
      </div>
      {error && <div className="error-box">{error}</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxWidth: 420 }}>
        {!isEdit && (
          <input placeholder="SKU (vd 3S-100G)" value={sku} onChange={(e) => setSku(e.target.value)} />
        )}
        {isEdit && (
          <div style={{ fontSize: 12, color: "#999" }}>
            SKU: <strong>{product.sku}</strong> (không đổi được sau khi tạo)
          </div>
        )}
        <input placeholder="Tên sản phẩm" value={name} onChange={(e) => setName(e.target.value)} />
        <textarea
          placeholder="Mô tả (dùng ngay cho RAG — nên viết cụ thể: kích thước, đóng gói, điểm khác biệt...)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
        />
        <input
          type="number"
          placeholder="Giá lẻ (1-4 hũ, VNĐ)"
          value={priceVnd}
          onChange={(e) => setPriceVnd(e.target.value)}
        />
        <input
          type="number"
          placeholder="Tồn kho"
          value={stock}
          onChange={(e) => setStock(e.target.value)}
        />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button className="primary" disabled={busy} onClick={save}>
          {busy ? "Đang lưu..." : "Lưu"}
        </button>
        <button onClick={onCancel}>Huỷ</button>
      </div>
    </div>
  );
}

// Editor bac gia cho 1 san pham - thay TOAN BO danh sach moi lan luu (khop
// dung logic backend products.py:replace_price_tiers).
function TiersEditor({ product, onSaved, onCancel }) {
  const [rows, setRows] = useState(
    product.price_tiers.length > 0
      ? product.price_tiers.map((t) => ({ min_qty: t.min_qty, unit_price_vnd: t.unit_price_vnd }))
      : [{ min_qty: "", unit_price_vnd: "" }]
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function updateRow(i, field, value) {
    setRows((r) => r.map((row, idx) => (idx === i ? { ...row, [field]: value } : row)));
  }

  function addRow() {
    setRows((r) => [...r, { min_qty: "", unit_price_vnd: "" }]);
  }

  function removeRow(i) {
    setRows((r) => r.filter((_, idx) => idx !== i));
  }

  async function save() {
    setError(null);
    const cleaned = rows.filter((r) => r.min_qty !== "" && r.unit_price_vnd !== "");
    if (cleaned.length === 0) {
      setError("Cần ít nhất 1 bậc giá hợp lệ.");
      return;
    }
    setBusy(true);
    try {
      await apiFetch(`/dashboard/products/${product.id}/tiers`, {
        method: "PUT",
        body: JSON.stringify({
          tiers: cleaned.map((r) => ({ min_qty: Number(r.min_qty), unit_price_vnd: Number(r.unit_price_vnd) })),
        }),
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #eee", borderRadius: 8, padding: 12, background: "#fff", marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Bậc giá — {product.sku}</div>
      {error && <div className="error-box">{error}</div>}
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "center" }}>
          <input
            type="number"
            placeholder="Từ số lượng"
            value={r.min_qty}
            onChange={(e) => updateRow(i, "min_qty", e.target.value)}
            style={{ width: 140 }}
          />
          <span style={{ fontSize: 12, color: "#999" }}>hũ →</span>
          <input
            type="number"
            placeholder="Đơn giá VNĐ"
            value={r.unit_price_vnd}
            onChange={(e) => updateRow(i, "unit_price_vnd", e.target.value)}
            style={{ width: 160 }}
          />
          <button onClick={() => removeRow(i)} style={{ fontSize: 12 }}>
            Xoá dòng
          </button>
        </div>
      ))}
      <button onClick={addRow} style={{ fontSize: 12, marginBottom: 10 }}>
        + Thêm bậc giá
      </button>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="primary" disabled={busy} onClick={save}>
          {busy ? "Đang lưu..." : "Lưu bậc giá"}
        </button>
        <button onClick={onCancel}>Huỷ</button>
      </div>
    </div>
  );
}

export default function ProductsPage() {
  const ready = useAuthGuard();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editingTiersId, setEditingTiersId] = useState(null);
  const [busyDeleteId, setBusyDeleteId] = useState(null);

  useEffect(() => {
    if (ready) load();
  }, [ready]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch("/dashboard/products/full");
      setProducts(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function afterSave() {
    setShowAddForm(false);
    setEditingId(null);
    setEditingTiersId(null);
    load();
  }

  async function deleteProduct(id, sku) {
    const ok = window.confirm(`Xoá sản phẩm ${sku}? Sẽ bị từ chối nếu đã có đơn hàng liên quan.`);
    if (!ok) return;
    setBusyDeleteId(id);
    try {
      await apiFetch(`/dashboard/products/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      alert("Lỗi: " + err.message);
    } finally {
      setBusyDeleteId(null);
    }
  }

  if (!ready) return null;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20 }}>Sản phẩm</h1>
        {!showAddForm && (
          <button className="primary" onClick={() => setShowAddForm(true)}>
            + Thêm sản phẩm
          </button>
        )}
      </div>

      <p style={{ fontSize: 12, color: "#999", marginBottom: 12 }}>
        Mô tả sản phẩm nhập ở đây <strong>tự động dùng cho trò chuyện tự do (RAG)</strong> — cập
        nhật ngay khi lưu, không cần chạy script. Nội dung tĩnh trong{" "}
        <code>data/knowledge/product_profile.md</code> là nguồn riêng, không bị ảnh hưởng.
      </p>

      {showAddForm && (
        <ProductForm onSaved={afterSave} onCancel={() => setShowAddForm(false)} />
      )}

      {error && <div className="error-box">{error}</div>}
      {loading ? (
        <div className="empty-state">Đang tải...</div>
      ) : products.length === 0 ? (
        <div className="empty-state">Chưa có sản phẩm nào.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Tên</th>
              <th>Giá lẻ</th>
              <th>Tồn kho</th>
              <th>Bậc giá</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {products.map((p) => (
              <Fragment key={p.id}>
                <tr>
                  <td>{p.sku}</td>
                  <td>{p.name}</td>
                  <td>{formatVnd(p.price_vnd)}</td>
                  <td>{p.stock}</td>
                  <td style={{ fontSize: 12 }}>
                    {p.price_tiers.length === 0
                      ? "(chưa có bậc giá)"
                      : p.price_tiers.map((t) => `${t.min_qty}+: ${formatVnd(t.unit_price_vnd)}`).join(" · ")}
                  </td>
                  <td style={{ display: "flex", gap: 6 }}>
                    <button
                      style={{ fontSize: 12 }}
                      onClick={() => {
                        setEditingId(editingId === p.id ? null : p.id);
                        setEditingTiersId(null);
                      }}
                    >
                      Sửa
                    </button>
                    <button
                      style={{ fontSize: 12 }}
                      onClick={() => {
                        setEditingTiersId(editingTiersId === p.id ? null : p.id);
                        setEditingId(null);
                      }}
                    >
                      Bậc giá
                    </button>
                    <button
                      style={{ fontSize: 12 }}
                      disabled={busyDeleteId === p.id}
                      onClick={() => deleteProduct(p.id, p.sku)}
                    >
                      {busyDeleteId === p.id ? "..." : "Xoá"}
                    </button>
                  </td>
                </tr>
                {editingId === p.id && (
                  <tr>
                    <td colSpan={6}>
                      <ProductForm product={p} onSaved={afterSave} onCancel={() => setEditingId(null)} />
                    </td>
                  </tr>
                )}
                {editingTiersId === p.id && (
                  <tr>
                    <td colSpan={6}>
                      <TiersEditor product={p} onSaved={afterSave} onCancel={() => setEditingTiersId(null)} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
