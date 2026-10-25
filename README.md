
<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_parser?name=astrbot_plugin_parser&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_parser

_✨ 链接解析器 ✨_  

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-3.4%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)

</div>

## 📖 介绍

| JMComic | 链接(含短链) / jm 号             | ❌️  | ✅​  | ❌️  |
内置解析器适配矩阵（`—` 表示当前内置实现已禁用）：

| 平台 | 触发的消息形态 | 视频 | 图集 | 音频 | 备注 |
| --- | --- | :---: | :---: | :---: | --- |
| B 站 | `av` / `BV` / `bmBV`、视频/动态/直播/收藏夹/专栏/Opus 链接、短链 | ✅ | ✅ | ✅ | `bmBV` 提取音频；多 P 视频可在编号后指定分 P |
| 抖音 | 分享短链、电脑端链接、`aweme_id`、作品 ID | ✅ | ✅ | ❌ | 支持视频与图文作品，部分内容需要 Cookie |
| 快手 | 标准链接、`v.kuaishou.com` 短链、`chenzhongtech.com` 链接 | ✅ | ✅ | ❌ | 支持视频与图集，登录态可提高解析成功率 |
| QQ 空间 | `h5.qzone.qq.com/ugc/share`、`mobile.qzone.qq.com/l` 公开分享链接/卡片 | ✅ | ✅ | ❌ | 默认关闭；可选 SnowLuma 自动凭证或手动 Cookie，保留公开页面回退 |
| 微信视频号 | `weixin.qq.com/sph` 短链、带 `token`/`eid` 的预览长链 | ✅ | ❌ | ❌ | 短链需要腾讯元宝 Cookie；预览长链自带凭证时可直接解析 |
| 微博 | 博文、视频、`show`、文章及分享链接 | ✅ | ✅ | ❌ | Cookie 可提升受限内容和登录态页面的可用性 |
| 小红书 | 标准链接、`xhslink.com` / `xhslink.cn` 短链、卡片 | ✅ | ✅ | ❌ | 支持视频笔记与图文笔记，建议配置 Cookie |
| 小黑盒 | 社区帖子、分享链接、游戏详情链接/卡片 | ✅ | ✅ | ❌ | 支持图文混排；可配置正文、原图和视频发送方式 |
| 知乎 | 专栏、问题、回答、想法链接/卡片 | ✅ | ✅ | ❌ | 解析正文中的图片和视频，登录态可改善受限页面访问 |
| TikTok | 标准链接、`vt.tiktok.com` / `vm.tiktok.com` 短链 | ✅ | ✅ | ❌ | 照片集使用图文接口解析，失败时会在视频与图文路径间回退 |
| YouTube | 视频、Shorts、`youtu.be` 短链；`ym` + 链接 | ✅ | ❌ | ✅ | 普通链接下载视频；`ym` 前缀提取音频，通常需要 Cookie |
| Metube | YouTube 视频、Shorts、`youtu.be` 短链 | ✅ | ❌ | ❌ | 需要独立 Metube 服务；启用后接管 YouTube 视频路由，`ym` 音频仍由 YouTube 解析器处理 |
| Instagram | `p` / `reel` / `reels` / `tv` / `share` 链接 | ✅ | ✅ | ❌ | 支持帖子、图集和 Reels；Cookie 可提高私有或受限内容成功率 |
| Twitter / X | `twitter.com` / `x.com` 状态链接 | ✅ | ✅ | ❌ | 通过解析服务提取推文视频、图片和引用内容 |
| AcFun | `ac` 号或稿件链接 | ✅ | ❌ | ❌ | 下载并合并 HLS 视频流，Cookie 为可选项 |
| 网易云音乐 | 歌曲链接、`163cn.tv` 短链、MP3/外链播放地址 | ❌ | ❌ | ✅ | 支持歌曲元数据、封面和音频直链，部分资源受版权或登录态限制 |
| NGA | `ngabbs.com` / `nga.178.com` / `bbs.nga.cn` 主题链接 | ❌ | ✅ | ❌ | 返回主题首帖文本与图片；登录可见内容需要 Cookie |
| CPP 无差别同人站 | `icp.red` 短链、展品 `/d/`、图文 `/w/` 链接 | ❌ | ✅ | ❌ | 未登录时展品试阅会退化为仅封面；正文显示长度可配置 |
| Pixiv | 插画/漫画/小说链接、`pid` / `pixivid` + ID | ❌ | ✅ | ❌ | 默认关闭且需要 Cookie；支持动图 GIF、漫画 PDF、小说 TXT，R18/R18G 固定忽略 |
| Iwara | 链接(含短链) | ❌️  | ✅​  | ❌️ | R18 |
| nhentai | 链接(含短链) | ❌️  | ✅​  | ❌️ | R18 |
| JMComic | 链接(含短链) / jm 号             | ❌️  | ✅​  | ❌️  | R18 |

