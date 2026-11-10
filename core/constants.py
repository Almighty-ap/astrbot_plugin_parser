from typing import Final

COMMON_HEADER: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/55.0.2883.87 UBrowser/6.2.4098.3 Safari/537.36"
    )
}

IOS_HEADER: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1 Edg/132.0.0.0"
    )
}

ANDROID_HEADER: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/132.0.0.0 Mobile Safari/537.36 Edg/132.0.0.0"
    )
}

# CDN 防盗链兜底 Referer 映射（域名后缀 -> Referer）
# 仅在媒体下载被 401/403 拦截且请求头未带 Referer 时使用，不影响正常下载链路
CDN_REFERER: Final[dict[str, str]] = {
    # 抖音
    "douyinpic.com": "https://www.douyin.com/",
    "douyinvod.com": "https://www.douyin.com/",
    "iesdouyin.com": "https://www.iesdouyin.com/",
    # 哔哩哔哩
    "bilivideo.com": "https://www.bilibili.com/",
    "bilivideo.cn": "https://www.bilibili.com/",
    "hdslb.com": "https://www.bilibili.com/",
    # 小红书
    "xhscdn.com": "https://www.xiaohongshu.com/",
    # 快手
    "kwaicdn.com": "https://www.kuaishou.com/",
    # 微博
    "sinaimg.cn": "https://weibo.com/",
    # TikTok
    "tiktokcdn.com": "https://www.tiktok.com/",
    "tiktokcdn-us.com": "https://www.tiktok.com/",
}
