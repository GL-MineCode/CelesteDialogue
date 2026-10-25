#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用《Celeste》自带的 FMOD Studio 运行时渲染对话语音，得到与游戏完全一致的音频。

原理：
  * 游戏语音不是「每字一个音效」，而是一个常驻循环事件
    event:/char/dialogue/<角色>，通过参数 dialogue_portrait（表情序号）
    与 dialogue_end 门控（见 Textbox.cs 的 StartTalker / StopTalker）。
  * 因此直接从 .bank 抽采样会丢事件层的处理。这里改为：
      初始化 FMOD Studio（输出到 WAVWRITER）
      -> 加载 Master Bank / strings / sfx / ui
      -> 逐个事件实例播放并设置参数
      -> 实时 Update，把所有输出录进一个 WAV
      -> 按每个任务的起止时间戳切分、去静音、按能量最低点取循环结尾
  * 只初始化一次系统，避免反复读取 164MB 的 sfx.bank。

依赖：Windows + Python 3.8+（标准库），以及游戏目录下的
      lib64-win-x64/fmod64.dll、fmodstudio.dll
"""

from __future__ import annotations

import argparse
import array
import base64
import ctypes
import faulthandler
import io
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_GAME_DIR = r"E:\Programs\Steam\steamapps\common\Celeste"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "assets" / "celeste"

FMOD_OK = 0
FMOD_OUTPUTTYPE_WAVWRITER = 3
FMOD_SPEAKERMODE_STEREO = 1
FMOD_STUDIO_STOP_IMMEDIATE = 0

UI_EVENTS = [
    ("event:/ui/game/textbox_madeline_in", "ui_textbox_madeline_in"),
    ("event:/ui/game/textbox_madeline_out", "ui_textbox_madeline_out"),
    ("event:/ui/game/textbox_other_in", "ui_textbox_other_in"),
    ("event:/ui/game/textbox_other_out", "ui_textbox_other_out"),
]

# FMOD Studio 的参数按 ParameterId 排序，而不是按名字。
# 绝大多数对话事件的顺序是 [dialogue_portrait, dialogue_end]，
# 但电话相关的 ex / mom 正好相反（用 SetParameterValueByIndex 设置时
# 会把 dialogue_end 当成表情，导致整段静音）。
SWAPPED_EVENT_PARAMS = {
    "event:/char/dialogue/ex",
    "event:/char/dialogue/mom",
}


# ---------------------------------------------------------------------------
# WAV 读写
# ---------------------------------------------------------------------------

def read_wav(path: Path) -> Tuple[int, int, array.array]:
    raw = path.read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path} 不是 RIFF/WAVE")

    pos = 12
    fmt: Optional[bytes] = None
    data: Optional[bytes] = None
    while pos + 8 <= len(raw):
        chunk_id = raw[pos:pos + 4]
        size = int.from_bytes(raw[pos + 4:pos + 8], "little")
        body = raw[pos + 8:pos + 8 + size]
        if chunk_id == b"fmt ":
            fmt = body
        elif chunk_id == b"data":
            data = body
        pos += 8 + size + (size & 1)

    if fmt is None or data is None:
        raise ValueError(f"{path} 缺少 fmt/data 块")

    tag, channels, rate, _byte_rate, _block_align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:          # WAVE_FORMAT_EXTENSIBLE
        tag = struct.unpack("<H", fmt[24:26])[0]

    if tag == 1 and bits == 16:
        samples = array.array("h")
        samples.frombytes(data[:len(data) // 2 * 2])
    elif tag == 3 and bits == 32:
        tmp = array.array("f")
        tmp.frombytes(data[:len(data) // 4 * 4])
        samples = array.array("h", (max(-32768, min(32767, int(v * 32767.0))) for v in tmp))
    elif tag == 1 and bits == 8:
        samples = array.array("h", ((b - 128) << 8 for b in data))
    elif tag == 1 and bits == 24:
        samples = array.array("h")
        for i in range(0, len(data) - 2, 3):
            v = data[i] | (data[i + 1] << 8) | (data[i + 2] << 16)
            if v & 0x800000:
                v -= 0x1000000
            samples.append(int(v / 256))
    else:
        raise ValueError(f"{path} 不支持的格式 tag={tag} bits={bits}")

    if channels <= 0:
        raise ValueError(f"{path} 声道数异常：{channels}")
    return channels, rate, samples


def write_wav(path: Path, channels: int, rate: int, samples: array.array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as fp:
        fp.setnchannels(channels)
        fp.setsampwidth(2)
        fp.setframerate(rate)
        fp.writeframes(samples.tobytes())


def to_mono(samples: array.array, channels: int) -> array.array:
    if channels == 1:
        return array.array("h", samples)
    total = len(samples) // channels
    out = array.array("h")
    for i in range(total):
        acc = 0
        base = i * channels
        for c in range(channels):
            acc += samples[base + c]
        out.append(int(acc / channels))
    return out


def wav_bytes(channels: int, rate: int, samples: array.array) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as fp:
        fp.setnchannels(channels)
        fp.setsampwidth(2)
        fp.setframerate(rate)
        fp.writeframes(samples.tobytes())
    return buffer.getvalue()


def build_audio_data_js(audio_dir: Path) -> None:
    """
    浏览器在 file:// 下会拦载 <audio src="xxx.wav">，所以额外生成一份 base64
    内联数据。语音左右声道完全相同，降为单声道是无损的。
    """
    payload = {}
    for wav_path in sorted(audio_dir.glob("*.wav")):
        if wav_path.name.startswith("_"):
            continue
        channels, rate, samples = read_wav(wav_path)
        mono = to_mono(samples, channels)
        encoded = base64.b64encode(wav_bytes(1, rate, mono)).decode("ascii")
        payload[wav_path.stem] = f"data:audio/wav;base64,{encoded}"

    target = audio_dir / "audio-data.js"
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    target.write_text(
        "window.CelesteDemo = window.CelesteDemo || {};\n"
        "window.CelesteDemo.assets = window.CelesteDemo.assets || {};\n"
        f"window.CelesteDemo.assets.audio = {body};\n",
        encoding="utf-8")
    print(f"[内联] {target.name}: {target.stat().st_size / 1024 / 1024:.2f} MB")
    return None


# ---------------------------------------------------------------------------
# 切片 / 静音裁剪
# ---------------------------------------------------------------------------

def frames_of(samples: array.array, channels: int) -> int:
    return len(samples) // channels


def slice_frames(samples: array.array, channels: int, start: int, end: int) -> array.array:
    start = max(0, start)
    end = max(start, end)
    return array.array("h", samples[start * channels:end * channels])


def peak_of(samples: array.array) -> int:
    return max((abs(v) for v in samples), default=0)


def find_active_span(samples: array.array, channels: int, threshold: int) -> Tuple[int, int]:
    """返回首个/最后一个超过阈值的帧（含），找不到返回 (-1, -1)。"""
    total = frames_of(samples, channels)
    first = -1
    last = -1
    for i in range(total):
        base = i * channels
        peak = 0
        for c in range(channels):
            v = abs(samples[base + c])
            if v > peak:
                peak = v
        if peak > threshold:
            if first < 0:
                first = i
            last = i
    return first, last


def window_rms(samples: array.array, channels: int, start_frame: int, frames: int) -> float:
    total = frames_of(samples, channels)
    end = min(total, start_frame + frames)
    if end <= start_frame:
        return 0.0
    acc = 0
    count = 0
    base = start_frame * channels
    stop = end * channels
    for i in range(base, stop):
        v = samples[i]
        acc += v * v
        count += 1
    return math.sqrt(acc / max(1, count))


def choose_loop_end(samples: array.array, channels: int, rate: int,
                    start_frame: int, target_frames: int,
                    search_frames: int) -> int:
    """在目标长度附近寻找 20ms 窗口能量最低的切点，减少循环接缝爆音。"""
    total = frames_of(samples, channels)
    win = max(64, int(rate * 0.02))
    lo = max(start_frame + int(rate * 0.25), start_frame + target_frames - search_frames)
    hi = min(total - win - 1, start_frame + target_frames + search_frames)
    if hi <= lo:
        return min(total, start_frame + target_frames)

    best_pos = lo
    best_energy = float("inf")
    step = max(1, int(rate * 0.005))
    for pos in range(lo, hi, step):
        energy = window_rms(samples, channels, pos, win)
        if energy < best_energy:
            best_energy = energy
            best_pos = pos
    return best_pos


def apply_fades(samples: array.array, channels: int, rate: int,
                fade_in_ms: float = 8.0, fade_out_ms: float = 8.0) -> array.array:
    total = frames_of(samples, channels)
    if total <= 0:
        return samples
    out = array.array("h", samples)
    n_in = min(total, max(1, int(rate * fade_in_ms / 1000.0)))
    n_out = min(total, max(1, int(rate * fade_out_ms / 1000.0)))
    for i in range(n_in):
        g = i / n_in
        for c in range(channels):
            out[i * channels + c] = int(out[i * channels + c] * g)
    for i in range(n_out):
        g = i / n_out
        idx = total - 1 - i
        for c in range(channels):
            out[idx * channels + c] = int(out[idx * channels + c] * g)
    return out


# ---------------------------------------------------------------------------
# FMOD Studio 绑定
# ---------------------------------------------------------------------------

class FmodError(RuntimeError):
    pass


class ParameterId(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint), ("data2", ctypes.c_uint)]


class Studio:
    def __init__(self, dll_dir: Path):
        if os.name != "nt":
            raise FmodError("此脚本依赖 Windows 的 fmod64.dll / fmodstudio.dll")
        # 句柄必须持有，否则目录会被立刻从 DLL 搜索路径里移除
        self._dll_dir_handle = os.add_dll_directory(str(dll_dir))
        self.core = ctypes.WinDLL(str(dll_dir / "fmod64.dll"))
        self.studio = ctypes.WinDLL(str(dll_dir / "fmodstudio.dll"))
        self._bind()

    def _bind(self) -> None:
        P = ctypes.POINTER
        V = ctypes.c_void_p
        s, c = self.studio, self.core

        s.FMOD_Studio_System_Create.argtypes = [P(V), ctypes.c_uint]
        s.FMOD_Studio_System_Create.restype = ctypes.c_int
        # FMOD Studio 1.10 叫 GetLowLevelSystem（1.11+ 才改名 GetCoreSystem）
        s.FMOD_Studio_System_GetLowLevelSystem.argtypes = [V, P(V)]
        s.FMOD_Studio_System_GetLowLevelSystem.restype = ctypes.c_int
        s.FMOD_Studio_System_Initialize.argtypes = [V, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, V]
        s.FMOD_Studio_System_Initialize.restype = ctypes.c_int
        s.FMOD_Studio_System_LoadBankFile.argtypes = [V, ctypes.c_char_p, ctypes.c_uint, P(V)]
        s.FMOD_Studio_System_LoadBankFile.restype = ctypes.c_int
        s.FMOD_Studio_System_GetEvent.argtypes = [V, ctypes.c_char_p, P(V)]
        s.FMOD_Studio_System_GetEvent.restype = ctypes.c_int
        s.FMOD_Studio_System_Update.argtypes = [V]
        s.FMOD_Studio_System_Update.restype = ctypes.c_int
        s.FMOD_Studio_System_Release.argtypes = [V]
        s.FMOD_Studio_System_Release.restype = ctypes.c_int
        s.FMOD_Studio_Bank_Unload.argtypes = [V]
        s.FMOD_Studio_Bank_Unload.restype = ctypes.c_int
        s.FMOD_Studio_EventDescription_CreateInstance.argtypes = [V, P(V)]
        s.FMOD_Studio_EventDescription_CreateInstance.restype = ctypes.c_int
        s.FMOD_Studio_EventInstance_Start.argtypes = [V]
        s.FMOD_Studio_EventInstance_Start.restype = ctypes.c_int
        s.FMOD_Studio_EventInstance_Stop.argtypes = [V, ctypes.c_int]
        s.FMOD_Studio_EventInstance_Stop.restype = ctypes.c_int
        s.FMOD_Studio_EventInstance_Release.argtypes = [V]
        s.FMOD_Studio_EventInstance_Release.restype = ctypes.c_int
        # 不用 SetParameterValue（8 字节结构体按值传参在 ctypes 下不可靠，
        # 会破坏栈并在后续调用触发 access violation），改用 ByIndex。
        s.FMOD_Studio_EventInstance_SetParameterValueByIndex.argtypes = [
            V, ctypes.c_int, ctypes.c_float, ctypes.c_int]
        s.FMOD_Studio_EventInstance_SetParameterValueByIndex.restype = ctypes.c_int

        c.FMOD_System_SetOutput.argtypes = [V, ctypes.c_int]
        c.FMOD_System_SetOutput.restype = ctypes.c_int
        c.FMOD_System_SetSoftwareFormat.argtypes = [V, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        c.FMOD_System_SetSoftwareFormat.restype = ctypes.c_int

    @staticmethod
    def version_from_dll(dll: Path) -> Optional[int]:
        try:
            text = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-Item '{dll}').VersionInfo.FileVersion"],
                text=True, timeout=20, stderr=subprocess.DEVNULL).strip()
            match = re.search(r"(\d+)[.,]\s*(\d+)[.,]\s*(\d+)", text)
            if match:
                major, minor, patch = (int(g) for g in match.groups())
                return (major << 16) | (minor << 8) | patch
        except Exception:  # noqa: BLE001
            pass
        return None

    def create_system(self, dll_dir: Path) -> Tuple[int, ctypes.c_void_p, ctypes.c_void_p]:
        candidates: List[int] = []
        detected = self.version_from_dll(dll_dir / "fmodstudio.dll")
        if detected:
            candidates.append(detected)
        # 此版本的 fmodstudio.dll 实际接受 0x00011000（FileVersion 报 1.10.14），
        # 与常规 (major<<16|minor<<8|patch) 编码不一致，因此扩大范围穷举。
        for major in (0, 1, 2, 3):
            for minor in range(0, 33):
                for patch in range(0, 41):
                    candidates.append((major << 16) | (minor << 8) | patch)
        seen = set()
        last_error = None
        for version in candidates:
            if version in seen:
                continue
            seen.add(version)
            system = ctypes.c_void_p()
            result = self.studio.FMOD_Studio_System_Create(ctypes.byref(system), version)
            if result == FMOD_OK and system.value:
                core = ctypes.c_void_p()
                if self.studio.FMOD_Studio_System_GetLowLevelSystem(
                        system, ctypes.byref(core)) != FMOD_OK:
                    self.studio.FMOD_Studio_System_Release(system)
                    continue
                print(f"[FMOD] 版本常量 0x{version:08X}")
                return version, system, core
            last_error = result
            if system.value:
                self.studio.FMOD_Studio_System_Release(system)
        raise FmodError(f"FMOD_Studio_System_Create 全部失败，最后错误码 {last_error}")


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------

def build_jobs(out_dir: Path) -> List[dict]:
    jobs: List[dict] = []
    jobs_path = out_dir / "dialog" / "voice_jobs.json"
    voices: List[dict] = []
    loops: List[dict] = []
    if jobs_path.is_file():
        data = json.loads(jobs_path.read_text(encoding="utf-8"))
        if isinstance(data, list):      # 兼容旧格式
            voices = data
        else:
            voices = data.get("voices", [])
            loops = data.get("loops", [])
    else:
        print(f"[警告] 未找到 {jobs_path}，使用默认 Madeline/Granny 组合")
        for name, exprs in (("madeline", (1, 3, 7, 8)), ("granny", (1, 2))):
            for expr in exprs:
                voices.append({"event": f"event:/char/dialogue/{name}",
                               "expression": expr})

    for item in voices:
        event = item["event"]
        expr = int(item["expression"])
        name = event.rsplit("/", 1)[-1]
        jobs.append({
            "kind": "voice",
            "event": event,
            "expression": expr,
            "out": f"vo_{name}_{expr}.wav",
            "seconds": 2.4,
            "gap": 0.7,
        })

    # 电话杂音之类的循环层：不裁成 2s 循环，整段留作 loop 播放
    for item in loops:
        event = item["event"]
        name = item.get("name") or event.rsplit("/", 1)[-1]
        jobs.append({
            "kind": "loop",
            "event": event,
            "expression": None,
            "out": f"loop_{name}.wav",
            "seconds": 5.0,
            "gap": 0.6,
        })

    for event, out in UI_EVENTS:
        jobs.append({
            "kind": "ui",
            "event": event,
            "expression": None,
            "out": f"{out}.wav",
            "seconds": 1.4,
            "gap": 0.6,
        })
    return jobs


# ---------------------------------------------------------------------------
# 录音
# ---------------------------------------------------------------------------

def render(jobs: List[dict], dll_dir: Path, banks: List[Path], raw_wav: Path,
           portrait_index: int = 0, end_index: int = 1) -> Tuple[int, int, List[dict]]:
    fmod = Studio(dll_dir)
    _version, system, core = fmod.create_system(dll_dir)
    stud, low = fmod.studio, fmod.core

    low.FMOD_System_SetOutput(core, FMOD_OUTPUTTYPE_WAVWRITER)
    low.FMOD_System_SetSoftwareFormat(core, 48000, FMOD_SPEAKERMODE_STEREO, 0)

    raw_wav.parent.mkdir(parents=True, exist_ok=True)
    if raw_wav.exists():
        raw_wav.unlink()
    # 必须用 create_string_buffer 持有内存：cast(c_char_p(...)) 的临时对象会被 GC，
    # FMOD 随后读到的是悬空指针，WAV 会悄无声息地消失。
    driver_buf = ctypes.create_string_buffer(str(raw_wav).encode("utf-8"))
    driver_data = ctypes.cast(driver_buf, ctypes.c_void_p)

    result = stud.FMOD_Studio_System_Initialize(system, 512, 0, 0, driver_data)
    if result != FMOD_OK:
        stud.FMOD_Studio_System_Release(system)
        raise FmodError(f"FMOD_Studio_System_Initialize 失败：{result}")

    loaded = []
    try:
        for bank in banks:
            handle = ctypes.c_void_p()
            result = stud.FMOD_Studio_System_LoadBankFile(
                system, str(bank).encode("utf-8"), 0, ctypes.byref(handle))
            if result != FMOD_OK:
                raise FmodError(f"加载 bank 失败（{result}）：{bank}")
            loaded.append(handle)
            print(f"[FMOD] 已加载 {bank.name}")

        t0 = time.perf_counter()

        # 对话快照（游戏在 Textbox 打开时会 ResumeSnapshot，效果是压低音乐）
        snapshot = ctypes.c_void_p()
        snapshot_instance = ctypes.c_void_p()
        snapshot_ok = False
        if stud.FMOD_Studio_System_GetEvent(system, b"snapshot:/dialogue_in_progress",
                                            ctypes.byref(snapshot)) == FMOD_OK:
            if stud.FMOD_Studio_EventDescription_CreateInstance(
                    snapshot, ctypes.byref(snapshot_instance)) == FMOD_OK:
                stud.FMOD_Studio_EventInstance_Start(snapshot_instance)
                snapshot_ok = True
                print("[FMOD] 已启动 snapshot:/dialogue_in_progress")
        if not snapshot_ok:
            print("[提示] 未能启动 dialogue_in_progress 快照，继续")

        def pump(seconds: float) -> None:
            end = time.perf_counter() + seconds
            while True:
                stud.FMOD_Studio_System_Update(system)
                remain = end - time.perf_counter()
                if remain <= 0:
                    break
                time.sleep(min(0.01, remain))

        timings: List[dict] = []
        desc_cache: Dict[str, ctypes.c_void_p] = {}
        # 开头留 0.5s 静音，便于自动对齐
        pump(0.5)

        for job in jobs:
            desc = desc_cache.get(job["event"])
            if desc is None:
                desc = ctypes.c_void_p()
                result = stud.FMOD_Studio_System_GetEvent(
                    system, job["event"].encode("utf-8"), ctypes.byref(desc))
                if result != FMOD_OK:
                    print(f"[警告] 找不到事件 {job['event']}（{result}），跳过")
                    continue
                desc_cache[job["event"]] = desc

            instance = ctypes.c_void_p()
            result = stud.FMOD_Studio_EventDescription_CreateInstance(desc, ctypes.byref(instance))
            if result != FMOD_OK:
                print(f"[警告] 无法创建实例 {job['event']}（{result}），跳过")
                continue

            p_index, e_index = (portrait_index, end_index)
            if job["event"] in SWAPPED_EVENT_PARAMS:
                p_index, e_index = e_index, p_index

            if job["kind"] == "voice":
                stud.FMOD_Studio_EventInstance_SetParameterValueByIndex(
                    instance, e_index, 0.0, 0)
                stud.FMOD_Studio_EventInstance_SetParameterValueByIndex(
                    instance, p_index, float(job["expression"]), 0)

            start_t = time.perf_counter() - t0
            stud.FMOD_Studio_EventInstance_Start(instance)
            if job["kind"] == "voice":
                pump(0.06)
                stud.FMOD_Studio_EventInstance_SetParameterValueByIndex(
                    instance, p_index, float(job["expression"]), 0)

            pump(job["seconds"])
            end_t = time.perf_counter() - t0

            stud.FMOD_Studio_EventInstance_Stop(instance, FMOD_STUDIO_STOP_IMMEDIATE)
            stud.FMOD_Studio_EventInstance_Release(instance)
            pump(job["gap"])

            timings.append({**job, "start": start_t, "end": end_t})
            print(f"[录音] {job['out']}: {job['event']} expr={job['expression']} "
                  f"{end_t - start_t:.2f}s")

        if snapshot_ok:
            stud.FMOD_Studio_EventInstance_Stop(snapshot_instance, FMOD_STUDIO_STOP_IMMEDIATE)
            stud.FMOD_Studio_EventInstance_Release(snapshot_instance)
            stud.FMOD_Studio_System_Update(system)

        pump(0.3)
    finally:
        for handle in loaded:
            stud.FMOD_Studio_Bank_Unload(handle)
        stud.FMOD_Studio_System_Release(system)

    channels, rate, samples = read_wav(raw_wav)
    print(f"[录音] 原始文件：{frames_of(samples, channels) / rate:.2f}s, "
          f"{channels}ch @ {rate}Hz")
    return channels, rate, timings


def export(jobs: List[dict], raw_wav: Path, out_dir: Path,
           channels: int, rate: int) -> None:
    samples = read_wav(raw_wav)[2]
    total_frames = frames_of(samples, channels)
    first_active, last_active = find_active_span(samples, channels, 96)
    if first_active < 0:
        raise FmodError("录音里没有任何声音，请检查 bank 与事件名")
    print(f"[切分] 首个有声帧 {first_active / rate:.2f}s，最后有声帧 {last_active / rate:.2f}s")

    # 自动对齐：假设最早的任务就是第一个发声点
    first_job_start = jobs[0]["start"]
    origin = first_active - int(first_job_start * rate)
    print(f"[切分] 时间基准校正 {origin / rate:+.3f}s")

    for job in jobs:
        start = max(0, origin + int(job["start"] * rate) - int(rate * 0.15))
        end = min(total_frames, origin + int(job["end"] * rate) + int(rate * 0.15))
        segment = slice_frames(samples, channels, start, end)
        peak = peak_of(segment)
        if peak <= 0:
            print(f"[警告] {job['out']} 全静音，跳过")
            continue
        threshold = max(96, int(peak * 0.01))
        a, b = find_active_span(segment, channels, threshold)
        if a < 0:
            print(f"[警告] {job['out']} 未检测到有效音频，跳过")
            continue
        # 前后各留 10ms
        pad = int(rate * 0.01)
        a = max(0, a - pad)
        b = min(frames_of(segment, channels) - 1, b + pad)
        trimmed = slice_frames(segment, channels, a, b + 1)

        if job["kind"] == "voice":
            target = int(rate * 2.0)
            cut = choose_loop_end(trimmed, channels, rate, 0, target, int(rate * 0.25))
            trimmed = slice_frames(trimmed, channels, 0, cut)
            trimmed = apply_fades(trimmed, channels, rate, 10.0, 12.0)
        elif job["kind"] == "loop":
            # 循环层不做淡入淡出，避免循环时出现音量凹陷
            pass
        else:
            trimmed = apply_fades(trimmed, channels, rate, 3.0, 12.0)

        dst = out_dir / job["out"]
        write_wav(dst, channels, rate, trimmed)
        dur = frames_of(trimmed, channels) / rate
        print(f"[输出] {dst.name}: {dur:.2f}s, peak={peak}")

    build_audio_data_js(out_dir)


def probe_voice_peak(raw_wav: Path, timings: List[dict]) -> int:
    """检查第一段语音是否录到声音，用来判断参数索引是否猜对。"""
    first_voice = next((j for j in timings if j["kind"] == "voice"), None)
    if first_voice is None:
        return 0
    channels, rate, samples = read_wav(raw_wav)
    limit = min(frames_of(samples, channels), int((first_voice["end"] + 0.5) * rate))
    return peak_of(slice_frames(samples, channels, 0, limit))


def main() -> int:
    faulthandler.enable()
    ap = argparse.ArgumentParser(description="用 FMOD Studio 渲染 Celeste 对话语音")
    ap.add_argument("--game-dir", default=os.environ.get("CELESTE_DIR", DEFAULT_GAME_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--keep-raw", action="store_true", help="保留合并后的 _raw.wav")
    ap.add_argument("--limit", type=int, default=0, help="只渲染前 N 个任务（调试用）")
    args = ap.parse_args()

    game = Path(args.game_dir)
    out = Path(args.out_dir)
    dll_dir = game / "lib64-win-x64"
    fmod_dir = game / "Content" / "FMOD" / "Desktop"

    if not (dll_dir / "fmodstudio.dll").is_file():
        print(f"[错误] 找不到 {dll_dir / 'fmodstudio.dll'}", file=sys.stderr)
        return 2

    banks = [
        fmod_dir / "Master Bank.bank",
        fmod_dir / "Master Bank.strings.bank",
        fmod_dir / "sfx.bank",
        fmod_dir / "ui.bank",
    ]
    for bank in banks:
        if not bank.is_file():
            print(f"[错误] 找不到 bank：{bank}", file=sys.stderr)
            return 2

    jobs = build_jobs(out)
    if args.limit > 0:
        jobs = jobs[:args.limit]
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    raw_wav = audio_dir / "_raw.wav"

    try:
        mapping = (0, 1)
        channels = rate = 0
        timings: List[dict] = []
        for attempt in (1, 2):
            channels, rate, timings = render(
                jobs, dll_dir, banks, raw_wav,
                portrait_index=mapping[0], end_index=mapping[1])
            peak = probe_voice_peak(raw_wav, timings)
            print(f"[校验] dialogue_portrait 索引={mapping[0]} / dialogue_end={mapping[1]} "
                  f"试录峰值={peak}")
            if peak > 500:
                break
            if attempt == 1:
                print("[校验] 这一组索引没有声音，交换索引后重试")
                mapping = (1, 0)
                if raw_wav.exists():
                    raw_wav.unlink()
            else:
                raise FmodError("两种参数索引组合都录不到语音，请检查 bank 是否匹配")

        export(timings, raw_wav, audio_dir, channels, rate)
    except FmodError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 3

    if not args.keep_raw and raw_wav.exists():
        raw_wav.unlink()

    print(f"[完成] 语音输出目录：{audio_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
