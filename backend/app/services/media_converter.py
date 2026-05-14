"""媒体转码引擎（ffmpeg 封装）"""
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def ts_to_mp4(
    input_path: Path,
    output_path: Path,
    preset: str = "medium",
    crf: int = 28,
) -> bool:
    """TS 文件转 MP4（H.265）

    参数：
        input_path:  输入 .ts 文件路径
        output_path: 输出 .mp4 文件路径
        preset:      ffmpeg preset（medium / fast / slow）
        crf:         质量参数（28=平衡, 22=高质量, 32=小体积）

    返回：是否成功
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "libx265",
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        logger.error(f"ffmpeg 转码超时 (>600s)")
        return False

    if proc.returncode != 0:
        logger.error(f"ffmpeg 转码失败: {stderr.decode()[:200]}")
        return False

    if output_path.exists():
        logger.info(f"转码成功: {output_path} ({output_path.stat().st_size / 1024 / 1024:.1f}MB)")
        return True
    return False


async def extract_audio(
    video_path: Path,
    output_path: Path,
    sample_rate: int = 16000,
) -> bool:
    """从视频中提取音频"""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error(f"音频提取失败: {stderr.decode()[:200]}")
        return False
    return output_path.exists()
