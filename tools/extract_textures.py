#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从《Celeste》游戏目录提取本 DEMO 需要的纹理与字体数据。

输出（默认 <repo>/assets/celeste/）：
  fonts/chinese.json          由 Content/Dialog/Fonts/chinese.fnt 解析出的 BMFont 数据
  fonts/chinese_0.png         字体页（原样复制）
  ui/textbox_<name>.png       文本框皮肤（madeline / granny / theo / oshiro / badeline / default）
  ui/textbox_<name>_overlay.png 文本框叠加层（oshiro 的面具，存在时才导出）
  ui/textboxbutton.png        从 Gui 图集裁出的继续按钮
  portraits/<sprite>/<frame>.png   立绘帧（只导出场景实际用到的动画）
  portraits.json / portraits.js    立绘定义（动画表 / 帧文件 / 原点）
  manifest.json               资源清单（含 frame/offset 信息）

Celeste 的 .data 纹理格式（由 TeWu/CelesteExtractor 的 Java 实现确认）：
  little-endian u32 width
  little-endian u32 height
  u8 alphaFlag（0 = RGB，非 0 = RGBA）
  之后是 RLE： [runLength u8] [B, G, R, (A)]  重复 runLength 次

Celeste 的 .meta 图集格式（Monocle Atlas.AtlasDataFormat.CrunchBinaryNoAtlas）：
  int32  version
  string 源信息（BinaryWriter 的 7bit 长度前缀 + UTF-8）
  int32  时间戳
  int16  图集数量
  每个图集：
    string 数据文件名（不含 .data）
    int16  条目数
    每个条目：
      string 名称
      int16 x, y, w, h, offsetX, offsetY, frameWidth, frameHeight
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))

from celeste_common import (  # noqa: E402
    DEFAULT_GAME_DIR, DEFAULT_OUT_DIR, EXPORT_FILE, SCENES,
    animation_closure, build_scene_text, collect_portrait_usage,
    parse_portraits, read_dotnet_string, read_language_export, write_js_global,
)


# ---------------------------------------------------------------------------
# .data 解码 / PNG 编码
# ---------------------------------------------------------------------------

def decode_celeste_data(path: Path) -> Tuple[int, int, bytearray]:
    """把 Celeste 的 .data 纹理解码为 RGBA 字节串。"""
    with open(path, "rb") as fp:
        head = fp.read(9)
        if len(head) < 9:
            raise ValueError(f"{path} 太小，不是合法的 .data 纹理")
        width, height = struct.unpack("<II", head[:8])
        alpha_flag = head[8]
        if width <= 0 or height <= 0 or width > 16384 or height > 16384:
            raise ValueError(f"{path} 尺寸异常：{width}x{height}")

        bpp = 4 if alpha_flag else 3
        data = fp.read()

    total = width * height
    out = bytearray(total * 4)

    pos = 0
    index = 0
    length = len(data)
    while pos < length and index < total:
        run = data[pos]
        pos += 1
        if bpp == 4:
            # 关键：alpha 为 0 时只写 1 个字节（透明 run 优化），否则才是 A,B,G,R。
            if pos >= length:
                break
            a = data[pos]
            pos += 1
            if a == 0:
                pixel = b"\x00\x00\x00\x00"
            else:
                if pos + 3 > length:
                    break
                b, g, r = data[pos:pos + 3]
                pos += 3
                pixel = bytes((r, g, b, a))
        else:
            if pos + 3 > length:
                break
            b, g, r = data[pos:pos + 3]
            pos += 3
            pixel = bytes((r, g, b, 255))

        if run <= 0:          # 理论上不会出现；避免死循环
            continue
        end = min(index + run, total)
        out[index * 4:end * 4] = pixel * (end - index)
        index = end

    return width, height, out


