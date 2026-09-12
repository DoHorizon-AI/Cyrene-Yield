# Yield public contracts / Yield 公开契约

This package contains contracts whose domain meaning is owned by Cyrene Yield
and may be consumed by other Products. `model_version.py` defines the immutable
model composition and lineage identity; `__init__.py` is the stable import
surface; `py.typed` declares inline type information for downstream Products.
Read `model_version.py` first, then use exports from `__init__.py`.

本包保存由 Cyrene Yield 拥有业务语义、并可供其他 Product 使用的契约。
`model_version.py` 定义不可变模型组合与血缘身份，`__init__.py` 提供稳定导入面。
