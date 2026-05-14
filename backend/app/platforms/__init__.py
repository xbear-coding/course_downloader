"""平台插件注册表"""
from typing import Optional
from app.services.platform_base import BasePlatform

_registry: dict[str, type[BasePlatform]] = {}


def register(name: str, cls: type[BasePlatform]):
    _registry[name] = cls


def get_platform(name: str) -> Optional[BasePlatform]:
    cls = _registry.get(name)
    if cls:
        return cls()
    return None


def list_platforms() -> list[str]:
    return list(_registry.keys())


def _init():
    from app.platforms.tencent_meeting import TencentMeetingPlugin
    from app.platforms.xiaoe import XiaoEPlugin
    from app.platforms.bilibili import BilibiliPlugin
    from app.platforms.xiaohongshu import XiaohongshuPlugin
    from app.platforms.toutiao import ToutiaoPlugin
    from app.platforms.douyin import DouyinPlugin
    register("tencent_meeting", TencentMeetingPlugin)
    register("xiaoe", XiaoEPlugin)
    register("bilibili", BilibiliPlugin)
    register("xiaohongshu", XiaohongshuPlugin)
    register("toutiao", ToutiaoPlugin)
    register("douyin", DouyinPlugin)


_init()
