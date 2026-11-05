[English](README.md) · [简体中文](README.zh-CN.md)

<p align="center">
  <img src="docs/assets/ideck/icon.png" width="156" alt="iDeck">
</p>
<h1 align="center">iDeck (增强分支版)</h1>
<p align="center"><strong>在 iOS 与 iPadOS 上体验 Steam 与 Windows PC 游戏</strong><br>让你的 iPhone / iPad，成为随身携带的掌机与桌面游戏终端。</p>
<p align="center">
  <a href="https://discord.gg/aQdsaJyTM"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdiscord.com%2Fapi%2Finvites%2FaQdsaJyTM%3Fwith_counts%3Dtrue&query=%24.approximate_member_count&suffix=%20members&label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="加入 iDeck Discord 社区"></a>
</p>
<p align="center">
  <a href="docs/GETTING_STARTED.md"><img src="https://img.shields.io/badge/Platform-iOS%20%26%20iPadOS%2017%2B-007AFF" alt="iOS 与 iPadOS 平台"></a>
  <a href="docs/IDECK.md"><img src="https://img.shields.io/badge/Status-活跃维护中-success" alt="开发状态"></a>
  <a href="https://github.com/willfaust/Madeira"><img src="https://img.shields.io/badge/Powered%20by-Madeira%20%2B%20Wine%20%2B%20FEX-28C7D9" alt="底层动力: Madeira"></a>
  <a href="COPYING"><img src="https://img.shields.io/badge/License-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later"></a>
</p>

把手柄接上，打开 Steam 游戏库，给积灰的游戏一个住进兜里的机会。
iDeck 通过 **Madeira、Wine、FEX-Emu、DXMT 和 Metal**，在 iPhone 与 iPad 本地运行 Valve 真正的 Windows Steam 客户端（包含大屏幕模式 Big Picture 与标准桌面模式），以及部分兼容的 Windows PC 游戏，**无需从任何电脑远程串流**。

本分支（Fork）在此前基础上，针对 **iPadOS 18 适配**、**中文字体与乱码修复**、**HTTP/SOCKS5 全功能网络代理**、**UI 交互体验** 以及 **CI/CD 自动化构建** 进行了深度优化与重构。

> **SteamOS 的体验，iOS 的底层。** 这里运行的是通过指令转译与兼容层驱动的 Windows Steam 与游戏，并非安装 Linux SteamOS，也不是将所有游戏重新编译为 ARM 原生 iOS 应用。

<p align="center">
  <img src="docs/assets/ideck/demo-landscape-ccw90-1.5x.gif" width="831" alt="iPhone 本地启动 Steam 与 PC 游戏的演示，1.5 倍速">
  <br><sub>真机演示 · 1.5 倍速 · 实验构建</sub>
</p>

---

## 本分支（Fork）核心新增特性与改进

### 1. 🈲 完整 CJK / 中文字体支持（彻底告别豆腐块 `□□□□` 乱码）
- **内置完整字库**：打包内置包含 49,775+ 字形的 `DroidSansFallback.ttf`（全量覆盖 GBK / 简繁体中文、日文假名及韩文），并附带 Wine 核心字体库（`simsun.ttc` 宋体、`msyh.ttc` 微软雅黑、`tahoma.ttf`、`system.ttf` 等）。
- **自动化注册表字体链接**：启动时自动在 `user.reg` 和 `system.reg` 中注入 `FontLink\SystemLink`、`FontSubstitutes` 与 `Wine\Fonts\Replacements`，将 Tahoma、宋体、微软雅黑等映射至内置 CJK 字体。
- **全局生效**：完美解决 iOS / iPadOS 18+ 环境下因沙盒限制导致注册表编辑器（`regedit.exe`）、配置程序、安装器向导、弹出对话框以及中文 PC 游戏中文字符全部变成方块（豆腐块）的问题。

