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
  <a href="https://github.com/LxnChan/iDeck/actions"><img src="https://img.shields.io/badge/构建状态-GitHub%20Actions-brightgreen?logo=github-actions" alt="构建状态"></a>
  <a href="docs/GETTING_STARTED.md"><img src="https://img.shields.io/badge/Platform-iOS%20%26%20iPadOS%2017%2B-007AFF" alt="iOS 与 iPadOS 平台"></a>
  <a href="docs/IDECK.md"><img src="https://img.shields.io/badge/Status-活跃维护中-success" alt="开发状态"></a>
  <a href="https://github.com/willfaust/Madeira"><img src="https://img.shields.io/badge/Powered%20by-Madeira%20%2B%20Wine%20%2B%20FEX-28C7D9" alt="底层动力: Madeira"></a>
  <a href="COPYING"><img src="https://img.shields.io/badge/License-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later"></a>
</p>

把手柄接上，打开 Steam 游戏库，给积灰的游戏一个住进兜里的机会。
iDeck 通过 **Madeira、Wine、FEX-Emu、DXMT 和 Metal**，在 iPhone 与 iPad 本地运行 Valve 真正的 Windows Steam 客户端（包含大屏幕模式 Big Picture 与标准普通桌面模式），以及部分兼容的 Windows PC 游戏，**无需从任何电脑远程串流**。