def data_size(path: Path) -> Tuple[int, int]:
    with open(path, "rb") as fp:
        raw = fp.read(8)
    return struct.unpack("<II", raw)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    """写 8bit RGBA PNG（不依赖 Pillow）。"""
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        raw += rgba[y * stride:(y + 1) * stride]

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def crop_rgba(rgba: bytes, src_w: int, src_h: int,
              x: int, y: int, w: int, h: int) -> bytearray:
    if x < 0 or y < 0 or x + w > src_w or y + h > src_h:
        raise ValueError(f"裁切区域越界：({x},{y},{w},{h}) 于 {src_w}x{src_h}")
    out = bytearray(w * h * 4)
    for row in range(h):
        src = ((y + row) * src_w + x) * 4
        dst = row * w * 4
        out[dst:dst + w * 4] = rgba[src:src + w * 4]
    return out


# ---------------------------------------------------------------------------
# .meta 图集
# ---------------------------------------------------------------------------

def read_celeste_meta(path: Path) -> Dict[str, dict]:
    """解析 CrunchBinaryNoAtlas 的 .meta，返回 名称 -> 区域信息。"""
    entries: Dict[str, dict] = {}
    with open(path, "rb") as fp:
        fp.read(4)                    # version
        read_dotnet_string(fp)        # 源信息
        fp.read(4)                    # 时间戳
        group_count = struct.unpack("<h", fp.read(2))[0]
        for _ in range(group_count):
            data_name = read_dotnet_string(fp)
            count = struct.unpack("<h", fp.read(2))[0]
            for _ in range(count):
                name = read_dotnet_string(fp).replace("\\", "/")
                x, y, w, h, ox, oy, fw, fh = struct.unpack("<8h", fp.read(16))
                entries[name.lower()] = {
                    "data": data_name,
                    "x": x, "y": y, "w": w, "h": h,
                    "ox": ox, "oy": oy, "fw": fw, "fh": fh,
                }
    return entries


# ---------------------------------------------------------------------------
# BMFont (.fnt)
# ---------------------------------------------------------------------------

def parse_fnt(fnt_path: Path, texture_name: str) -> dict:
    root = ET.parse(fnt_path).getroot()
    info = root.find("info")
    common = root.find("common")

    chars: Dict[str, list] = {}
    chars_el = root.find("chars")
    if chars_el is not None:
        for ch in chars_el.findall("char"):
            chars[ch.get("id")] = [
                int(ch.get("x")), int(ch.get("y")),
                int(ch.get("width")), int(ch.get("height")),
                int(ch.get("xoffset", "0")), int(ch.get("yoffset", "0")),
                int(ch.get("xadvance")),
            ]

    kernings = []
    kern_el = root.find("kernings")
    if kern_el is not None:
        for k in kern_el.findall("kerning"):
            kernings.append([int(k.get("first")), int(k.get("second")), int(k.get("amount"))])

    return {
        "face": info.get("face") if info is not None else "",
        "size": float(info.get("size", "64")) if info is not None else 64,
        "lineHeight": int(common.get("lineHeight")),
        "base": int(common.get("base")),
        "scaleW": int(common.get("scaleW")),
        "scaleH": int(common.get("scaleH")),
        "texture": texture_name,
        "chars": chars,
        "kernings": kernings,
    }


# ---------------------------------------------------------------------------
# 立绘帧
# ---------------------------------------------------------------------------

def find_frame_file(folder: Path, prefix: str, index: int) -> Optional[Path]:
    """对应 Atlas.GetAtlasSubtextureFromAtlasAt：优先无填充，其次左补 0（最多 6 位）。"""
    for pad in (0, 2, 3, 1, 4, 5, 6):
        name = f"{prefix}{index}" if pad == 0 else f"{prefix}{index:0{pad}d}"
        candidate = folder / f"{name}.data"
        if candidate.is_file():
            return candidate
    return None


