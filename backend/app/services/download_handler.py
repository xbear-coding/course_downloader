"""下载处理器 — 桥接 TaskScheduler 与平台插件（含 3 层错误恢复）"""
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from app.database import async_session
from app.models import Task, TaskStatus, StepStatus, Account, Platform
from app.api.ws import manager
from app.services.platform_base import (
    BasePlatform, VideoCapable, ArticleCapable, ContentItem,
)
from app.services.asr_engine import transcribe_audio
from app.services.media_converter import ts_to_mp4, extract_audio
from app.config import DATA_DIR

logger = logging.getLogger(__name__)

# 3 层错误恢复：重试延迟（秒）
RETRY_DELAYS = [0, 5, 15]


async def _get_safe_output_dir(task: Task) -> Path:
    """安全获取输出目录（处理 account/platform 为空的情况）"""
    default = DATA_DIR / "downloads" / task.platform
    if not task.account_id:
        return default
    async with async_session() as db:
        acct = await db.get(Account, task.account_id)
        if not acct:
            return default
        # acct.platform 可能懒加载失败，手动查询
        plat = await db.get(Platform, acct.platform_id)
        if plat and plat.output_dir:
            return Path(plat.output_dir)
    return default


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

    output_dir = await _get_safe_output_dir(task)
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

        # 3 层错误恢复：逐级尝试
        last_error = None
        for retry_idx, delay in enumerate(RETRY_DELAYS):
            if delay > 0:
                logger.info(
                    f"[第{retry_idx + 1}次重试] 步骤 {step['name']} "
                    f"等待 {delay}s..."
                )
                await asyncio.sleep(delay)

            try:
                if step["name"] == "downloading" and task.content_type in ("video", "audio"):
                    await _handle_video_download(platform, task, item, output_dir, idx, total_steps)
                elif step["name"] == "article" and task.content_type == "article":
                    await _handle_article_download(platform, task, item, output_dir, idx, total_steps)
                elif step["name"] == "transcript":
                    await _handle_transcript(task, output_dir, idx, total_steps)
                elif step["name"] == "convert":
                    await _handle_convert(task, output_dir, idx, total_steps)

                # 成功
                last_error = None
                break

            except Exception as e:
                last_error = e
                logger.warning(
                    f"[{task.id}] 步骤 {step['name']} 第{retry_idx + 1}次失败: {e}"
                )
                continue

        if last_error:
            # 重试耗尽 → 第 2 层：降级（非关键步骤继续，关键步骤终止）
            is_critical = step["name"] in ("downloading",)
            if is_critical:
                logger.error(f"[{task.id}] 关键步骤失败，终止任务: {last_error}")
                await _update_step_status(task.id, step["name"], StepStatus.FAILED)
                await _mark_failed(task.id, str(last_error)[:200])
                return
            else:
                # 非关键步骤降级：标记跳过，继续后续
                logger.warning(
                    f"[{task.id}] 非关键步骤 {step['name']} 降级跳过"
                )
                await _update_step_status(task.id, step["name"], StepStatus.SKIPPED)
                continue

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
        db_task.video_path = str(result.file_path or raw_output)
        db_task.video_status = StepStatus.DONE
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
        db_task.article_status = StepStatus.DONE
        await db.commit()


async def _handle_transcript(
    task: Task, output_dir: Path, step_idx: int, total: int,
):
    # 检查是否跳过转录
    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        if db_task.transcript_status == StepStatus.SKIPPED:
            return

    # 统一读取所需路径
    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        article_path_str = db_task.article_path
        video_path_str = db_task.video_path

    article_path = Path(article_path_str) if article_path_str else None
    video_path = Path(video_path_str) if video_path_str else None

    has_article = article_path and article_path.exists()
    has_video = video_path and video_path.exists()
    transcript_text = ""

    if has_article:
        transcript_text = article_path.read_text(encoding="utf-8")

    elif has_video:
        audio_path = output_dir / f"{task.resource_id}_audio.wav"
        ok = await extract_audio(video_path, audio_path)
        if not ok:
            raise RuntimeError("音频提取失败")

        # 获取 ASR API Key（支持多个 provider）
        async with async_session() as db:
            from app.models import APIKey
            from sqlalchemy import select
            api_key = None
            for provider in ("siliconflow", "groq", "openai"):
                result = await db.execute(
                    select(APIKey).where(
                        APIKey.is_active == True,
                        APIKey.provider == provider,
                    )
                )
                api_key = result.scalar_one_or_none()
                if api_key:
                    break

        if not api_key:
            raise RuntimeError("未找到可用的 ASR API Key")

        from app.services.crypto import decrypt
        try:
            plain_key = decrypt(api_key.key_value)
        except Exception:
            raise RuntimeError("ASR API Key 解密失败，加密密钥可能已变更")

        transcript_text = await transcribe_audio(audio_path, plain_key)
        audio_path.unlink(missing_ok=True)

    if transcript_text:
        transcript_path = output_dir / f"{task.resource_id}_transcript.md"
        transcript_path.write_text(transcript_text, encoding="utf-8")
        await _update_progress(task.id, step_idx, total, 100)

        async with async_session() as db:
            db_task = await db.get(Task, task.id)
            db_task.transcript_path = str(transcript_path)
            db_task.transcript_status = StepStatus.DONE
            await db.commit()


async def _handle_convert(
    task: Task, output_dir: Path, step_idx: int, total: int,
):
    async with async_session() as db:
        db_task = await db.get(Task, task.id)
        raw_path = Path(db_task.video_path) if db_task.video_path else None

    if not raw_path or not raw_path.exists():
        return

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
        field_map = {"downloading": "video_status", "transcript": "transcript_status", "article": "article_status"}
        field = field_map.get(step)
        if field:
            setattr(db_task, field, status.value)
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
        total_size = 0
        for attr in ("video_path", "article_path", "transcript_path"):
            path_str = getattr(db_task, attr, None)
            if path_str and Path(path_str).exists():
                total_size += Path(path_str).stat().st_size
        db_task.file_size_bytes = total_size
        await db.commit()
    await manager.push_task_done(task.id)


async def _mark_failed(task_id: int, error: str):
    async with async_session() as db:
        db_task = await db.get(Task, task_id)
        db_task.status = TaskStatus.FAILED
        db_task.error_message = error
        await db.commit()
    await manager.push_task_error(task_id, "execute", error[:100])
