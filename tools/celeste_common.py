#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三个提取脚本共用的 Celeste 数据读取逻辑。

包含：
  * DEMO 场景配置（哪些对话条目拼成一个场景）
  * 语言 .export 读取（与 Language.FromExport 一致）
  * Portraits.xml 解析（含 <Anim>/<Loop> 的 frames / delay / goto）
  * 对话文本中的 {portrait ...} 用法收集
  * 输出 <script> 可直接加载的 JS 全局变量

这里只依赖标准库。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

DEFAULT_GAME_DIR = r"E:\Programs\Steam\steamapps\common\Celeste"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "assets" / "celeste"

ENTRY_ID = "CH0_GRANNY"
EXPORT_FILE = "Simplified Chinese.txt.export"
LANGUAGE_FILE = "Simplified Chinese.txt"

# 每个场景 = 一个标题 + 若干对话条目（按顺序用 {break} 连接）
SCENES: List[dict] = [
    {
        "id": "ch0_granny",
        "title": "序章 · 奶奶",
        "subtitle": "CH0_GRANNY",
        "entries": ["CH0_GRANNY"],
    },
    {
        "id": "ch1_theo",
        "title": "第一章 · Theo",
        "subtitle": "CH1_THEO_A + CH1_THEO_B",
        "entries": ["CH1_THEO_A", "CH1_THEO_B"],
    },
    {
        "id": "ch2_phone",
        "title": "第二章 · 梦里电话",
        "subtitle": "CH2_DREAM_PHONECALL",
        "entries": ["CH2_DREAM_PHONECALL"],
    },
    {
        "id": "ch3_oshiro",
        "title": "第三章 · Oshiro",
        "subtitle": "CH3_OSHIRO_SUITE",
        "entries": ["CH3_OSHIRO_SUITE"],
    },
]


# ---------------------------------------------------------------------------
# 语言 .export
# ---------------------------------------------------------------------------

def read_dotnet_string(fp) -> str:
    value = 0
    shift = 0
    while True:
        raw = fp.read(1)
        if not raw:
            raise EOFError("读取字符串长度时文件提前结束")
        b = raw[0]
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    data = fp.read(value)
    if len(data) != value:
        raise EOFError("读取字符串内容时文件提前结束")
    return data.decode("utf-8", errors="replace")


def read_language_export(path: Path) -> Tuple[dict, Dict[str, str]]:
    with open(path, "rb") as fp:
        meta = {
            "id": read_dotnet_string(fp),
            "label": read_dotnet_string(fp),
            "icon": read_dotnet_string(fp),
            "order": struct.unpack("<i", fp.read(4))[0],
            "fontFace": read_dotnet_string(fp),
            "fontSize": struct.unpack("<f", fp.read(4))[0],
            "splitRegex": read_dotnet_string(fp),
            "commas": read_dotnet_string(fp),
            "periods": read_dotnet_string(fp),
        }
        lines, words, count = struct.unpack("<3i", fp.read(12))
        meta["lines"] = lines
        meta["words"] = words

        entries: Dict[str, str] = {}
        for _ in range(count):
            key = read_dotnet_string(fp)
            value = read_dotnet_string(fp)
            read_dotnet_string(fp)  # Cleaned
            entries[key.upper()] = value
    return meta, entries


# ---------------------------------------------------------------------------
# Portraits.xml
# ---------------------------------------------------------------------------

def parse_frames(text: str) -> List[int]:
    """对应 Calc.ReadCSVIntWithTricks：支持 0-1 / 2*3 / 4 三种写法。"""
    frames: List[int] = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and "*" not in part:
            a, b = part.split("-", 1)
            for i in range(int(a), int(b) + 1):
                frames.append(i)
        elif "*" in part:
            a, b = part.split("*", 1)
            for _ in range(int(b)):
                frames.append(int(a))
        else:
            frames.append(int(part))
    return frames


def parse_goto(text: str) -> List[list]:
    """对应 Chooser<string>.FromString：'id:4,id2' -> [[id,4],[id2,1]]"""
    out: List[list] = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, _, weight = part.rpartition(":")
            try:
                value = float(weight)
            except ValueError:
                name, value = part, 1.0
        else:
            name, value = part, 1.0
        out.append([name, value])
    return out


def parse_animations(element: ET.Element) -> Dict[str, dict]:
    animations: Dict[str, dict] = {}
    for tag, is_loop in (("Anim", False), ("Loop", True)):
        for node in element.findall(tag):
            anim_id = node.get("id")
            if not anim_id:
                continue
            animations[anim_id.lower()] = {
                "id": anim_id,
                "path": node.get("path", ""),
                "delay": float(node.get("delay", "0") or 0),
                "frames": parse_frames(node.get("frames", "")),
                "loop": is_loop,
                "goto": [[anim_id, 1.0]] if is_loop else parse_goto(node.get("goto", "")),
            }
    return animations