def build_portrait_asset(name: str, info: dict, anim_names: List[str],
                         portraits_root: Path, dst_root: Path) -> Optional[dict]:
    base_dir = portraits_root / info.get("_folder", name)
    closure = animation_closure(info, anim_names) or info["animations"]
    if not closure:
        print(f"[警告] {name} 没有任何动画，跳过")
        return None

    animations: Dict[str, dict] = {}
    frame_files: Dict[str, str] = {}
    first_frame_src: Optional[Path] = None
    missing = 0
    for anim_id, anim in closure.items():
        folder = base_dir
        prefix = anim["path"]
        frames = []
        for index in anim["frames"]:
            key = f"{prefix}/{index}"
            if key not in frame_files:
                src = find_frame_file(folder, prefix, index)
                if src is None:
                    missing += 1
                    continue
                fname = src.stem + ".png"
                dst = dst_root / fname
                w, h, rgba = decode_celeste_data(src)
                write_png(dst, w, h, rgba)
                frame_files[key] = fname
                if first_frame_src is None:
                    first_frame_src = src
            frames.append(index)
        if not frames:
            continue
        animations[anim_id] = {
            "path": prefix,
            "delay": anim["delay"],
            "loop": anim["loop"],
            "goto": anim["goto"],
            "frames": frames,
        }
    if missing:
        print(f"[警告] {name}: {missing} 个帧文件缺失")
    if not frame_files or first_frame_src is None:
        print(f"[警告] {name}: 没有可用的帧文件，跳过")
        return None

    # 精灵尺寸：Monocle Sprite.GetFrames 用「每个动画首帧」的最大宽高
    sprite_w = sprite_h = 0
    for anim in info["animations"].values():
        src = find_frame_file(base_dir, anim["path"], anim["frames"][0]) \
            if anim["frames"] else None
        if src is None:
            continue
        w, h = data_size(src)
        sprite_w = max(sprite_w, w)
        sprite_h = max(sprite_h, h)
    if not sprite_w:
        sprite_w, sprite_h = data_size(first_frame_src)

    origin = [sprite_w // 2, sprite_h // 2] if info.get("center", True) else [0, 0]
    return {
        "sprite": info["sprite"],
        "sfx": info["sfx"],
        "event": info["event"],
        "textbox": info["textbox"],
        "size": info["size"],
        "phonestatic": info.get("phonestatic", ""),
        "glitchy": info.get("glitchy", False),
        "expressions": info["expressions"],
        "spriteSize": [sprite_w, sprite_h],
        "origin": origin,
        "folder": info.get("_folder", name),
        "animations": animations,
        "frameFiles": frame_files,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="提取 Celeste 纹理 / 字体 / 立绘")
    ap.add_argument("--game-dir", default=os.environ.get("CELESTE_DIR", DEFAULT_GAME_DIR),
                    help="Celeste 安装目录（或设置环境变量 CELESTE_DIR）")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    game = Path(args.game_dir)
    out = Path(args.out_dir)
    content = game / "Content"

    if not content.is_dir():
        print(f"[错误] 找不到游戏内容目录：{content}", file=sys.stderr)
        print("       请用 --game-dir 指定 Celeste 安装目录，或设置 CELESTE_DIR。", file=sys.stderr)
        return 2

    manifest: Dict[str, dict] = {"gameDir": str(game), "files": {}}
    out.mkdir(parents=True, exist_ok=True)

    # 1) 字体：fnt -> json，页面 png 原样复制
    fonts_src = content / "Dialog" / "Fonts"
    fnt_path = fonts_src / "chinese.fnt"
    page_src = fonts_src / "chinese_0.png"
    if not fnt_path.is_file() or not page_src.is_file():
        print(f"[错误] 缺少字体文件：{fnt_path} / {page_src}", file=sys.stderr)
        return 2

    font_out = out / "fonts"
    font_out.mkdir(parents=True, exist_ok=True)
    (font_out / "chinese_0.png").write_bytes(page_src.read_bytes())

    fnt = parse_fnt(fnt_path, "chinese_0.png")
    (font_out / "chinese.json").write_text(
        json.dumps(fnt, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_js_global(font_out / "chinese.js", "font", fnt)
    manifest["files"]["font"] = {
        "json": "fonts/chinese.json",
        "texture": "fonts/chinese_0.png",
        "chars": len(fnt["chars"]),
        "page": [fnt["scaleW"], fnt["scaleH"]],
    }
    print(f"[字体] {fnt['face']} 字符数={len(fnt['chars'])} 页={fnt['scaleW']}x{fnt['scaleH']}")

    # 2) 解析对话，得到「哪些立绘 / 哪些表情 / 哪些文本框皮肤」需要导出
    portraits_root = content / "Graphics" / "Atlases" / "Portraits"
    portraits_xml = content / "Graphics" / "Portraits.xml"
    portraits: Dict[str, dict] = {}
    used_portraits: Dict[str, set] = {}
    used_textboxes = set()

    export_path = content / "Dialog" / EXPORT_FILE
    if export_path.is_file() and portraits_xml.is_file():
        _, entries = read_language_export(export_path)
        portraits = parse_portraits(portraits_xml)
        for scene in SCENES:
            text = build_scene_text(entries, scene["entries"])
            for use in collect_portrait_usage(text):
                name = use["sprite"]
                info = portraits.get(name or "")
                if not info:
                    continue
                used_portraits.setdefault(name, set()).add(use["animation"].lower())
                used_textboxes.add(info["textbox"])
        # 记录每张立绘的实际目录（Portraits.xml 的 path 属性）
        root = ET.parse(portraits_xml).getroot()
        for el in root:
            if not el.tag.startswith("portrait_"):
                continue
            name = el.tag[len("portrait_"):].lower()
            if name in portraits:
                folder = (el.get("path", "") or f"{name}/").strip("/")
                portraits[name]["_folder"] = folder
    else:
        print("[警告] 找不到 .export 或 Portraits.xml，跳过立绘 / 文本框皮肤导出")

    # 3) 文本框皮肤（Portraits/textbox/*.data）
    #    Portraits 图集是 CrunchBinaryNoAtlas：每个条目指向一张独立 .data，
    #    .meta 里只提供 frameWidth/frameHeight 与绘制偏移（用于居中与超出发光边）。
    ui_out = out / "ui"
    ui_out.mkdir(parents=True, exist_ok=True)
    textbox_dir = portraits_root / "textbox"
    portraits_meta = content / "Graphics" / "Atlases" / "Portraits.meta"
    portrait_entries: Dict[str, dict] = {}
    if portraits_meta.is_file():
        try:
            portrait_entries = read_celeste_meta(portraits_meta)
        except Exception as exc:  # noqa: BLE001
            print(f"[警告] 解析 Portraits.meta 失败：{exc}")

    textbox_names = ["default"]
    for name in sorted(used_textboxes | {"default", "madeline"}):
        if name not in textbox_names:
            textbox_names.append(name)

    for name in textbox_names:
        targets = [name]
        if (textbox_dir / f"{name}_overlay.data").is_file():
            targets.append(f"{name}_overlay")
        for target in targets:
            src = textbox_dir / f"{target}.data"
            if not src.is_file():
                print(f"[警告] 缺少文本框纹理：{src}")
                continue
            w, h, rgba = decode_celeste_data(src)
            dst = ui_out / f"textbox_{target}.png"
            write_png(dst, w, h, rgba)

            meta = portrait_entries.get(f"textbox/{target}".lower())
            if meta:
                frame = [meta["fw"], meta["fh"]]
                offset = [-meta["ox"], -meta["oy"]]
            else:
                frame = [w, h]
                offset = [0, 0]
                print(f"[警告] Portraits.meta 缺少 textbox/{target}，按整图处理")

            manifest["files"][f"textbox_{target}"] = {
                "path": f"ui/textbox_{target}.png",
                "size": [w, h],
                "frame": frame,
                "offset": offset,
            }
            print(f"[文本框] {target}: image={w}x{h} frame={frame[0]}x{frame[1]} offset={offset}")

    # 4) Gui 图集里的 textboxbutton
    atlas_dir = content / "Graphics" / "Atlases"
    gui_meta = atlas_dir / "Gui.meta"
    gui_data = atlas_dir / "Gui0.data"
    if gui_meta.is_file() and gui_data.is_file():
        try:
            entries = read_celeste_meta(gui_meta)
            entry = entries.get("textboxbutton")
            if entry is None:
                print("[警告] Gui.meta 中找不到 textboxbutton 条目")
            else:
                src_w, src_h, rgba = decode_celeste_data(gui_data)
                if entry["data"].lower() != "gui0":
                    print(f"[警告] textboxbutton 位于 {entry['data']}，本脚本只解码 Gui0")
                else:
                    crop = crop_rgba(rgba, src_w, src_h,
                                     entry["x"], entry["y"], entry["w"], entry["h"])
                    dst = ui_out / "textboxbutton.png"
                    write_png(dst, entry["w"], entry["h"], crop)
                    manifest["files"]["textboxbutton"] = {
                        "path": "ui/textboxbutton.png",
                        "size": [entry["w"], entry["h"]],
                        "frame": [entry["fw"], entry["fh"]],
                        "offset": [-entry["ox"], -entry["oy"]],
                        "atlas": [src_w, src_h],
                    }
                    print(f"[按钮] textboxbutton: rect=({entry['x']},{entry['y']},"
                          f"{entry['w']}x{entry['h']}) frame={entry['fw']}x{entry['fh']}")
        except Exception as exc:  # noqa: BLE001 - 提取失败不应中断整个流程
            print(f"[警告] 解析 Gui 图集失败：{exc}")
    else:
        print("[警告] 缺少 Gui.meta / Gui0.data，跳过 textboxbutton")

    # 5) 立绘帧
    portrait_assets: Dict[str, dict] = {}
    portrait_root_out = out / "portraits"
    total_frames = 0
    for name, anims in sorted(used_portraits.items()):
        info = portraits[name]
        asset = build_portrait_asset(name, info, sorted(anims), portraits_root,
                                     portrait_root_out / info.get("_folder", name))
        if asset is None:
            continue
        portrait_assets[name] = asset
        total_frames += len(asset["frameFiles"])
        print(f"[立绘] {name}: 动画 {len(asset['animations'])} 个 / 帧 {len(asset['frameFiles'])} 张 "
              f"/ sprite={asset['spriteSize'][0]}x{asset['spriteSize'][1]} "
              f"/ textbox={asset['textbox']}"
              + (" / phonestatic=" + asset['phonestatic'] if asset['phonestatic'] else "")
              + (" / glitchy" if asset['glitchy'] else ""))

    # 噪点叠层（glitchy 立绘用）
    noise_dir = portraits_root / "noise"
    if noise_dir.is_dir() and any(a["glitchy"] for a in portrait_assets.values()):
        noise_frames = []
        for index in range(64):
            src = find_frame_file(noise_dir, "", index)
            if src is None:
                break
            w, h, rgba = decode_celeste_data(src)
            fname = src.stem + ".png"
            write_png(portrait_root_out / "noise" / fname, w, h, rgba)
            noise_frames.append(fname)
        if noise_frames:
            portrait_assets["_noise"] = {"frames": noise_frames, "delay": 0.1}
            total_frames += len(noise_frames)
            print(f"[噪点] {len(noise_frames)} 帧")

    (out / "portraits.json").write_text(
        json.dumps(portrait_assets, ensure_ascii=False, indent=2), encoding="utf-8")
    write_js_global(out / "portraits.js", "portraits", portrait_assets)
    manifest["files"]["portraits"] = {
        "dir": "portraits",
        "sprites": sorted(k for k in portrait_assets if not k.startswith("_")),
        "frames": total_frames,
    }

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_js_global(out / "manifest.js", "manifest", manifest)
    print(f"[完成] 输出目录：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
