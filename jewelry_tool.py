#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
珠寶代購圖片工具 - PoC
用法：python jewelry_tool.py
"""

import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

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

    # 字體大小依圖片寬度自動縮放
    name_sz  = max(26, int(w * 0.048))
    sub_sz   = max(19, int(w * 0.033))
    price_sz = max(30, int(w * 0.055))

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
        ("折扣 %",   "discount"),   # 例：85 代表 85折（×0.85）
        ("加成 %",   "markup"),     # 例：20 代表再加 20%（×1.20）
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("珠寶代購圖片工具")
        self.root.geometry("1050x720")
        self.root.minsize(800, 580)

        self.image_paths: list[str] = []
        self.image_data: dict[str, dict] = {}
        self.current_path: str | None = None
        self._preview_photo = None
        self._loading_form = False  # 防止 trace 迴圈

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

        # ── 左側：圖片列表 ──
        left = ttk.Frame(paned, width=210)
        paned.add(left, weight=0)

        ttk.Label(left, text="圖片列表", font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 4))

        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(lf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(lf, yscrollcommand=sb.set, activestyle="dotbox",
                                  selectmode=tk.SINGLE, font=("", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        ttk.Button(left, text="＋ 新增圖片", command=self.add_images).pack(fill=tk.X, pady=(6, 2))
        ttk.Button(left, text="✕ 移除選取", command=self.remove_selected).pack(fill=tk.X)

        # ── 右側：預覽 + 表單 ──
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        # 預覽區
        pf = ttk.LabelFrame(right, text="預覽", padding=6)
        pf.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.preview_label = ttk.Label(pf, text="← 從左側新增並選擇圖片", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        pf.bind("<Configure>", lambda e: self._refresh_preview())

        # 表單區
        form_frame = ttk.LabelFrame(right, text="商品資訊", padding=10)
        form_frame.pack(fill=tk.X)

        # 左欄：文字欄位
        col1 = ttk.Frame(form_frame)
        col1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 16))

        self.vars: dict[str, tk.StringVar] = {}
        for label, key in self.FIELDS:
            row = ttk.Frame(col1)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, width=10, anchor=tk.W).pack(side=tk.LEFT)
            v = tk.StringVar()
            v.trace_add("write", lambda *a, k=key: self._on_text_field_change(k))
            ttk.Entry(row, textvariable=v).pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.vars[key] = v

        # 右欄：定價計算
        col2 = ttk.LabelFrame(form_frame, text="定價計算", padding=8)
        col2.pack(side=tk.LEFT, fill=tk.Y)

        for label, key in self.PRICE_FIELDS:
            row = ttk.Frame(col2)
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, width=8, anchor=tk.W).pack(side=tk.LEFT)
            v = tk.StringVar()
            v.trace_add("write", lambda *a: self._calc_and_save_price())
            ttk.Entry(row, textvariable=v, width=10).pack(side=tk.LEFT)
            self.vars[key] = v

        ttk.Separator(col2, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        price_row = ttk.Frame(col2)
        price_row.pack(fill=tk.X)
        ttk.Label(price_row, text="售價", width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.price_label = ttk.Label(price_row, text="--", font=("", 15, "bold"), foreground="#c0392b")
        self.price_label.pack(side=tk.LEFT)

        ttk.Label(col2, text="公式：報價 × (折扣/100) × (1+加成/100)",
                  font=("", 8), foreground="gray").pack(anchor=tk.W, pady=(4, 0))

        # 輸出路徑列
        bot = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bot.pack(fill=tk.X)
        ttk.Label(bot, text="輸出資料夾：").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value=os.path.expanduser("~/Desktop/珠寶圖片輸出"))
        ttk.Entry(bot, textvariable=self.output_var, width=42).pack(side=tk.LEFT, padx=5)
        ttk.Button(bot, text="選擇", command=self._choose_output).pack(side=tk.LEFT)

    # ── 圖片管理 ──────────────────────────────────────────────────────────────

    def add_images(self):
        paths = filedialog.askopenfilenames(
            title="選擇商品圖片",
            filetypes=[("圖片檔", "*.jpg *.jpeg *.png *.JPG *.JPEG *.PNG"), ("所有檔案", "*.*")],
        )
        for p in paths:
            if p not in self.image_paths:
                self.image_paths.append(p)
                self.image_data[p] = {k: "" for k in ["name", "material", "description",
                                                        "cost", "discount", "markup", "final_price"]}
                self.listbox.insert(tk.END, os.path.basename(p))

        # 自動選取第一張
        if paths and self.current_path is None:
            self.listbox.selection_set(0)
            self._on_list_select(None)

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        path = self.image_paths.pop(idx)
        del self.image_data[path]
        self.listbox.delete(idx)
        self.current_path = None
        self._clear_form()

    # ── 選取圖片 ──────────────────────────────────────────────────────────────

    def _on_list_select(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        if self.current_path:
            self._save_current()
        self.current_path = self.image_paths[sel[0]]
        self._load_form(self.current_path)
        self._refresh_preview()

    # ── 表單讀寫 ──────────────────────────────────────────────────────────────

    def _on_text_field_change(self, key: str):
        if self._loading_form or not self.current_path:
            return
        self.image_data[self.current_path][key] = self.vars[key].get()

    def _calc_and_save_price(self):
        if self._loading_form or not self.current_path:
            return
        for key in ["cost", "discount", "markup"]:
            self.image_data[self.current_path][key] = self.vars[key].get()
        try:
            cost     = float(self.vars["cost"].get()     or 0)
            discount = float(self.vars["discount"].get() or 100)
            markup   = float(self.vars["markup"].get()   or 0)
            final    = cost * (discount / 100) * (1 + markup / 100)
            display  = f"$ {final:,.0f}"
            self.price_label.config(text=display)
            self.image_data[self.current_path]["final_price"] = display
        except ValueError:
            self.price_label.config(text="--")
            self.image_data[self.current_path]["final_price"] = ""

    def _save_current(self):
        if not self.current_path:
            return
        for key in ["name", "material", "description"]:
            self.image_data[self.current_path][key] = self.vars[key].get()

    def _load_form(self, path: str):
        self._loading_form = True
        data = self.image_data.get(path, {})
        for key in ["name", "material", "description", "cost", "discount", "markup"]:
            self.vars[key].set(data.get(key, ""))
        price = data.get("final_price", "")
        self.price_label.config(text=price if price else "--")
        self._loading_form = False

    def _clear_form(self):
        self._loading_form = True
        for v in self.vars.values():
            v.set("")
        self.price_label.config(text="--")
        self.preview_label.config(image="", text="← 從左側新增並選擇圖片")
        self._preview_photo = None
        self._loading_form = False

    # ── 預覽 ──────────────────────────────────────────────────────────────────

    def _refresh_preview(self):
        if not self.current_path:
            return
        w = self.preview_label.winfo_width()
        h = self.preview_label.winfo_height()
        if w < 50 or h < 50:
            return
        try:
            img = Image.open(self.current_path)
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

        if not self.image_paths:
            messagebox.showwarning("提示", "請先新增圖片")
            return

        output_dir = self.output_var.get().strip()
        if not output_dir:
            messagebox.showwarning("提示", "請選擇輸出資料夾")
            return

        os.makedirs(output_dir, exist_ok=True)

        success, skipped, errors = 0, 0, []

        for path in self.image_paths:
            data = self.image_data[path]
            if not data.get("name") and not data.get("final_price"):
                skipped += 1
                continue

            base = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(output_dir, f"{base}_output.jpg")
            try:
                overlay_image(path, data, out_path)
                success += 1
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        # 結果訊息
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