def parse_portraits(xml_path: Path) -> Dict[str, dict]:
    root = ET.parse(xml_path).getroot()
    out: Dict[str, dict] = {}
    for el in root:
        tag = el.tag
        if not tag.startswith("portrait_"):
            continue
        name = tag[len("portrait_"):].lower()
        sfx = el.get("sfx")
        if not sfx:
            continue  # copy="..." 的变体没有独立定义

        expressions: Dict[str, int] = {}
        sfxs_el = el.find("sfxs")
        if sfxs_el is not None:
            for item in sfxs_el:
                try:
                    expressions[item.tag.lower()] = int(item.get("index", "1"))
                except ValueError:
                    expressions[item.tag.lower()] = 1

        out[name] = {
            "sprite": tag,
            "sfx": sfx,
            "event": f"event:/char/dialogue/{sfx}",
            "textbox": el.get("textbox", "default"),
            "size": int(el.get("size", "160")),
            "phonestatic": el.get("phonestatic", ""),
            "glitchy": (el.get("glitchy", "").lower() == "true"),
            "expressions": expressions,
            "defaultExpression": 1,
            "animations": parse_animations(el),
            "center": el.find("Center") is not None,
        }
    return out


# ---------------------------------------------------------------------------
# 对话文本里的 {portrait ...}
# ---------------------------------------------------------------------------

import re

PORTRAIT_CMD = re.compile(r"\{portrait\s+([^}]*)\}", re.IGNORECASE)
COMMAND = re.compile(r"\{.*?\}")


def collect_portrait_usage(text: str) -> List[dict]:
    uses: List[dict] = []
    for match in PORTRAIT_CMD.finditer(text):
        tokens = [t for t in re.split(r"\s+", match.group(1).strip()) if t]
        if not tokens:
            continue
        if len(tokens) == 1 and tokens[0].lower() == "none":
            continue
        sprite = None
        animation = None
        side = 0
        for token in tokens:
            low = token.lower()
            if low in ("upsidedown", "flip", "pop"):
                continue
            if low == "left":
                side = -1
                continue
            if low == "right":
                side = 1
                continue
            if sprite is None:
                sprite = low
            elif animation is None:
                animation = low
        uses.append({
            "sprite": sprite,
            "animation": animation or "normal",
            "side": side,
            "raw": match.group(0),
        })
    return uses


def resolve_usage(uses: List[dict], portraits: Dict[str, dict]) -> List[dict]:
    resolved = []
    for use in uses:
        info = portraits.get(use["sprite"] or "")
        if not info:
            resolved.append(use)
            continue
        animation = use["animation"].lower()
        expression = info["expressions"].get(animation, info["defaultExpression"])
        resolved.append({**use, "event": info["event"], "expression": expression,
                         "textbox": info["textbox"]})
    return resolved


def strip_commands(text: str) -> str:
    return COMMAND.sub("", text)


# ---------------------------------------------------------------------------
# 场景文本 / 统计
# ---------------------------------------------------------------------------

def build_scene_text(entries: Dict[str, str], ids: List[str]) -> str:
    parts = []
    for entry_id in ids:
        value = entries.get(entry_id.upper())
        if value is None:
            raise KeyError(f"语言文件中找不到对话条目 {entry_id}")
        parts.append(value)
    return "{break}".join(parts)


def collect_scene_portraits(scenes: List[dict], portraits: Dict[str, dict]) -> Dict[str, List[str]]:
    """返回 scene_id -> 需要的肖像名列表"""
    result: Dict[str, List[str]] = {}
    for scene in scenes:
        names = set()
        for use in collect_portrait_usage(scene["text"]):
            if use["sprite"] and use["sprite"] in portraits:
                names.add(use["sprite"])
        result[scene["id"]] = sorted(names)
    return result


def animation_closure(portrait: dict, animation_names: List[str]) -> Dict[str, dict]:
    """
    从一个场景用到的表情（normal / sad ...）出发，收集
    idle_x / talk_x / begin_x 以及所有 goto 目标的动画定义。
    """
    animations = portrait.get("animations", {})
    queue: List[str] = []
    for name in animation_names:
        low = name.lower()
        queue.extend([f"idle_{low}", f"talk_{low}", f"begin_{low}"])
    seen = set()
    out: Dict[str, dict] = {}
    while queue:
        anim_id = queue.pop()
        key = anim_id.lower()
        if key in seen:
            continue
        seen.add(key)
        anim = animations.get(key)
        if not anim:
            continue
        out[key] = anim
        for target, _weight in anim.get("goto", []):
            queue.append(target)
    return out


def frame_key(path: str, index: int) -> str:
    return f"{path}{index:02d}"


# ---------------------------------------------------------------------------
# 输出 JS 全局
# ---------------------------------------------------------------------------

def write_js_global(path: Path, key: str, obj) -> None:
    """输出成 <script> 可直接加载的全局变量，避免 file:// 下 fetch 被 CORS 拦截。"""
    payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    path.write_text(
        "window.CelesteDemo = window.CelesteDemo || {};\n"
        "window.CelesteDemo.assets = window.CelesteDemo.assets || {};\n"
        f"window.CelesteDemo.assets.{key} = {payload};\n",
        encoding="utf-8")