> [!TIP]
> ### 📦 快速下载预编译 IPA（来人指路）
> 您不需要配有 Mac 电脑或 Xcode 即可畅玩！GitHub Actions 会在每次代码推送后全自动编译最新功能的 IPA 安装包：
> 1. 点击进入 [**GitHub Actions 构建页面**](https://github.com/LxnChan/iDeck/actions?query=workflow%3A%22Build+iDeck+IPA%22+is%3Asuccess)；
> 2. 点击列表顶部**最新一条带有绿色对勾 ✅ 的构建记录（`Build iDeck IPA`）**；
> 3. 滑动至页面最下方的 **Artifacts（构建产物）** 区域；
> 4. 点击下载 **`iDeck-fork-<sha>`** 压缩包，解压后即可获得编译完成、可直接签名的 IPA 文件（`iDeck-fork-*.ipa`）。
> *(注：下载 GitHub Artifacts 需要先登录 GitHub 账号)*。

<p align="center">
  <img src="docs/assets/ideck/demo-landscape-ccw90-1.5x.gif" width="831" alt="iPhone 本地启动 Steam 与 PC 游戏的演示，1.5 倍速">
  <br><sub>真机演示 · 1.5 倍速 · 实验构建</sub>
</p>

---

## 本分支（Fork）核心新增特性与改进

### 1. 🈲 完整 CJK / 中文字体支持（彻底告别豆腐块 `□□□□` 乱码）
- **宋体（`simsun.ttc`）与微软雅黑（`msyh.ttc`）双正版内置**：开箱即用打包完整的 Windows 宋体/新宋体（18.3 MB）以及微软雅黑/微软雅黑 UI（19.7 MB）TrueType 字库。
- **解决编辑框英文字母变框框**：彻底修复经典 GDI 编辑框（如“运行”对话框 Edit 控件）中输入英文字母变成方块框框的问题。
- **解决 Steam 中文界面与登录框方块问题**：Steam 的 VGUI2 与 CEF DirectWrite 现代渲染引擎在中文语言下强制要求 `Microsoft YaHei`。内置正版 `msyh.ttc` 并在注册表 `[Fonts]` 中正式注册后，彻底消除了 Steam 登录框、客户端商店和好友列表中的中文乱码与字形缺失（`▯` 框框）。
- **自动化注册表字体链接**：启动时自动注入 `FontLink\SystemLink`，将 `Segoe UI`、`Tahoma`、`Arial`、`Lucida Sans`、`MS Sans Serif` 等西文字体的中文字形优先链入 `msyh.ttc` 与 `simsun.ttc`。

### 2. 📱 iPad 沉浸式真全屏（零黑边）与磨砂导航栏
- **消除 iPad 顶部双重内边距 Bug**：彻底修复了原版针对 iPad 进行双重 Inset 边距计算导致顶部多出 48pt+ 宽黑边的历史遗留问题。
- **会话画面全屏展开**：进入 Wine 会话与游戏时直接生效 `.ignoresSafeArea(edges: .all)` 与 `.statusBarHidden(true)`，让 iPad 与 iPhone 一样画面完全铺满屏幕。浮动 HUD 菜单按钮（`≡`）自动贴合顶部边缘，整洁清爽。
- **顶部半透明毛玻璃材质**：游戏库主界面顶栏与搜索栏引入系统级半透明磨砂玻璃材质（`UIBlurEffect(style: .systemMaterial)`），滑动游戏列表时文字与海报不再产生透光重叠穿透。

### 3. 🖱️ 鼠标指针体验与长按延迟自定义
- **Absolute 模式长按响应时间减半**：将绝对鼠标模式下的单指长按拖拽阈值从原版的 `0.5s` 缩短为 `0.25s`，拖动窗口或长按选择更干脆灵敏。
- **设置页与 HUD 自定义滑块**：在“设置 → 指针 (Pointer)”以及游戏内 HUD 悬浮层中新增了长按时间调节滑块（`0.15s` – `0.60s`，步长 `0.05s`），自由随心定制手感并持久化存储。

### 4. 🚀 主页三入口并排布局与按需按量加载
- **顶部横向胶囊三并排**：
  - **`Desktop`**：启动 Wine 桌面环境与文件管理器。
  - **`Steam Launcher`**：普通桌面模式（极轻量运行 32 位 Windows 原生 Steam，省去大屏 CEF 渲染开销）。
  - **`Steam Big Picture Mode`**：全功能手柄大屏模式（带 `-bigpicture` 参数的全屏 Gamepad UI）。
- **长按直接启动与手柄导航**：长按任意 Steam 按钮弹出菜单可直接一键启动对应模式；手柄十字键左右切换焦点（Cyan 边框高亮）与确认。
- **设置页专用独立控制**：设置页新增独立的 **Steam 客户端 (Steam Client)** 设置专区，方便快速配置默认启动模式。
- **“未安装”列表默认折叠与按需拉取**：主页“Not installed”分组默认保持收起，在收起状态下彻底阻断任何封面请求，极大降低网络带宽占用与内存压力。

### 5. 🌐 HTTP & SOCKS5 全栈双层网络代理
- **集中化设置面板**：在应用设置（Settings）中新增专门的“网络代理 (Network Proxy)”配置模块，支持随时切换 **HTTP** 或 **SOCKS5** 协议，并自由配置代理 Host 与 Port。
- **细粒度双独立开关**：
  - **应用本体代理 (App Native Proxy)**：配置 iOS 原生 `URLSessionConfiguration.connectionProxyDictionary`，覆盖 Steam Guard 账号登录验证、Steam Cloud 云存档实时同步、DepotDownloader 游戏文件高速下载以及游戏封面与元数据拉取。
  - **Wine 与 Steam 内部代理 (Wine & Steam Proxy)**：
    - **CEF 网页组件**：为 `steamwebhelper.exe` 自动注入 `-proxy-server="protocol://host:port"` 命令行参数，使 Steam 商店、个人主页、社区、创意工坊在受限网络环境下畅快访问。
    - **Windows 注册表**：自动向 `Internet Settings` 写入 `ProxyEnable=1` 与 `ProxyServer`，覆盖 WinINet 依赖程序。
    - **POSIX 环境变量**：向底层环境注入 `http_proxy`、`https_proxy`、`all_proxy`。
- **支持多代理来源**：完美兼容本机后台运行的代理工具（Shadowsocks / Surge / Loon 等本地回环 `127.0.0.1`）以及局域网旁路网关（如 `192.168.x.x`）。

### 6. ⚙️ GitHub Actions 自动化 CI/CD 构建
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
   - 前往 [**GitHub Actions 构建流水线**](https://github.com/LxnChan/iDeck/actions?query=workflow%3A%22Build+iDeck+IPA%22+is%3Asuccess)；
   - 点击最新一条带有绿色对勾 ✅ 的构建记录（`Build iDeck IPA`）；
   - 在底部的 **Artifacts** 处下载 **`iDeck-fork-<sha>`**，解压即可提取出最新的 IPA 安装包。
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
| 1 | **Local Runtime（本地运行时）** | 点击 **Prepare runtime** 初始化 Wine 环境并解压核心组件（本版本已自带完整 CJK 中文字体集，包括宋体与微软雅黑）。 |
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
