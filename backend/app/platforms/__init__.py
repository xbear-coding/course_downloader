"""平台插件注册表（单例模式）"""
from typing import Optional
from app.services.platform_base import BasePlatform

_registry: dict[str, type[BasePlatform]] = {}
_instances: dict[str, BasePlatform] = {}


def register(name: str, cls: type[BasePlatform]):
    _registry[name] = cls


def get_platform(name: str) -> Optional[BasePlatform]:
    """获取平台插件实例（单例，确保浏览器和登录状态复用）"""
    if name in _instances:
        return _instances[name]
    cls = _registry.get(name)
    if cls:
        inst = cls()
        _instances[name] = inst
        return inst
    return None


def reset_platform(name: str):
    """重置平台插件实例（用于重新登录）"""
    _instances.pop(name, None)


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
