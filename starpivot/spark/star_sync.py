"""GitHub 星数同步 + 好评率综合计算"""
import json, logging, urllib.request
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GITHUB_CACHE_TTL = timedelta(hours=24)  # 24 小时缓存

def get_github_stars(repo_url: str) -> int:
    """从 GitHub API 获取仓库星数"""
    if not repo_url or "github.com" not in repo_url:
        return 0
    try:
        # 提取 owner/repo
        parts = repo_url.strip("/").split("/")
        owner, repo = parts[-2], parts[-1].replace(".git", "")
        url = f"https://api.github.com/repos/{owner}/{repo}"
        data = json.loads(urllib.request.urlopen(url, timeout=8).read())
        return data.get("stargazers_count", 0)
    except Exception as e:
        logger.warning("获取 GitHub 星数失败: %s", e)
        return 0

def github_stars_to_score(stars: int) -> float:
    """GitHub 星数归一化到 0-100 分"""
    if stars >= 1000000:
        return 100.0
    if stars >= 100000:
        return 80.0
    if stars >= 10000:
        return 60.0
    if stars >= 1000:
        return 40.0
    if stars >= 100:
        return 20.0
    if stars >= 10:
        return 10.0
    return 0.0