本插件目标：凡是链接皆可解析！尽请期待更新（如果可以,请提交PR）

---

## 🎨 效果图

插件默认启用 PIL 实现的通用媒体卡片渲染，效果图如下

<div align="center">

<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/video.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/9_pic.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/4_pic.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/repost_video.png" width="160" />
<img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-parser/refs/heads/resources/resources/renderdamine/repost_2_pic.png" width="160" />

</div>

---

## 💿 安装

直接在astrbot的插件市场搜索astrbot_plugin_parser，点击安装，等待完成即可

## ⚙️ 配置

请在astrbot的插件配置面板查看并修改

## 🎉 指令

|   指令   |         权限          |        说明        |
| :------: | :-------------------: |  :---------------: |
| 开启解析 |      ADMIN            |     开启当前会话的解析功能      |
| 关闭解析 |      ADMIN            |    关闭当前会话的解析功能      |
|  blogin  |      ADMIN           |   扫码获取 B 站凭证 |

---

## 🧠 插件工作流程

当插件运行后，每一条消息的处理流程如下：

1. **消息接收**  
   监听所有消息事件，获取消息链与原始文本内容  
   - 支持普通文本、链接、卡片（Json 组件）

2. **基础过滤**  
   - 跳过已被禁用的会话  
   - 跳过空消息  
   - 若消息首段为 `@` 且目标不是本 Bot，则不解析

3. **链接提取与匹配**  
   - 若为卡片消息，先从 Json 中提取 URL  
   - 使用「关键词 + 正则」双重匹配，定位对应解析器  
   - 未匹配到解析规则则直接退出

4. **仲裁判定（Emoji Like Arbiter）**  
   - 仅在 `aiocqhttp` 平台生效  
   - 通过固定表情进行 Bot 间仲裁  
   - 未胜出的 Bot 自动放弃解析

5. **防抖判定（Link Debouncer）**  
   - 对同一会话内的相同链接进行时间窗口限制  
   - 命中防抖规则则跳过解析，避免短时间重复处理

6. **内容解析**  
   - 调用对应平台解析器获取媒体信息  
   - 生成统一的 `ParseResult` 数据结构

7. **媒体下载与消息构建**  
   - 下载视频 / 图片 / 音频 / 文件  
   - 根据配置决定音频发送方式  
   - 可按配置提示下载失败项

8. **卡片渲染（可选）**  
   - 在非简洁模式或无直传媒体时生成媒体卡片  
   - 使用 PIL 渲染并缓存图片

9. **消息合并与发送**  
    - 当消息段数量超过阈值时自动合并为转发消息  
    - 最终将结果发送到对应会话

---

## 🧩 扩展

插件支持自定义解析器，通过继承 `BaseParser` 类并实现 `platform`, `handle` 即可。

示例解析器请看 [示例解析器](https://github.com/Zhalslar/astrbot_plugin_parser/blob/main/core/parsers/example.py)

---

## 🎉 致谢

本项目初始版本改自 [nonebot-plugin-parser](https://github.com/fllesser/nonebot-plugin-parser) 插件，请前往原仓库给作者点个Star!

## 🤪 注意

有问题想第一时间交流，可前往 Astrbot 插件开发群：460973561（不点star不给进）
