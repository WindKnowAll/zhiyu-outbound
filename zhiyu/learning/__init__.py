"""已审核的场景话术。未批准的异常记录不会改变回答。"""

from zhiyu.learning.store import LearningRejected, LearningStore

__all__ = ["LearningRejected", "LearningStore"]
