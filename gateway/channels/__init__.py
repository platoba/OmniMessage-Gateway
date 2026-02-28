"""
渠道基类 - 所有渠道的抽象接口
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from gateway.models import Message, SendResult, ChannelType


class BaseChannel(ABC):
    """渠道抽象基类"""

    channel_type: ChannelType

    def __init__(self, config: Any = None):
        self.config = config
        self._enabled = False

    @property
    def name(self) -> str:
        return self.channel_type.value

    @property
    def enabled(self) -> bool:
        return self._enabled

    @abstractmethod
    def configure(self, config: Any) -> None:
        """配置渠道"""
        pass

    @abstractmethod
    async def send(self, message: Message) -> SendResult:
        """发送消息"""
        pass

    @abstractmethod
    async def validate(self) -> bool:
        """验证渠道配置是否有效"""
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} enabled={self.enabled}>"