### 2. 📱 iPad 大屏适配与状态栏安全区避让
- **顶部防碰撞间距**：自动识别 iPad 设备，在 Wine 会话及游戏运行界面动态保留至少 24pt 的安全区上边距（Safe Area Top Margin）。
- **杜绝遮挡系统状态栏**：彻底解决 iPad 顶部状态栏（StikDebug 返回药丸按钮、时间、电量、VPN 状态）与 Wine 窗口顶栏、标题栏及窗口控制按钮（最小化、最大化、关闭 `_ [] X`）重叠遮挡、无法点击的问题。
- **主界面重构**：修复游戏库主界面左上角 Big Picture 切换按钮与 Madeira / iDeck 标题的文字碰撞重叠。

### 3. 🌐 HTTP & SOCKS5 全栈双层网络代理
- **集中化设置面板**：在应用设置（Settings）中新增专门的“网络代理 (Network Proxy)”配置模块，支持随时切换 **HTTP** 或 **SOCKS5** 协议，并自由配置代理 Host 与 Port。
- **细粒度双独立开关**：
  - **应用本体代理 (App Native Proxy)**：配置 iOS 原生 `URLSessionConfiguration.connectionProxyDictionary`，覆盖 Steam Guard 账号登录验证、Steam Cloud 云存档实时同步、DepotDownloader 游戏文件高速下载以及游戏封面与元数据拉取。
  - **Wine 与 Steam 内部代理 (Wine & Steam Proxy)**：
    - **CEF 网页组件**：为 `steamwebhelper.exe` 自动注入 `-proxy-server="protocol://host:port"` 命令行参数，使 Steam 商店、个人主页、社区、创意工坊在受限网络环境下畅快访问。
    - **Windows 注册表**：自动向 `Internet Settings` 写入 `ProxyEnable=1` 与 `ProxyServer`，覆盖 WinINet 依赖程序。
    - **POSIX 环境变量**：向底层环境注入 `http_proxy`、`https_proxy`、`all_proxy`。
- **支持多代理来源**：完美兼容本机后台运行的代理工具（Shadowsocks / Surge / Loon 等本地回环 `127.0.0.1`）以及局域网旁路网关（如 `192.168.x.x`）。

### 4. 🚀 游戏库主视图与轻量桌面启动模式
- **默认进入游戏库**：启动应用后默认展示原生游戏库界面（Library View），无需每次忍受重度 Big Picture 界面的初始化等待。
- **桌面模式轻量启动**：新增桌面模式启动 Steam，相比传统全屏 Big Picture 大幅缩减内存开销与渲染负担。
- **全向导航与诊断**：在系统诊断、Wine 调试与游戏库之间无缝切换，不再发生视图卡死。

### 5. ⚙️ GitHub Actions 自动化 CI/CD 构建
- **自增版本号**：基于基础偏移值 + GitHub Actions 每次运行的 `run_number`，全自动递增 `CURRENT_PROJECT_VERSION`。
- **开箱即用的构建产物**：每次推送到分支均自动编译出带 short_sha 标识的 IPA 安装包（如 `iDeck-fork-<sha>.ipa`）。

---

## 安装与使用指南

