"""
從 gaga_logo.png 產生各平台所需的 icon 檔案。
Windows: icon.ico（多尺寸）
macOS:   由 CI 的 sips + iconutil 處理，此腳本不負責。
"""
from PIL import Image
import os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaga_logo.png")
ICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

def build_ico():
    img = Image.open(SRC).convert("RGBA")
    sizes = [16, 32, 48, 64, 128, 256]
    imgs  = [img.resize((s, s), Image.LANCZOS) for s in sizes]
    imgs[0].save(ICO, format="ICO", append_images=imgs[1:],
                 sizes=[(s, s) for s in sizes])
    print(f"Built {ICO}")

if __name__ == "__main__":
    build_ico()
