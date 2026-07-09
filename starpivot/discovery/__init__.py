"""星枢引擎 — GitHub 工具自动发现系统 (StarPivot Discovery)

自动扫描 GitHub 发现新工具，生成 MCP Server 包装器，测试后自动注册。

核心组件:
    - GitHubScanner:       扫描 GitHub Trending / 关键词搜索仓库
    - MCPWrapperGenerator: 为发现的工具生成 MCP Server 包装器
    - AutoTester:          自动测试新生成的 MCP Server
    - RegistryManager:     管理 MCP Server 的注册/注销/更新

用法:
    scanner = GitHubScanner()
    repos = scanner.scan_trending()
    for repo in repos[:5]:
        analysis = scanner.analyze_repo(repo)
        if analysis.suitable:
            code = MCPWrapperGenerator().generate(analysis)
            path = f"/tmp/servers/{analysis.name}_server.py"
            with open(path, "w") as f:
                f.write(code)
            result = AutoTester().test_server(path)
            if result.passed:
                RegistryManager().register(name=analysis.name, server_code=code)
"""

from .github_scanner import GitHubScanner, RepoInfo, RepoAnalysis
from .wrapper_generator import MCPWrapperGenerator
from .auto_tester import AutoTester, TestResult
from .registry_manager import RegistryManager

__all__ = [
    "GitHubScanner",
    "RepoInfo",
    "RepoAnalysis",
    "MCPWrapperGenerator",
    "AutoTester",
    "TestResult",
    "RegistryManager",
]
