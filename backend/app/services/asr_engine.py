"""ASR 语音转写引擎（SiliconFlow API）"""
import httpx
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SILICONFLOW_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
MODEL = "TeleAI/TeleSpeechASR"


async def transcribe_audio(
    audio_path: Path,
    api_key: str,
    model: str = MODEL,
    timeout: int = 60,
) -> str:
    """调用 SiliconFlow ASR API 转写音频

    返回带时间戳的文本，格式：
    **00:00:12 →** 大家好...
    **00:01:45 →** 首先...
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(audio_path, "rb") as f:
            resp = await client.post(
                SILICONFLOW_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": f},
                data={
                    "model": model,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                    "language": "zh",
                },
            )

    if resp.status_code != 200:
        raise RuntimeError(f"ASR API 返回 {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    text = data.get("text", "")

    # 如果有 segments，构造成带时间戳的格式
    segments = data.get("segments", [])
    if segments:
        lines = []
        for seg in segments:
            start = seg.get("start", 0)
            seg_text = seg.get("text", "")
            if not seg_text.strip():
                continue
            # 秒 → HH:MM:SS
            h, r = divmod(int(start), 3600)
            m, s = divmod(r, 60)
            lines.append(f"**{h:02d}:{m:02d}:{s:02d} →** {seg_text.strip()}")
        return "\n".join(lines)

    return text
