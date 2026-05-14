"""下载处理器 — 桥接 TaskScheduler 与平台插件"""
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from app.database import async_session
from app.models import Task, TaskStatus, StepStatus
from app.api.ws import manager
from app.services.platform_base import (
    BasePlatform, VideoCapable, ArticleCapable, ContentItem,
)
from app.services.asr_engine import transcribe_audio
from app.services.media_converter import ts_to_mp4, extract_audio
from app.config import DATA_DIR

logger = logging.getLogger(__name__)


async def execute_download(task: Task):
    """执行实际下载流程（由 TaskScheduler 调用）"""
    from app.platforms import get_platform

    platform = get_platform(task.platform)
    if not platform:
        raise ValueError(f"不支持的平台: {task.platform}")

    item = ContentItem(
        platform=task.platform,
        item_id=task.resource_id or "",
        title=task.title,
        content_type=task.content_type,
        url=task.url or "",
    )

    output_dir = Path(task.account.platform.output_dir or str(DATA_DIR / "downloads" / task.platform)) if task.account else DATA_DIR / "downloads" / task.platform
    output_dir.mkdir(parents=True, exist_ok=True)

    steps = _get_steps(task.content_type)
    total_steps = len(steps)

    for idx, step in enumerate(steps):
        await manager.push_task_update(
            task_id=task.id, step=step["name"],
            step_index=idx + 1, step_total=total_steps,
            step_progress=0, total_progress=int(idx / total_steps * 100),
            message=step["start_msg"],
        )

        try:
            if step["name"] == "downloading" and task.content_type in ("video", "audio"):
                await _handle_video_download(platform, task, item, output_dir, idx, total_steps)
            elif step["name"] == "article" and task.content_type == "article":
                await _handle_article_download(platform, task, item, output_dir, idx, total_steps)
            elif step["name"] == "transcript":
                await _handle_transcript(platform, task, item, output_dir, idx, total_steps)
            elif step["name"] == "convert":
                await _handle_convert(task, output_dir, idx, total_steps)
        except Exception as e:
            logger.error(f"步骤 {step['name']} 失败: {e}")
            await _update_step_status(task.id, step["name"], StepStatus.FAILED)
            raise

        await _update_step_status(task.id, step["name"], StepStatus.DONE)

    await _mark_done(task, output_dir)


def _get_steps(content_type: str) -> list[dict]:
    steps = []
    if content_type in ("video", "audio"):
        steps.append({"name": "downloading", "start_msg": "正在下载视频...", "progress_msg": "下载中"})
        steps.append({"name": "convert", "start_msg": "正在转码...", "progress_msg": "转码中"})
    elif content_type == "article":
        steps.append({"name": "article", "start_msg": "正在抓取文章...", "progress_msg": "抓取中"})

    steps.append({"name": "transcript", "start_msg": "正在转写文字...", "progress_msg": "转写中"})
    return steps


async def _handle_video_download(
    platform: BasePlatform, task: Task, item: ContentItem,
    output_dir: Path, step_idx: int, total: int,
):
    if not isinstance(platform, VideoCapable):
        logger.warning(f"[{task.platform}] 不支持视频下载")
        return

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_output = raw_dir / f"{task.resource_id}.ts"

    result = await platform.download_video(item, raw_output, quality="720p")
    if not result.success:
        raise RuntimeError(result.error_message or "视频下载失败")

    await _update_progress(task.id, step_idx, total, 100)

    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        db_task.video_path = str(raw_output)
        if result.file_path:
            db_task.video_path = str(result.file_path)
        db_task.video_status = StepStatus.DONE.value
        await db.commit()


async def _handle_article_download(
    platform: BasePlatform, task: Task, item: ContentItem,
    output_dir: Path, step_idx: int, total: int,
):
    if not isinstance(platform, ArticleCapable):
        logger.warning(f"[{task.platform}] 不支持文章抓取")
        return

    article_output = output_dir / f"{task.resource_id}.md"
    result = await platform.download_article(item, article_output)
    if not result.success:
        raise RuntimeError(result.error_message or "文章抓取失败")

    await _update_progress(task.id, step_idx, total, 100)

    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        db_task.article_path = str(article_output)
        db_task.article_status = StepStatus.DONE.value
        await db.commit()


