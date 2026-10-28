"""写入扩展点。

用户明确不加本地库，理由是容易不同步。这个判断成立，所以默认实现是空操作。

但接口要设计成幂等的，否则将来实现 SQLite 时，
get_transcript 和 get_answer 会重复写入同一轮。
去重依据是 (session_id, query_id)。
"""

from __future__ import annotations

from typing import Literal, Protocol

from .models import Turn

Source = Literal["transcript", "answer"]


class MessageSink(Protocol):
    def upsert_turn(self, session_id: str, turn: Turn, source: Source) -> None:
        """写入或更新一轮问答。

        必须幂等。同一个 (session_id, query_id) 重复调用不应产生重复数据，
        也不应报错。
        """
        ...


class NullSink:
    """默认实现。什么都不做。

    没有本地库时用它，上层代码不需要判断 sink 是否存在。
    """

    def upsert_turn(self, session_id: str, turn: Turn, source: Source) -> None:
        return None
