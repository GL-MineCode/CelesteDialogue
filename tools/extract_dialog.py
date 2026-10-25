#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从《Celeste》提取 DEMO 所需的对话文本与角色语音映射（支持多场景）。

为什么读 .export 而不是 .txt：
  游戏优先加载 "<语言>.txt.export"（Language.FromExport）。.export 是游戏自己
  解析 .txt 后的最终结果——已经完成 [MADELINE left normal] -> {portrait ...}
  的转换与 {+MOUNTAIN} 之类的嵌套变量展开，因此直接用它可以做到逐字一致。

输出（默认 assets/celeste/）：
  dialog/scenes.json / scenes.js     —— 所有场景（index.html 实际加载的文件）
  dialog/<scene_id>.json             —— 每个场景单独一份，便于调试
  portraits.json                     —— Portraits.xml 完整解析结果（含动画）
  dialog/voice_jobs.json             —— render_audio.py 需要的语音清单

.export 是 .NET BinaryWriter 格式：
  string Id, Label, IconPath
  int32  Order
  string FontFace
  float32 FontFaceSize
  string SplitRegex, CommaCharacters, PeriodCharacters
  int32  Lines, Words, Count
  Count 组：string Key, string Value, string Cleaned
其中 string = 7bit 变长长度 + UTF-8。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from celeste_common import (  # noqa: E402
    DEFAULT_GAME_DIR, DEFAULT_OUT_DIR, EXPORT_FILE, LANGUAGE_FILE,
    SCENES, build_scene_text, collect_portrait_usage, parse_portraits,
    read_language_export, resolve_usage, strip_commands, write_js_global,
)

# 肖像属性里 phonestatic="ex" -> 这个循环音效
PHONESTATIC_EVENTS = {
    "ex": "event:/char/dialogue/sfx_support/phone_static_ex",
    "mom": "event:/char/dialogue/sfx_support/phone_static_mom",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="提取 Celeste 对话与肖像语音映射")
    ap.add_argument("--game-dir", default=os.environ.get("CELESTE_DIR", DEFAULT_GAME_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()

    game = Path(args.game_dir)
    content = game / "Content"
    out = Path(args.out_dir)
    dialog_dir = content / "Dialog"

    export_path = dialog_dir / EXPORT_FILE
    txt_path = dialog_dir / LANGUAGE_FILE
    portraits_xml = content / "Graphics" / "Portraits.xml"

    if not export_path.is_file():
        if not txt_path.is_file():
            print(f"[错误] 找不到语言文件：{export_path} / {txt_path}", file=sys.stderr)
            return 2
        print(f"[错误] 缺少 {export_path.name}，请确认游戏版本；", file=sys.stderr)
        print("       （本脚本依赖 .export 以保证与游戏逐字一致）", file=sys.stderr)
        return 2

    meta, entries = read_language_export(export_path)

    if not portraits_xml.is_file():
        print(f"[错误] 找不到 {portraits_xml}", file=sys.stderr)
        return 2
    portraits = parse_portraits(portraits_xml)

    # ---- 组装场景 ----
    scenes = []
    all_uses = []
    for scene in SCENES:
        text = build_scene_text(entries, scene["entries"])
        uses = resolve_usage(collect_portrait_usage(text), portraits)
        all_uses.extend(uses)
        missing = sorted({u["sprite"] for u in uses
                          if u["sprite"] and u["sprite"] not in portraits})
        if missing:
            print(f"[警告] 场景 {scene['id']} 引用了未知肖像：{missing}")
        scenes.append({
            "id": scene["id"],
            "title": scene["title"],
            "subtitle": scene["subtitle"],
            "text": text,
            "portraitUsage": uses,
        })

    out.mkdir(parents=True, exist_ok=True)
    dialog_out = out / "dialog"
    dialog_out.mkdir(parents=True, exist_ok=True)

    # 完整解析结果（含所有角色的全部动画），仅用于调试；
    # 前端加载的是 extract_textures.py 输出的精简版 portraits.js
    (out / "portraits_full.json").write_text(
        json.dumps(portraits, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {"language": meta, "scenes": scenes}
    (dialog_out / "scenes.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_js_global(dialog_out / "scenes.js", "dialogScenes", payload)

    for scene in scenes:
        entries_of_scene = next(s["entries"] for s in SCENES if s["id"] == scene["id"])
        single = {
            "entry": "+".join(entries_of_scene),
            "text": scene["text"],
            "language": meta,
            "portraitUsage": scene["portraitUsage"],
        }
        (dialog_out / f"{scene['id']}.json").write_text(
            json.dumps(single, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 校验：字符覆盖 ----
    font_json = out / "fonts" / "chinese.json"
    if font_json.is_file():
        font = json.loads(font_json.read_text(encoding="utf-8"))
        known = {int(k) for k in font["chars"].keys()}
        visible = "".join(strip_commands(s["text"]).replace("\\#", "#") for s in scenes)
        used_chars = {ord(c) for c in visible if c not in "\r\n"}
        missing_chars = sorted(cp for cp in used_chars if cp not in known)
        if missing_chars:
            print("[警告] 以下字符不在字体中："
                  + " ".join(f"{cp:04X}({chr(cp)})" for cp in missing_chars))
    else:
        print(f"[警告] 未找到 {font_json}，跳过字库覆盖检查（先运行 extract_textures.py）")

    for scene in scenes:
        uses = scene["portraitUsage"]
        sprites = sorted({u["sprite"] for u in uses if u["sprite"]})
        pages = scene["text"].count("{break}") + 1
        print(f"[场景] {scene['id']:<12} {scene['title']}  "
              f"{len(scene['text'])} 字符 / {pages} 页 / 立绘 {sprites}")

    # ---- 语音渲染清单 ----
    combos = sorted({(u["event"], u["expression"]) for u in all_uses if "event" in u})
    used_sprites = {u["sprite"] for u in all_uses if u["sprite"]}
    phonestatics = sorted({PHONESTATIC_EVENTS[p["phonestatic"]]
                           for name, p in portraits.items()
                           if p.get("phonestatic") in PHONESTATIC_EVENTS
                           and name in used_sprites})
    jobs = {
        "voices": [{"event": e, "expression": x} for e, x in combos],
        "loops": [{"event": e, "name": e.rsplit("/", 1)[-1]} for e in phonestatics],
    }
    (dialog_out / "voice_jobs.json").write_text(
        json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[语音] {len(combos)} 个角色表情，{len(phonestatics)} 个电话杂音循环")
    print(f"[完成] {dialog_out / 'scenes.js'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
