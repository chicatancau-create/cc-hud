"""数据源适配器注册。"""
from . import cchaha, ccswitch, codex, dsh, herdsman, qoder, workbuddy, zcode

# 顺序即合并顺序：ccswitch 是基准，其余按此顺序做双计检查。
ADAPTERS = [
    ccswitch,
    cchaha,
    qoder,
    zcode,
    herdsman,
    codex,
    workbuddy,
    dsh,
]