### 环境要求
- **设备**：运行 iOS/iPadOS 17+ 或 18+ 的 iPhone / iPad（对于 3D 游戏，推荐 A17 Pro 或 M1 芯片及以上设备）。
- **JIT 编译权限**：通过 [StikDebug](https://github.com/stikdebug/stikdebug)、内置 StikJIT、SideStore JIT 或 AltStore 启用。
- **侧载签名工具**：[SideStore](https://sidestore.io/)、[AltStore](https://altstore.io/)、[Sideloadly](https://sideloadly.io/) 或 Xcode。

### 详细步骤

1. **下载 IPA**：
   - 前往 [GitHub Actions Artifacts](https://github.com/LxnChan/iDeck/actions) 或 Releases 页面下载最新构建生成的 IPA 文件。
2. **签名并安装**：
   - 使用你常用的签名工具（个人免费开发者证书即可）完成签名安装。
   - **注意**：必须同时保留并对 `MadeiraJITHelper.appex` 扩展进行签名，并确保勾选允许调试权限（`get-task-allow`）。
3. **启用 JIT**：
   - 首次启动前或打开应用后，通过 StikDebug（配对并连接 LocalDevVPN）或 SideStore 菜单激活 JIT。
4. **配置网络代理（可选，国内/受限网络推荐）**：
   - 点击主界面齿轮图标进入 **Settings**。
   - 在 **Network Proxy** 分组中开启总开关，选择 **HTTP** 或 **SOCKS5**。
   - 输入代理服务器 IP（如本机运行则为 `127.0.0.1`，内网代理则填写如 `192.168.31.2`）与端口。
   - 按需勾选 **App Native Proxy** 与 **Wine & Steam Proxy**。

---

## 启动 Steam 前置检查清单

初次使用时，点击主界面或设置中的 **Check all prerequisites（检查前置条件）**：

| 步骤 | 检查项目 | 说明与操作 |
| --- | --- | --- |
| 1 | **Local Runtime（本地运行时）** | 点击 **Prepare runtime** 初始化 Wine 环境并解压核心组件（本版本已自带全部 CJK 中文字体）。 |
| 2 | **Steam Client（Steam 文件）** | 在指定 Wine 路径（`wine/drive_c/Steam32BundleLab` 或 `wine/drive_c/Steam32Lab`）放入兼容的 Windows Steam 文件。 |
| 3 | **Development Signing（开发签名）** | 检查当前安装包是否具有调试权限，缺少需使用有效配置描述文件重新签名。 |
| 4 | **JIT Setup（JIT 授权）** | 配对 StikDebug 并连接 LocalDevVPN，使 FEX 转译引擎能够动态生成 ARM64 代码。 |
| 5 | **Launch Steam** | 所有准备项亮起绿灯后，点击 **Launch Steam Big Picture** 或进入桌面模式启动。 |

---

## 从源码构建

```sh
# 递归拉取子模块克隆仓库
git clone --recurse-submodules https://github.com/LxnChan/iDeck.git
cd iDeck
```

使用 Xcode 打开 `app/Madeira.xcodeproj`：
1. 选择 Scheme 为 `Madeira`。
2. 在 **Signing & Capabilities** 中选择你自己的 Apple 开发者账号与 Team。
3. 连接 iOS / iPadOS 设备，点击 Run 进行编译安装。

深入阅读参考文档：
- [快速入门文档 (英文)](docs/GETTING_STARTED.md)
- [构建详细指南 (英文)](docs/BUILDING.md)
- [JIT 配置与排错指南 (英文)](docs/JIT.md)
- [分发要求与合规声明 (英文)](docs/DISTRIBUTION.md)

---

## 社区交流与反馈

- **项目讨论**：欢迎加入 [iDeck 官方 Discord 社区](https://discord.gg/aQdsaJyTM) 或 [Madeira Discord 社区](https://discord.gg/4t5mNjwCn7)。
- **提交 Issue**：若发现 Bug 或兼容性问题，欢迎在 GitHub 上提交 Issue，请务必附带你的设备型号、系统版本号、构建号以及脱敏后的运行日志。

---

## 致谢与开源许可

- **Madeira**：感谢 Will Faust 及其贡献者构建了整个底层架构、图形驱动集成（DXMT）与 iOS 运行时。
- **上游生态**：致谢 Wine、FEX-Emu、DXMT、StikDebug / StikJIT、idevice 等优秀上游开源工程。
- **设计启发**：[DroidDeck](https://github.com/Droid-Deck/DroidDeck)。
- **开源许可证**：iDeck 新增代码遵循 **GPL-3.0-or-later** 许可证，上游各模块保留原有许可证（包括 LGPL、MIT、BSD、MPL 等），详见 [COPYING](COPYING)、[CREDITS.md](CREDITS.md) 及 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

*免责声明：Steam、SteamOS、Steam Big Picture 及 Steam Deck 均为 Valve Corporation 的商标或注册商标。iPhone、iPad、iOS、iPadOS 与 Metal 均为 Apple Inc. 的商标。iDeck 是独立的开源技术研究项目，与 Valve Corporation 或 Apple Inc. 无任何关联或官方背书。*
