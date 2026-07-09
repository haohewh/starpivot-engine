"""星火鉴 (Spark Judge) — 星枢工具九维质量评估体系。

┌──────────────────────────────────────────────────────────────┐
│  #  指标            权重   等级       总分                   │
│  1. 实用性         20%    S(≥95)  A(≥85)  B(≥70)           │
│  2. 扩展性         15%    C(≥55)  D(≥40)  F(<40)           │
│  3. 稳定性         15%                                       │
│  4. 时速性         10%    ⭐ 满分 100，按权重加权          │
│  5. 更新力         10%                                       │
│  6. 安全性         10%                                       │
│  7. 兼容性         10%                                       │
│  8. 好评率          5%                                       │
│  9. 星数            5%                                       │
└──────────────────────────────────────────────────────────────┘
"""

from .judge import SparkJudge
from .utility_test import UtilityTest
from .stability_test import StabilityTest
from .speed_test import SpeedTest
from .update_monitor import UpdateMonitor
from .security_test import SparkSecurityTest
from .integration_test import IntegrationTest
from .review_system import ReviewSystem

__all__ = [
    "SparkJudge",
    "UtilityTest",
    "StabilityTest",
    "SpeedTest",
    "UpdateMonitor",
    "SparkSecurityTest",
    "IntegrationTest",
    "ReviewSystem",
]