async def _handle_transcript(
    platform: BasePlatform, task: Task, item: ContentItem,
    output_dir: Path, step_idx: int, total: int,
):
    # 检查是否已禁用转写（通过 transcript_status == SKIPPED）
    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        if db_task.transcript_status == StepStatus.SKIPPED.value:
            return
        has_article = db_task.article_path and Path(db_task.article_path).exists()
        has_video = db_task.video_path and Path(db_task.video_path).exists()

    transcript_text = ""

    if has_article:
        # 文章类：直接读取内容作为转写
        async with async_session() as db:
            db_task = await db.get(Task, task.id)
            article_path = Path(db_task.article_path)
        if article_path.exists():
            transcript_text = article_path.read_text(encoding="utf-8")

    elif has_video:
        # 视频类：调用 ASR
        async with async_session() as db:
            db_task = await db.get(Task, task.id)
            video_path = Path(db_task.video_path)

        audio_path = output_dir / f"{task.resource_id}_audio.wav"
        ok = await extract_audio(video_path, audio_path)
        if not ok:
            raise RuntimeError("音频提取失败")

        # 获取 ASR API Key
        async with async_session() as db:
            from app.models import APIKey
            from sqlalchemy import select
            result = await db.execute(
                select(APIKey).where(
                    APIKey.is_active == True,
                    APIKey.provider == "siliconflow",
                )
            )
            api_key = result.scalar_one_or_none()

        if not api_key:
            raise RuntimeError("未找到可用的 ASR API Key")

        transcript_text = await transcribe_audio(audio_path, api_key.key_value)
        audio_path.unlink(missing_ok=True)

    if transcript_text:
        transcript_path = output_dir / f"{task.resource_id}_transcript.md"
        transcript_path.write_text(transcript_text, encoding="utf-8")

        await _update_progress(task.id, step_idx, total, 100)

        async with async_session() as db:
            db_task = await db.get(Task, task.id)
            db_task.transcript_path = str(transcript_path)
            db_task.transcript_status = StepStatus.DONE.value
            await db.commit()


async def _handle_convert(
    task: Task, output_dir: Path, step_idx: int, total: int,
):
    async with async_session() as db:
        db_task = await db.get(Task, task.id)

    raw_path = Path(db_task.video_path) if db_task.video_path else None
    if not raw_path or not raw_path.exists():
        return

    # 如果已经是 mp4，跳过转码
    if raw_path.suffix.lower() == ".mp4":
        await _update_progress(task.id, step_idx, total, 100)
        return

    mp4_path = output_dir / f"{task.resource_id}.mp4"
    ok = await ts_to_mp4(raw_path, mp4_path)
    if ok:
        async with async_session() as db:
            db_task = await db.get(Task, task.id)
            db_task.video_path = str(mp4_path)
            await db.commit()

    await _update_progress(task.id, step_idx, total, 100)


async def _update_step_status(task_id: int, step: str, status: StepStatus):
    async with async_session() as db:
        db_task = await db.get(Task, task_id)
        if step == "downloading":
            db_task.video_status = status.value
        elif step == "transcript":
            db_task.transcript_status = status.value
        elif step == "article":
            db_task.article_status = status.value
        await db.commit()


async def _update_progress(task_id: int, step_idx: int, total: int, progress: int):
    await manager.push_task_update(
        task_id=task_id, step="processing",
        step_index=step_idx + 1, step_total=total,
        step_progress=progress,
        total_progress=int((step_idx + progress / 100) / total * 100),
        message=f"步骤 {step_idx + 1}/{total} 处理中",
    )


async def _mark_done(task: Task, output_dir: Path):
    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        db_task.status = TaskStatus.DONE
        db_task.downloaded_at = datetime.utcnow()

        # 计算文件大小
        for attr in ("video_path", "article_path", "transcript_path"):
            path_str = getattr(db_task, attr, None)
            if path_str and Path(path_str).exists():
                db_task.file_size_bytes = (db_task.file_size_bytes or 0) + Path(path_str).stat().st_size

        await db.commit()

    await manager.push_task_done(task.id)
