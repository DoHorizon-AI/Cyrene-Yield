# Training environment policy / 训练环境策略

This directory owns Yield's environment intent, immutable lock, and candidate
selection. `contracts.py` defines the data model, `resolver.py` performs
deterministic selection, and `__init__.py` exposes the internal Product API.
Read them in that order.

本目录负责 Yield 的环境意图、不可变锁和候选环境选择。依次阅读
`contracts.py`、`resolver.py` 和 `__init__.py`。
