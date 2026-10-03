# Yield public contracts / Yield 公开契约

This package contains contracts whose domain meaning is owned by Cyrene Yield
and may be consumed by other Products. `model_version.py` defines the immutable
model composition and lineage identity; `__init__.py` is the stable import
surface; `py.typed` declares inline type information for downstream Products.
Read `model_version.py` first, then use exports from `__init__.py`.

本包保存由 Cyrene Yield 拥有业务语义、并可供其他 Product 使用的契约。
`model_version.py` 定义不可变模型组合与血缘身份，`__init__.py` 提供稳定导入面。
---

<!-- Chinese Translation / 中文翻译 -->

# Yield 公开契约

本 package 包含业务语义由 Cyrene Yield 拥有、可供其他 Product 使用的契约。model_version.py 定义不可变的模型组合与 lineage 身份；__init__.py 是稳定的导入接口；py.typed 声明供下游 Product 使用的内联类型信息。先阅读 model_version.py，再使用 __init__.py 导出的符号。
