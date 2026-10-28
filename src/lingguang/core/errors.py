"""异常分类。

不要把异常堆成一个 Exception。四类错误的处理方式完全不同：
认证失效要人重新导入，限流要退避，接口变了要报警，网络问题要重试。

ContractError 是逆向工具的生命线。所有解析器在结构不符时抛它，
带原始样本片段，接口一改就能立刻定位，不会静默返回空数据。
"""

from __future__ import annotations


class LingguangError(Exception):
    """所有本工具异常的基类。"""


class AuthError(LingguangError):
    """cookie 失效或缺失。处理方式是提示用户重新导入，重试无用。"""


class RateLimitError(LingguangError):
    """被限流。处理方式是退避后重试。

    要注意这类接口的风控后果不止于本次请求失败，
    账号被标记会连带影响用户在 App 里的正常使用。
    """


class ContractError(LingguangError):
    """接口结构不符合预期。上游改版了。

    message 里必须带原始样本片段，否则排查时无从下手。
    处理方式是报警并保存原始响应，不要重试。
    """

    def __init__(self, message: str, sample: str | None = None) -> None:
        super().__init__(message)
        self.sample = (sample or "")[:2048]


class TransportError(LingguangError):
    """网络层面的问题。超时、连接重置、DNS 失败都归这里。处理方式是重试。

    注意：SSE 断流不走这里。断流是 dispatched_unknown，属于业务状态不是错误。
    """


class TruncatedResponseError(LingguangError):
    """服务端返回成功但内容不可用。用于识别异常短或异常的响应。"""
