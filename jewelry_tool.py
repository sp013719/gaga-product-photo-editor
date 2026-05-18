#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
珠寶代購圖片工具 - PoC
用法：python jewelry_tool.py
"""

import csv
import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False

# ─── 字體 ────────────────────────────────────────────────────────────────────

def _find_font():
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
        "/Library/Fonts/Arial Unicode MS.ttf",
        # Windows fallback（開發環境）
        "C:/Windows/Fonts/msjh.ttc",
        "C:/Windows/Fonts/mingliu.ttc",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

FONT_PATH = _find_font()

def get_font(size):
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ─── 路徑 & Firebase 初始化 ───────────────────────────────────────────────────

def _base_dir() -> str:
    """打包成 .exe 後用 sys.executable 路徑，開發時用 __file__ 路徑"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

SERVICE_ACCOUNT_FILE = os.path.join(_base_dir(), "firebase_service_account.json")
FIRESTORE_COLLECTION  = "jewelry-tool"
FIRESTORE_DOC         = "shared"

_db = None

def _get_db():
    global _db
    if _db is not None:
        return _db
    if not FIREBASE_AVAILABLE:
        raise RuntimeError("firebase-admin 套件未安裝，請執行 pip install firebase-admin")
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f"找不到 Firebase 金鑰檔：{SERVICE_ACCOUNT_FILE}\n"
            "請將 firebase_service_account.json 放在與程式相同的資料夾中。"
        )
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
        firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _db


def _shared_doc():
    return _get_db().collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOC)


# ─── 設定 ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        doc = _shared_doc().get()
        if doc.exists:
            return doc.to_dict().get("config", {})
    except Exception as e:
        messagebox.showwarning("Firebase 讀取失敗", f"無法讀取設定，使用預設值。\n{e}")
    return {}

def save_config(cfg: dict):
    try:
        _shared_doc().set({"config": cfg}, merge=True)
    except Exception as e:
        messagebox.showerror("Firebase 寫入失敗", f"設定未能儲存至雲端。\n{e}")


# ─── 廠商 ─────────────────────────────────────────────────────────────────────

def load_vendors() -> list[dict]:
    try:
        doc = _shared_doc().get()
        if doc.exists:
            return doc.to_dict().get("vendors", [])
    except Exception as e:
        messagebox.showwarning("Firebase 讀取失敗", f"無法讀取廠商資料。\n{e}")
    return []

def save_vendors(vendors: list[dict]):
    try:
        _shared_doc().set({"vendors": vendors}, merge=True)
    except Exception as e:
        messagebox.showerror("Firebase 寫入失敗", f"廠商資料未能儲存至雲端。\n{e}")


# ─── 加成區間 ─────────────────────────────────────────────────────────────────

def load_markups() -> list[dict]:
    try:
        doc = _shared_doc().get()
        if doc.exists:
            rows = doc.to_dict().get("markups", [])
            rows.sort(key=lambda r: float(r.get("min_price") or 0))
            return rows
    except Exception as e:
        messagebox.showwarning("Firebase 讀取失敗", f"無法讀取加成資料。\n{e}")
    return []

def save_markups(markups: list[dict]):
    try:
        _shared_doc().set({"markups": markups}, merge=True)
    except Exception as e:
        messagebox.showerror("Firebase 寫入失敗", f"加成資料未能儲存至雲端。\n{e}")


# ─── 廠商管理視窗 ─────────────────────────────────────────────────────────────

class VendorDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, on_save):
        super().__init__(parent)
        self.title("管理廠商折扣")
        self.geometry("440x400")
        self.resizable(False, False)
        self.grab_set()  # modal

        self.on_save = on_save
        self.vendors: list[dict] = load_vendors()

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        # 列表
        lf = ttk.Frame(self, padding=10)
        lf.pack(fill=tk.BOTH, expand=True)

        ttk.Label(lf, text="廠商名稱").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(lf, text="折扣 %").grid(row=0, column=1, sticky=tk.W, padx=(10, 0))

        list_frame = ttk.Frame(lf)
        list_frame.grid(row=1, column=0, columnspan=3, sticky=tk.NSEW, pady=(4, 8))
        lf.rowconfigure(1, weight=1)
        lf.columnconfigure(0, weight=1)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=sb.set, font=("", 11), height=8)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        # 編輯欄
        edit_frame = ttk.Frame(lf)
        edit_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))

        # 第一行：名稱 + 折扣
        row1 = ttk.Frame(edit_frame)
        row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row1, text="名稱").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.name_var, width=16).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row1, text="折扣 %").pack(side=tk.LEFT)
        self.discount_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.discount_var, width=6).pack(side=tk.LEFT, padx=4)

        # 第二行：含稅勾選 + 稅率
        row2 = ttk.Frame(edit_frame)
        row2.pack(fill=tk.X)
        self.tax_included_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="報價含稅", variable=self.tax_included_var,
                        command=self._toggle_tax_rate).pack(side=tk.LEFT)
        ttk.Label(row2, text="稅率 %").pack(side=tk.LEFT, padx=(12, 0))
        self.tax_rate_var = tk.StringVar()
        self.tax_rate_entry = ttk.Entry(row2, textvariable=self.tax_rate_var, width=6,
                                        state=tk.DISABLED)
        self.tax_rate_entry.pack(side=tk.LEFT, padx=4)

        # 操作按鈕
        btn_frame = ttk.Frame(lf)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW)

        ttk.Button(btn_frame, text="新增 / 更新", command=self._upsert).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="刪除選取",   command=self._delete).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="儲存並關閉", command=self._save_and_close).pack(side=tk.RIGHT)

    def _toggle_tax_rate(self):
        state = tk.NORMAL if self.tax_included_var.get() else tk.DISABLED
        self.tax_rate_entry.config(state=state)
        if not self.tax_included_var.get():
            self.tax_rate_var.set("")

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for v in self.vendors:
            tax_label = ""
            if v.get("tax_included") == "1":
                rate = v.get("tax_rate", "")
                tax_label = f"  ｜ 含稅 {rate}%" if rate else "  ｜ 含稅"
            self.listbox.insert(tk.END, f"{v['name']}  —  {v['discount']}%{tax_label}")

    def _on_select(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        v = self.vendors[sel[0]]
        self.name_var.set(v["name"])
        self.discount_var.set(v["discount"])
        included = v.get("tax_included") == "1"
        self.tax_included_var.set(included)
        self.tax_rate_var.set(v.get("tax_rate", "") if included else "")
        self.tax_rate_entry.config(state=tk.NORMAL if included else tk.DISABLED)

    def _upsert(self):
        name     = self.name_var.get().strip()
        discount = self.discount_var.get().strip()
        if not name or not discount:
            messagebox.showwarning("提示", "名稱和折扣都不能空白", parent=self)
            return
        try:
            float(discount)
        except ValueError:
            messagebox.showwarning("提示", "折扣請輸入數字（例：85）", parent=self)
            return
        tax_included = self.tax_included_var.get()
        tax_rate     = self.tax_rate_var.get().strip()
        if tax_included and tax_rate:
            try:
                float(tax_rate)
            except ValueError:
                messagebox.showwarning("提示", "稅率請輸入數字（例：10）", parent=self)
                return

        entry = {
            "name":         name,
            "discount":     discount,
            "tax_included": "1" if tax_included else "0",
            "tax_rate":     tax_rate if tax_included else "",
        }
        # 若名稱已存在則更新，否則新增
        for v in self.vendors:
            if v["name"] == name:
                v.update(entry)
                self._refresh_list()
                return
        self.vendors.append(entry)
        self._refresh_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.vendors.pop(sel[0])
        self.name_var.set("")
        self.discount_var.set("")
        self._refresh_list()

    def _save_and_close(self):
        save_vendors(self.vendors)
        self.on_save(self.vendors)
        self.destroy()


# ─── 加成管理視窗 ─────────────────────────────────────────────────────────────

class MarkupDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, on_save):
        super().__init__(parent)
        self.title("管理加成區間")
        self.geometry("420x380")
        self.resizable(False, False)
        self.grab_set()

        self.on_save = on_save
        self.markups: list[dict] = load_markups()

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        lf = ttk.Frame(self, padding=10)
        lf.pack(fill=tk.BOTH, expand=True)

        ttk.Label(lf, text="價格區間與加成設定（台幣，空白最高價 = 無上限）",
                  font=("", 9), foreground="gray").grid(row=0, column=0, columnspan=3,
                  sticky=tk.W, pady=(0, 4))

        list_frame = ttk.Frame(lf)
        list_frame.grid(row=1, column=0, columnspan=3, sticky=tk.NSEW, pady=(0, 8))
        lf.rowconfigure(1, weight=1)
        lf.columnconfigure(0, weight=1)

        sb = ttk.Scrollbar(list_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(list_frame, yscrollcommand=sb.set, font=("", 11), height=8)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        # 編輯欄
        edit_frame = ttk.Frame(lf)
        edit_frame.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(0, 8))

        ttk.Label(edit_frame, text="最低價").pack(side=tk.LEFT)
        self.min_var = tk.StringVar()
        ttk.Entry(edit_frame, textvariable=self.min_var, width=7).pack(side=tk.LEFT, padx=(4, 8))

        ttk.Label(edit_frame, text="最高價").pack(side=tk.LEFT)
        self.max_var = tk.StringVar()
        ttk.Entry(edit_frame, textvariable=self.max_var, width=7).pack(side=tk.LEFT, padx=(4, 8))

        ttk.Label(edit_frame, text="加成 %").pack(side=tk.LEFT)
        self.markup_var = tk.StringVar()
        ttk.Entry(edit_frame, textvariable=self.markup_var, width=6).pack(side=tk.LEFT, padx=4)

        btn_frame = ttk.Frame(lf)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky=tk.EW)

        ttk.Button(btn_frame, text="新增 / 更新", command=self._upsert).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="刪除選取",   command=self._delete).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="儲存並關閉", command=self._save_and_close).pack(side=tk.RIGHT)

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for m in self.markups:
            max_label = m["max_price"] if m["max_price"] else "∞"
            self.listbox.insert(tk.END, f"$ {m['min_price']} ~ {max_label}  →  {m['markup']}%")

    def _on_select(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        m = self.markups[sel[0]]
        self.min_var.set(m["min_price"])
        self.max_var.set(m["max_price"])
        self.markup_var.set(m["markup"])

    def _upsert(self):
        min_p  = self.min_var.get().strip()
        max_p  = self.max_var.get().strip()
        markup = self.markup_var.get().strip()
        if not min_p or not markup:
            messagebox.showwarning("提示", "最低價和加成不能空白", parent=self)
            return
        try:
            float(min_p)
            if max_p:
                float(max_p)
            float(markup)
        except ValueError:
            messagebox.showwarning("提示", "請輸入有效數字", parent=self)
            return

        # 以最低價為 key 更新，否則新增
        for m in self.markups:
            if m["min_price"] == min_p:
                m["max_price"] = max_p
                m["markup"]    = markup
                self.markups.sort(key=lambda r: float(r["min_price"] or 0))
                self._refresh_list()
                return
        self.markups.append({"min_price": min_p, "max_price": max_p, "markup": markup})
        self.markups.sort(key=lambda r: float(r["min_price"] or 0))
        self._refresh_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.markups.pop(sel[0])
        self.min_var.set("")
        self.max_var.set("")
        self.markup_var.set("")
        self._refresh_list()

    def _save_and_close(self):
        save_markups(self.markups)
        self.on_save(self.markups)
        self.destroy()


# ─── 圖片疊字 ────────────────────────────────────────────────────────────────

def overlay_image(src_path: str, data: dict, output_path: str):
    """在圖片底部疊加商品資訊欄"""
    img = Image.open(src_path).convert("RGBA")
    w, h = img.size

    # 資訊欄高度：圖片高度 20%，最少 120px
    bar_h = max(120, int(h * 0.20))

    # 半透明黑色底欄
    bar = Image.new("RGBA", (w, bar_h), (15, 15, 15, 210))
    draw = ImageDraw.Draw(bar)

    # 字體大小依圖片寬度計算初始值
    name_sz  = max(26, int(w * 0.048))
    sub_sz   = max(19, int(w * 0.033))
    price_sz = max(30, int(w * 0.055))

    # 等比縮放：確保三行文字加上行距能放入 bar（保留上下各 10% padding）
    line_gaps   = 22                          # 兩個行間距 (10 + 12)
    max_text_h  = bar_h - int(bar_h * 0.20)  # 可用文字高度
    total_text_h = name_sz + sub_sz + price_sz + line_gaps
    if total_text_h > max_text_h:
        scale    = max_text_h / total_text_h
        name_sz  = int(name_sz  * scale)
        sub_sz   = int(sub_sz   * scale)
        price_sz = int(price_sz * scale)

    padding = int(w * 0.03)
    y = int(bar_h * 0.1)

    # 商品名稱（白色）
    name = data.get("name", "").strip()
    if name:
        draw.text((padding, y), name, font=get_font(name_sz), fill=(255, 255, 255, 255))
        y += name_sz + 10

    # 材質 + 說明（淺灰色）
    parts = [data.get("material", "").strip(), data.get("description", "").strip()]
    sub = "  ｜  ".join(p for p in parts if p)
    if sub:
        draw.text((padding, y), sub, font=get_font(sub_sz), fill=(195, 195, 195, 255))
        y += sub_sz + 12

    # 售價（金色，靠右）
    price = data.get("final_price", "").strip()
    if price:
        font_p = get_font(price_sz)
        # 計算文字寬度以靠右對齊
        try:
            bbox = draw.textbbox((0, 0), price, font=font_p)
            txt_w = bbox[2] - bbox[0]
        except AttributeError:
            txt_w = price_sz * len(price) // 2
        x_price = max(padding, w - txt_w - padding)
        draw.text((x_price, y), price, font=font_p, fill=(255, 210, 50, 255))

    # 合成並儲存
    img.paste(bar, (0, h - bar_h), bar)
    img.convert("RGB").save(output_path, quality=95)


# ─── GUI ─────────────────────────────────────────────────────────────────────

class JewelryApp:
    FIELDS = [
        ("商品名稱 *", "name"),
        ("材質 *",     "material"),
        ("其他說明",   "description"),
    ]
    PRICE_FIELDS = [
        ("廠商報價", "cost"),
        ("匯率",     "rate"),       # 例：31.5 代表 1 USD = 31.5 TWD
        ("折扣 %",   "discount"),   # 例：85 代表 85折（×0.85）
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("珠寶代購圖片工具")
        self.root.geometry("1200x720")
        self.root.minsize(900, 560)

        # 商品群組資料模型
        self.products: list[dict] = []
        self.current_product_idx: int | None = None
        self.current_image_path: str | None = None

        self._preview_photo = None
        self._loading_form = False
        self.vendors: list[dict] = load_vendors()
        self.markups: list[dict] = load_markups()
        self._auto_filling_markup = False
        cfg = load_config()
        self._default_rate: str = cfg.get("default_rate", "")

        self._build_ui()

    # ── 建構介面 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # 頂部標題列
        header = ttk.Frame(self.root, padding=(12, 8))
        header.pack(fill=tk.X)
        ttk.Label(header, text="珠寶代購圖片工具", font=("", 17, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="  產生所有圖片  ", command=self.generate_all).pack(side=tk.RIGHT)

        ttk.Separator(self.root).pack(fill=tk.X)

        # 主體：左右 Paned
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        # ── 左側：商品/圖片樹狀列表 ──
        left = ttk.Frame(paned, width=260)
        paned.add(left, weight=0)

        ttk.Label(left, text="商品列表", font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 4))

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree = ttk.Treeview(tree_frame, yscrollcommand=sb.set,
                                  show="tree", selectmode="extended")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.tree.yview)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Control-a>", self._select_all)
        self.tree.bind("<Command-a>", self._select_all)  # macOS

        ttk.Button(left, text="＋ 新增商品", command=self.add_product).pack(fill=tk.X, pady=(6, 2))
        ttk.Button(left, text="＋ 新增圖片", command=self.add_images).pack(fill=tk.X, pady=(0, 2))
        ttk.Button(left, text="✕ 移除選取", command=self.remove_selected).pack(fill=tk.X)

        # ── 中欄：預覽 ──
        middle = ttk.Frame(paned)
        paned.add(middle, weight=1)

        pf = ttk.LabelFrame(middle, text="預覽", padding=6)
        pf.pack(fill=tk.BOTH, expand=True)
        self.preview_label = ttk.Label(pf, text="← 新增商品並選取圖片以預覽", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        pf.bind("<Configure>", lambda e: self._refresh_preview())

        # ── 右欄：商品資訊 + 定價計算 ──
        right = ttk.Frame(paned, width=400)
        paned.add(right, weight=0)

        # 商品資訊
        form_frame = ttk.LabelFrame(right, text="商品資訊", padding=10)
        form_frame.pack(fill=tk.X, pady=(0, 6))

        self.vars: dict[str, tk.StringVar] = {}
        for label, key in self.FIELDS:
            row = ttk.Frame(form_frame)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, width=8, anchor=tk.W).pack(side=tk.LEFT)
            v = tk.StringVar()
            v.trace_add("write", lambda *a, k=key: self._on_text_field_change(k))
            ttk.Entry(row, textvariable=v).pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.vars[key] = v

        # 定價計算
        col2 = ttk.LabelFrame(right, text="定價計算", padding=8)
        col2.pack(fill=tk.X)

        # 預設匯率
        rate_row = ttk.Frame(col2)
        rate_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(rate_row, text="預設匯率", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.default_rate_var = tk.StringVar(value=self._default_rate)
        ttk.Entry(rate_row, textvariable=self.default_rate_var, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(rate_row, text="套用至全部", command=self._apply_rate_to_all).pack(side=tk.LEFT)
        self.default_rate_var.trace_add("write", lambda *a: self._save_default_rate())

        ttk.Separator(col2, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 6))

        # 廠商下拉
        vendor_row = ttk.Frame(col2)
        vendor_row.pack(fill=tk.X, pady=3)
        ttk.Label(vendor_row, text="廠商", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.vendor_var = tk.StringVar(value="（不選取）")
        self.vendor_combo = ttk.Combobox(vendor_row, textvariable=self.vendor_var,
                                         width=16, state="readonly")
        self.vendor_combo.pack(side=tk.LEFT)
        self.vendor_combo.bind("<<ComboboxSelected>>", self._on_vendor_select)
        ttk.Button(vendor_row, text="管理", width=4,
                   command=self._open_vendor_dialog).pack(side=tk.LEFT, padx=(4, 0))
        self._reload_vendor_dropdown()

        # 廠商報價、匯率、折扣（變動時觸發自動查加成）
        for label, key in self.PRICE_FIELDS:
            row = ttk.Frame(col2)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, width=8, anchor=tk.W).pack(side=tk.LEFT)
            v = tk.StringVar()
            v.trace_add("write", lambda *a: self._on_price_input_change())
            ttk.Entry(row, textvariable=v, width=14).pack(side=tk.LEFT)
            self.vars[key] = v

        # 加成（可手動覆蓋；自動查表帶入）
        markup_row = ttk.Frame(col2)
        markup_row.pack(fill=tk.X, pady=3)
        ttk.Label(markup_row, text="加成 %", width=8, anchor=tk.W).pack(side=tk.LEFT)
        markup_v = tk.StringVar()
        markup_v.trace_add("write", lambda *a: self._calc_and_save_price())
        ttk.Entry(markup_row, textvariable=markup_v, width=14).pack(side=tk.LEFT)
        ttk.Button(markup_row, text="管理", width=4,
                   command=self._open_markup_dialog).pack(side=tk.LEFT, padx=(4, 0))
        self.vars["markup"] = markup_v

        ttk.Separator(col2, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        cost_row = ttk.Frame(col2)
        cost_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(cost_row, text="成本", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.cost_label = ttk.Label(cost_row, text="--", font=("", 12), foreground="#555555")
        self.cost_label.pack(side=tk.LEFT)

        ttk.Label(col2, text="台幣成本 = 報價 × 折扣 ÷ (1 + 稅率)",
                  font=("", 8), foreground="gray").pack(anchor=tk.W, pady=(0, 4))

        price_row = ttk.Frame(col2)
        price_row.pack(fill=tk.X)
        ttk.Label(price_row, text="售價", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.price_label = ttk.Label(price_row, text="--", font=("", 15, "bold"), foreground="#c0392b")
        self.price_label.pack(side=tk.LEFT)

        ttk.Label(col2, text="售價 = 台幣成本 × (1 + 加成)",
                  font=("", 8), foreground="gray").pack(anchor=tk.W, pady=(4, 0))

        # 輸出路徑列
        bot = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bot.pack(fill=tk.X)
        ttk.Label(bot, text="輸出資料夾：").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value=os.path.expanduser("~/Desktop/珠寶圖片輸出"))
        ttk.Entry(bot, textvariable=self.output_var, width=42).pack(side=tk.LEFT, padx=5)
        ttk.Button(bot, text="選擇", command=self._choose_output).pack(side=tk.LEFT)

    # ── 商品管理 ──────────────────────────────────────────────────────────────

    def _new_product(self) -> dict:
        return {
            "name": "", "material": "", "description": "",
            "cost": "", "rate": self._default_rate, "discount": "",
            "markup": "", "tax_included": "0", "tax_rate": "",
            "final_price": "", "vendor_name": "（不選取）",
            "images": [],
        }

    def add_product(self):
        self._save_current()
        product = self._new_product()
        self.products.append(product)
        idx = len(self.products) - 1
        self._rebuild_tree()
        piid = f"p:{idx}"
        self.tree.selection_set(piid)
        self.tree.see(piid)
        self.current_product_idx = idx
        self.current_image_path = None
        self._load_product(idx)

    def _rebuild_tree(self):
        # 記住哪些節點是展開狀態
        open_set = {iid for iid in self.tree.get_children("")
                    if self.tree.item(iid, "open")}
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(self.products):
            name = p.get("name", "").strip() or f"（商品 {i + 1}）"
            img_count = len(p["images"])
            label = f"{name}  [{img_count}張]" if img_count else name
            piid = f"p:{i}"
            # 新商品預設展開；舊商品保持原本狀態（預設展開）
            is_open = piid not in open_set or open_set  # 保持展開
            self.tree.insert("", tk.END, iid=piid, text=label, open=True)
            for j, img_path in enumerate(p["images"]):
                self.tree.insert(piid, tk.END, iid=f"i:{i}:{j}",
                                 text=os.path.basename(img_path))

    def _update_tree_label(self, idx: int):
        """更新指定商品節點的顯示文字（商品名稱變動時即時更新）"""
        p = self.products[idx]
        name = p.get("name", "").strip() or f"（商品 {idx + 1}）"
        img_count = len(p["images"])
        label = f"{name}  [{img_count}張]" if img_count else name
        try:
            self.tree.item(f"p:{idx}", text=label)
        except tk.TclError:
            pass

    # ── 圖片管理 ──────────────────────────────────────────────────────────────

    def add_images(self):
        if self.current_product_idx is None:
            messagebox.showwarning("提示", "請先選取或新增一個商品")
            return
        paths = filedialog.askopenfilenames(
            title="選擇商品圖片",
            filetypes=[("圖片檔", "*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG"), ("所有檔案", "*.*")],
        )
        if not paths:
            return
        product = self.products[self.current_product_idx]
        added = []
        for p in paths:
            if p not in product["images"]:
                product["images"].append(p)
                added.append(p)
        if added:
            self._rebuild_tree()
            # 自動選取第一張新增的圖片
            img_idx = product["images"].index(added[0])
            iid = f"i:{self.current_product_idx}:{img_idx}"
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self.current_image_path = added[0]
            self._refresh_preview()

    def remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return

        # 分類：要刪除的商品索引 vs 要刪除的圖片（僅在商品不被刪除時）
        product_indices = {int(s.split(":")[1]) for s in sel if s.startswith("p:")}
        image_removals: dict[int, list[int]] = {}
        for s in sel:
            if s.startswith("i:"):
                parts = s.split(":")
                pidx, iidx = int(parts[1]), int(parts[2])
                if pidx not in product_indices:
                    image_removals.setdefault(pidx, []).append(iidx)

        # 先刪圖片（從後往前避免 index 位移）
        for pidx, indices in image_removals.items():
            if pidx < len(self.products):
                for i in sorted(indices, reverse=True):
                    if i < len(self.products[pidx]["images"]):
                        self.products[pidx]["images"].pop(i)

        # 再刪商品（從後往前）
        for idx in sorted(product_indices, reverse=True):
            if idx < len(self.products):
                self.products.pop(idx)

        self.current_product_idx = None
        self.current_image_path = None
        self._rebuild_tree()
        self._clear_form()

    # ── 樹狀選取 ──────────────────────────────────────────────────────────────

    def _select_all(self, _event=None):
        for piid in self.tree.get_children(""):
            self.tree.selection_add(piid)
            for ciid in self.tree.get_children(piid):
                self.tree.selection_add(ciid)
        return "break"

    def _on_tree_select(self, _event):
        focused = self.tree.focus()
        if not focused:
            return
        if focused.startswith("p:"):
            idx = int(focused.split(":")[1])
            if idx != self.current_product_idx:
                self._save_current()
                self.current_product_idx = idx
                self._load_product(idx)
            self.current_image_path = None
            self._refresh_preview()
        elif focused.startswith("i:"):
            parts = focused.split(":")
            product_idx, image_idx = int(parts[1]), int(parts[2])
            if product_idx != self.current_product_idx:
                self._save_current()
                self.current_product_idx = product_idx
                self._load_product(product_idx)
            self.current_image_path = self.products[product_idx]["images"][image_idx]
            self._refresh_preview()

    # ── 廠商 ──────────────────────────────────────────────────────────────────

    def _save_default_rate(self):
        rate = self.default_rate_var.get().strip()
        self._default_rate = rate
        cfg = load_config()
        cfg["default_rate"] = rate
        save_config(cfg)

    def _apply_rate_to_all(self):
        rate = self.default_rate_var.get().strip()
        if not rate:
            return
        for p in self.products:
            p["rate"] = rate
        if self.current_product_idx is not None:
            self._loading_form = True
            self.vars["rate"].set(rate)
            self._loading_form = False
            self._calc_and_save_price()

    def _reload_vendor_dropdown(self):
        names = ["（不選取）"] + [v["name"] for v in self.vendors]
        self.vendor_combo["values"] = names
        if self.vendor_var.get() not in names:
            self.vendor_var.set("（不選取）")

    def _on_vendor_select(self, _event):
        name = self.vendor_var.get()
        if self.current_product_idx is not None:
            self.products[self.current_product_idx]["vendor_name"] = name
        for v in self.vendors:
            if v["name"] == name:
                self._loading_form = True
                self.vars["discount"].set(v["discount"])
                self._loading_form = False
                if self.current_product_idx is not None:
                    p = self.products[self.current_product_idx]
                    p["tax_included"] = v.get("tax_included", "0")
                    p["tax_rate"]     = v.get("tax_rate", "")
                self._on_price_input_change()
                return

    def _open_vendor_dialog(self):
        def on_save(updated_vendors):
            self.vendors = updated_vendors
            self._reload_vendor_dropdown()
        VendorDialog(self.root, on_save)

    # ── 表單讀寫 ──────────────────────────────────────────────────────────────

    def _on_text_field_change(self, key: str):
        if self._loading_form or self.current_product_idx is None:
            return
        p = self.products[self.current_product_idx]
        p[key] = self.vars[key].get()
        if key == "name":
            self._update_tree_label(self.current_product_idx)

    def _on_price_input_change(self):
        """cost / rate / discount 變動時：先自動查加成，再算售價"""
        if self._loading_form or self.current_product_idx is None:
            return
        markup = self._lookup_markup()
        if markup is not None:
            self._auto_filling_markup = True
            self.vars["markup"].set(markup)
            self._auto_filling_markup = False
        self._calc_and_save_price()

    def _calc_net_cost(self) -> float | None:
        """成本 = 報價 × 匯率 × (折扣/100) / (1 + 稅率/100)"""
        try:
            vendor_price = float(self.vars["cost"].get()     or 0)
            rate         = float(self.vars["rate"].get()     or 1)
            discount     = float(self.vars["discount"].get() or 100)
            intermediate = vendor_price * rate * (discount / 100)
            if self.current_product_idx is not None:
                p = self.products[self.current_product_idx]
                if p.get("tax_included") == "1":
                    tax_rate = float(p.get("tax_rate") or 0)
                    intermediate = intermediate / (1 + tax_rate / 100)
            return intermediate
        except (ValueError, ZeroDivisionError):
            return None

    def _lookup_markup(self) -> str | None:
        """根據稅後成本查對應加成區間，找不到回傳 None"""
        net_cost = self._calc_net_cost()
        if net_cost is None:
            return None
        for rule in self.markups:
            min_p = float(rule["min_price"] or 0)
            max_p = float(rule["max_price"]) if rule["max_price"] else float("inf")
            if min_p <= net_cost <= max_p:
                return rule["markup"]
        return None

    def _open_markup_dialog(self):
        def on_save(updated):
            self.markups = updated
        MarkupDialog(self.root, on_save)

    def _calc_and_save_price(self):
        if self._loading_form or self._auto_filling_markup or self.current_product_idx is None:
            return
        p = self.products[self.current_product_idx]
        for key in ["cost", "rate", "discount", "markup"]:
            p[key] = self.vars[key].get()
        try:
            vendor_price = float(self.vars["cost"].get()     or 0)
            rate         = float(self.vars["rate"].get()     or 1)
            discount     = float(self.vars["discount"].get() or 100)
            markup       = float(self.vars["markup"].get()   or 0)

            tax_rate = float(p.get("tax_rate") or 0) if p.get("tax_included") == "1" else 0

            # 原幣成本（折扣後退稅）
            original_cost = vendor_price * (discount / 100) / (1 + tax_rate / 100)
            # 台幣成本
            twd_cost = original_cost * rate
            # 售價（四捨五入至十位）
            final    = int(twd_cost * (1 + markup / 100) / 10 + 0.5) * 10

            cost_display = f"$ {twd_cost:,.0f}  ({original_cost:,.0f})"
            self.cost_label.config(text=cost_display)

            price_display = f"$ {final:,.0f}"
            self.price_label.config(text=price_display)
            p["final_price"] = price_display
        except (ValueError, TypeError):
            self.cost_label.config(text="--")
            self.price_label.config(text="--")
            p["final_price"] = ""

    def _save_current(self):
        if self.current_product_idx is None:
            return
        p = self.products[self.current_product_idx]
        for key in ["name", "material", "description"]:
            p[key] = self.vars[key].get()
        p["vendor_name"] = self.vendor_var.get()

    def _load_product(self, idx: int):
        self._loading_form = True
        p = self.products[idx]
        for key in ["name", "material", "description", "cost", "rate", "discount", "markup"]:
            self.vars[key].set(p.get(key, ""))
        vendor_name = p.get("vendor_name", "（不選取）")
        combo_values = self.vendor_combo["values"]
        self.vendor_var.set(vendor_name if vendor_name in combo_values else "（不選取）")
        price = p.get("final_price", "")
        self.price_label.config(text=price if price else "--")
        self._loading_form = False
        # 重新計算成本顯示
        self._recalc_display()

    def _recalc_display(self):
        """載入表單後重新計算並顯示成本/售價（不寫回資料）"""
        if self.current_product_idx is None:
            return
        try:
            p = self.products[self.current_product_idx]
            vendor_price = float(self.vars["cost"].get()     or 0)
            rate         = float(self.vars["rate"].get()     or 1)
            discount     = float(self.vars["discount"].get() or 100)
            markup       = float(self.vars["markup"].get()   or 0)
            tax_rate     = float(p.get("tax_rate") or 0) if p.get("tax_included") == "1" else 0
            original_cost = vendor_price * (discount / 100) / (1 + tax_rate / 100)
            twd_cost      = original_cost * rate
            final         = int(twd_cost * (1 + markup / 100) / 10 + 0.5) * 10
            self.cost_label.config(text=f"$ {twd_cost:,.0f}  ({original_cost:,.0f})")
            self.price_label.config(text=f"$ {final:,.0f}")
        except (ValueError, TypeError):
            self.cost_label.config(text="--")

    def _clear_form(self):
        self._loading_form = True
        for v in self.vars.values():
            v.set("")
        self.vendor_var.set("（不選取）")
        self.cost_label.config(text="--")
        self.price_label.config(text="--")
        self.preview_label.config(image="", text="← 新增商品並選取圖片以預覽")
        self._preview_photo = None
        self._loading_form = False

    # ── 預覽 ──────────────────────────────────────────────────────────────────

    def _refresh_preview(self):
        if not self.current_image_path:
            self.preview_label.config(image="", text="← 選取圖片以預覽")
            self._preview_photo = None
            return
        w = self.preview_label.winfo_width()
        h = self.preview_label.winfo_height()
        if w < 50 or h < 50:
            return
        try:
            img = Image.open(self.current_image_path)
            img.thumbnail((w, h), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self._preview_photo, text="")
        except Exception as e:
            self.preview_label.config(image="", text=f"無法讀取圖片：{e}")

    # ── 輸出 ──────────────────────────────────────────────────────────────────

    def _choose_output(self):
        path = filedialog.askdirectory(title="選擇輸出資料夾")
        if path:
            self.output_var.set(path)

    def generate_all(self):
        self._save_current()

        if not self.products:
            messagebox.showwarning("提示", "請先新增商品")
            return

        total_images = sum(len(p["images"]) for p in self.products)
        if total_images == 0:
            messagebox.showwarning("提示", "請先為商品新增圖片")
            return

        output_dir = self.output_var.get().strip()
        if not output_dir:
            messagebox.showwarning("提示", "請選擇輸出資料夾")
            return

        os.makedirs(output_dir, exist_ok=True)

        success, skipped, errors = 0, 0, []

        for p in self.products:
            if not p.get("name") and not p.get("final_price"):
                skipped += len(p["images"])
                continue
            for img_path in p["images"]:
                base = os.path.splitext(os.path.basename(img_path))[0]
                out_path = os.path.join(output_dir, f"{base}_output.jpg")
                try:
                    overlay_image(img_path, p, out_path)
                    success += 1
                except Exception as e:
                    errors.append(f"{os.path.basename(img_path)}: {e}")

        msg = f"完成！成功產生 {success} 張圖片。\n輸出位置：{output_dir}"
        if skipped:
            msg += f"\n（{skipped} 張未填寫資料，已略過）"
        if errors:
            msg += "\n\n錯誤：\n" + "\n".join(errors)

        messagebox.showinfo("完成", msg)

        # 自動開啟輸出資料夾
        try:
            if os.name == "posix":
                subprocess.run(["open", output_dir])
            else:
                subprocess.run(["explorer", output_dir])
        except Exception:
            pass


# ─── 主程式 ──────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = JewelryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
