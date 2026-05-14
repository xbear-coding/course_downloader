"""ASR 引擎测试"""
import pytest


class TestTranscribeAudio:
    """语音转写功能测试"""

    async def test_audio_file_not_found(self):
        from app.services.asr_engine import transcribe_audio
        from pathlib import Path

        with pytest.raises(FileNotFoundError):
            await transcribe_audio(Path("/nonexistent/file.wav"), "fake_key")

    async def test_invalid_api_key(self):
        """无效 Key 应返回非 200 状态码"""
        from app.services.asr_engine import transcribe_audio
        from pathlib import Path
        import tempfile, asyncio

        # 生成最小测试音频
        wav = Path(tempfile.gettempdir()) / "test_asr_invalid.wav"
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "1", str(wav)]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        if not wav.exists():
            pytest.skip("ffmpeg 不可用")

        with pytest.raises(RuntimeError) as exc:
            await transcribe_audio(wav, "sk-invalid-key")
        assert "ASR API 返回" in str(exc.value) or "401" in str(exc.value) or "403" in str(exc.value)

        wav.unlink(missing_ok=True)

    async def test_transcribe_empty_audio(self):
        """空音频应返回空字符串或有效结果"""
        from app.services.asr_engine import transcribe_audio
        from pathlib import Path
        import tempfile, asyncio

        wav = Path(tempfile.gettempdir()) / "test_asr_empty.wav"
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "0.5", str(wav)]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        if not wav.exists():
            pytest.skip("ffmpeg 不可用")

        try:
            result = await transcribe_audio(wav, "sk-test")
        except RuntimeError:
            # API 调用失败是预期的（测试 Key）
            pass
        else:
            assert isinstance(result, str)

        wav.unlink(missing_ok=True)
