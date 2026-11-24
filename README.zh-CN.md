[English](README.md) · [简体中文](README.zh-CN.md)

<p align="center">
  <img src="docs/assets/ideck/icon.png" width="156" alt="iDeck">
</p>
<h1 align="center">iDeck</h1>
<p align="center"><strong>在 iOS 与 iPadOS 上体验 Steam 与 Windows PC 游戏</strong><br>主要面向 iPad、iPhoneDuo 等大屏机型的本地 PC 游戏体验。</p>
<p align="center">
  <a href="https://github.com/LxnChan/iDeck/actions"><img src="https://img.shields.io/badge/构建状态-GitHub%20Actions-brightgreen?logo=github-actions" alt="构建状态"></a>
  <a href="docs/GETTING_STARTED.md"><img src="https://img.shields.io/badge/Platform-iOS%20%26%20iPadOS%2017%2B-007AFF" alt="iOS 与 iPadOS 平台"></a>
  <a href="docs/IDECK.md"><img src="https://img.shields.io/badge/Status-活跃维护中-success" alt="开发状态"></a>
  <a href="https://github.com/willfaust/Madeira"><img src="https://img.shields.io/badge/Powered%20by-Madeira%20%2B%20Wine%20%2B%20FEX-28C7D9" alt="底层动力: Madeira"></a>
  <a href="COPYING"><img src="https://img.shields.io/badge/License-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later"></a>
</p>

iDeck 通过 **Madeira、Wine、FEX-Emu、DXMT 和 Metal**，在设备本地运行 Valve 的 Windows Steam 客户端（包含大屏幕模式 Big Picture 与普通桌面模式），以及部分兼容的 Windows PC 游戏，**无需从任何电脑远程串流**。项目主要面向 **iPad、iPhoneDuo 等大屏机型**，围绕桌面布局、外接键鼠、实体手柄与触控操作进行适配。

项目仍处于实验阶段。设备、系统版本、签名/JIT 配置及具体游戏都会影响兼容性；上述设备定位不代表所有机型或游戏均已通过真机验证。

> [!IMPORTANT]
> 本仓库是包含独立修改的分支。使用本仓库编译的 IPA（包括 GitHub Actions 产物及本地编译版本）产生的问题，**仅向 [LxnChan/iDeck Issues](https://github.com/LxnChan/iDeck/issues) 反馈**。请勿向上游 iDeck、Madeira 或其他上游仓库及社群提交相关 Issue、求助或本分支构建的日志。上游维护者不负责支持本分支的构建。

> [!TIP]
>
> ### 📦 快速下载预编译 IPA（来人指路）
>
> 下载预编译 IPA 不需要 Mac 或 Xcode。向 `main` 推送代码/构建配置变更，或手动启动工作流后，GitHub Actions 会生成待签名的 IPA 安装包：
>
> 1. 点击进入 [**GitHub Actions 构建页面**](https://github.com/LxnChan/iDeck/actions?query=workflow%3A%22Build+iDeck+IPA%22+is%3Asuccess)；
> 2. 打开 **Build iDeck IPA** 工作流最新一条成功的构建记录。记录标题描述具体修改，例如 `fix(app): preserve JIT connections and improve download controls`；
> 3. 滑动至页面最下方的 **Artifacts（构建产物）** 区域；
> 4. 点击下载 **`iDeck-fork-<sha>`** 压缩包，解压后即可获得编译完成、可直接签名的 IPA 文件（`iDeck-fork-*.ipa`）。
> 5. 普通安装**不需要下载另外的 `-source` 与 `-relink` 产物**：它们分别是对应源码包和重链接材料，不是应用运行所需的额外资源。每个下载项均附带独立的 SHA-256 校验文件。
>
> *(注：下载 GitHub Artifacts 需要先登录 GitHub 账号)*。
>
> 构建产物保留 **14 天**；如需长期使用，请及时下载并保存到本地。

---

## 主要功能与近期更新

### 1. 🈲 完整 CJK / 中文字体支持（彻底告别豆腐块 `□□□□` 乱码）

- **宋体（`simsun.ttc`）与微软雅黑（`msyh.ttc`）双正版内置**：开箱即用打包完整的 Windows 宋体/新宋体（18.3 MB）以及微软雅黑/微软雅黑 UI（19.7 MB）TrueType 字库。
- **解决编辑框英文字母变框框**：彻底修复经典 GDI 编辑框（如“运行”对话框 Edit 控件）中输入英文字母变成方块框框的问题。
- **解决 Steam 中文界面与登录框方块问题**：Steam 的 VGUI2 与 CEF DirectWrite 现代渲染引擎在中文语言下强制要求 `Microsoft YaHei`。内置正版 `msyh.ttc` 并在注册表 `[Fonts]` 中正式注册后，彻底消除了 Steam 登录框、客户端商店和好友列表中的中文乱码与字形缺失（`▯` 框框）。
- **自动化注册表字体链接**：启动时自动注入 `FontLink\SystemLink`，将 `Segoe UI`、`Tahoma`、`Arial`、`Lucida Sans`、`MS Sans Serif` 等西文字体的中文字形优先链入 `msyh.ttc` 与 `simsun.ttc`。

### 2. 📱 大屏布局、iPad 状态栏 HUD 与系统菜单

- **重新整理会话布局**：消除顶部重复边距，保留 iPad 顶部状态栏区域，游戏/桌面画面填满其余可用空间；右上角浮动菜单按钮保持可见、可操作。
- **iPad 资源监测 HUD**：可在顶部状态栏居中显示 CPU、GPU、内存、帧率和温控状态，游戏内菜单提供 iPad 专用开关；资源指标不再与滚动日志混排。
- **系统菜单集成**：在支持系统菜单的环境下提供 File、View、Help 菜单，包含添加自定义游戏、Desktop、两种 Steam 启动入口及 About，并为常用操作提供键盘快捷键。
- **顶部半透明毛玻璃材质**：游戏库主界面顶栏与搜索栏引入系统级半透明磨砂玻璃材质（`UIBlurEffect(style: .systemMaterial)`），滑动游戏列表时文字与海报不再产生透光重叠穿透。

### 3. 🖱️ 外接鼠标、触控操作与指针锁定

- **独立 Mouse 模式**：将外接鼠标操作与触控板/Crosshair 触控模式区分，支持独立鼠标灵敏度和 iPad 指针锁定设置；可通过 **Ctrl+Alt+P** 切换指针锁定。
- **点击路由与输入顺序修复**：修复鼠标点击丢失或间歇失效、原始输入与系统指针重复上报、指针跳变及按下/松开乱序问题；AssistiveTouch 状态切换后会自动更新兼容点击处理，无需重启应用。
- **触控与 Crosshair 手势**：恢复触控点击、拖拽及 Crosshair 手势，与硬件输入协同工作；打开菜单、切换模式或应用失去焦点时释放已按住的输入。
- **缩短长按响应时间**：触控板与 Crosshair 操作的默认静止长按阈值为 `0.25s`，用于拖拽和持续按住输入。
- **设置页与 HUD 自定义滑块**：在“设置 → 指针 (Pointer)”以及游戏内 HUD 悬浮层中新增了长按时间调节滑块（`0.15s` – `0.60s`，步长 `0.05s`），自由随心定制手感并持久化存储。
- **配置与验证范围**：iPhone 的 AssistiveTouch 要求、输入设置及真机验证边界见[键盘、鼠标与触控板说明](docs/KEYBOARD_MOUSE.md)。

### 4. 🚀 主页三入口并排布局与按需按量加载

- **顶部横向胶囊三并排**：
  - **`Desktop`**：启动 Wine 桌面环境与文件管理器。
  - **`Steam Launcher`**：普通桌面模式（极轻量运行 32 位 Windows 原生 Steam，省去大屏 CEF 渲染开销）。
  - **`Steam Big Picture Mode`**：全功能手柄大屏模式（带 `-bigpicture` 参数的全屏 Gamepad UI）。
- **长按直接启动与手柄导航**：长按任意 Steam 按钮弹出菜单可直接一键启动对应模式；手柄十字键左右切换焦点（Cyan 边框高亮）与确认。
- **设置页专用独立控制**：设置页新增独立的 **Steam 客户端 (Steam Client)** 设置专区，方便快速配置默认启动模式。
- **“未安装”列表默认折叠与按需拉取**：主页“Not installed”分组默认保持收起，在收起状态下彻底阻断任何封面请求，极大降低网络带宽占用与内存压力。
- **Steam 响应优化**：Steam 会话期间暂停隐藏日志渲染和不必要的诊断采样；Steam 菜单辅助逻辑复用已有客户端窗口，避免重复拉起客户端。

### 5. 🌐 HTTP & SOCKS5 全栈双层网络代理

- **集中化设置面板**：在应用设置（Settings）中新增专门的“网络代理 (Network Proxy)”配置模块，支持随时切换 **HTTP** 或 **SOCKS5** 协议，并自由配置代理 Host 与 Port。
- **细粒度双独立开关**：
  - **应用本体代理 (App Native Proxy)**：配置 iOS 原生 `URLSessionConfiguration.connectionProxyDictionary`，覆盖 Steam Guard 账号登录验证、Steam Cloud 云存档实时同步、DepotDownloader 游戏文件高速下载以及游戏封面与元数据拉取。
  - **Wine 与 Steam 内部代理 (Wine & Steam Proxy)**：
    - **CEF 网页组件**：为 `steamwebhelper.exe` 自动注入 `-proxy-server="protocol://host:port"` 命令行参数，使 Steam 商店、个人主页、社区、创意工坊在受限网络环境下畅快访问。
    - **Windows 注册表**：自动向 `Internet Settings` 写入 `ProxyEnable=1` 与 `ProxyServer`，覆盖 WinINet 依赖程序。
    - **POSIX 环境变量**：向底层环境注入 `http_proxy`、`https_proxy`、`all_proxy`。
- **支持多代理来源**：完美兼容本机后台运行的代理工具（Shadowsocks / Surge / Loon 等本地回环 `127.0.0.1`）以及局域网旁路网关（如 `192.168.x.x`）。
- **Steam 连通性反馈**：设置页提供 **Steam Connect** 状态与延迟指示；代理连通性检查失败时会询问是否关闭代理，不会静默修改设置。

### 6. 🎙️ 麦克风映射与蓝牙音频

- **可选麦克风输入**：游戏配置中的 **Microphone mapping** 开关可在获得录音权限后，将设备麦克风映射给 Windows 应用。
- **蓝牙输出路由**：优先使用设备内置麦克风，同时允许蓝牙 A2DP 立体声播放；实际音频路由和游戏语音效果仍取决于设备与应用。

### 7. 🔧 与源码匹配的 FEX、Wine 和 DXMT 运行时

- **协同更新运行时**：对齐 Madeira 选定的 iOS 分支 FEX、Wine、DXMT 版本，补齐对应原生桥接接口，并重建 Windows PE 运行时；这是固定版本的同步，不代表合入各项目主线的全部最新修改。
- **打包完整性检查**：记录组件版本、补丁/输入哈希及实际打包文件；CI 在上传前检查必需模块、架构和文件内容，并使用实际链接输入执行可移植重链接命令。
- **验证边界**：构建和打包检查不等同于游戏兼容性验证。反复退出游戏、Unity/Mono、WoW64 与 D3D9/11 等真机检查仍待完成，具体版本和已知缺口见[运行时同步说明](docs/RUNTIME_SYNC.md)。

### 8. ⚙️ GitHub Actions 自动构建、分层缓存与独立下载

- **自增版本号**：基于基础偏移值 + GitHub Actions 每次运行的 `run_number`，全自动递增 `CURRENT_PROJECT_VERSION`。
- **按输入范围划分缓存**：依赖库、Wine 头文件/宿主工具、原生运行时库和 Windows 运行时分别按相关输入与工具链身份缓存。仅修改应用或上传工作流时可复用匹配的运行时缓存；冷缓存或强制重建仍需编译相应组件。
- **三个独立下载项**：`iDeck-fork-<sha>` 包含 IPA、文件清单、运行时清单及校验文件；`iDeck-fork-<sha>-source` 与 `iDeck-fork-<sha>-relink` 分别提供匹配的源码和重链接包。普通安装只需第一个。
- **交付前失败检查**：运行时素材不完整、prefix 模板无效、IPA 或清单缺失/为空时，工作流会失败，不再将不完整产物当作成功构建提供下载。

### 9. JIT 配置、复用现有 VPN 与 DDI 恢复

- **JIT 方式**：通过 iDeck 的 **Enable JIT** 流程使用 StikDebug 或内置 StikJIT。Automatic 模式优先选择已安装的 StikDebug，否则使用内置辅助扩展。内置 JIT 需要 iOS/iPadOS 26 及以上真机、正确签名的辅助扩展及本机配对文件；应用内配对需要 iOS/iPadOS 27 及以上。
- **保留可用连接**：JIT 已就绪时跳过网络准备；当前 VPN 若能提供并通过本地调试端点（`10.7.0.1:62078`）验证，也不会自动切换到 LocalDevVPN。LocalDevVPN 仍可作为备用方案，普通 VPN 或 HTTP/SOCKS5 代理不代表已满足调试连接要求。
- **DDI 准备与恢复**：内置 JIT 在启动调试器连接计时前，先下载并校验 Developer Disk Image。准备失败时显示出错阶段，并可替换缓存、重新下载 DDI。DDI 下载可使用应用本体的下载代理，但代理不能代替本地调试连接。
- **验证边界**：自动化检查覆盖服务验证、无效响应和超时；其他 VPN 实现仍需真机验证。详见 [JIT 配置说明](docs/JIT.md)。

### 10. 并发下载、恢复校验与屏幕常亮

- **分块并发下载**：共享 Steam 下载器已支持最多 **8 个分块并发下载**，包含校验、重试和断点记录；队列中的游戏仍逐个安装。
- **CDN 发现与重试**：区域 Steam 目录返回的可用 HTTPS 节点不足时，会追加查询其他 cell，并接受 Steam 返回的合法合作 CDN 域名。最多 6 个节点的池中保留备用节点；每个分块先尝试不同节点，再重复尝试，总计最多 5 次，满 6 节点时为 6 次。日志区分节点排除原因、HTTP 状态及具体网络错误码。重试耗尽后停止下载；Resume 保留已完成分块并重新发现节点。
- **校验完成后再恢复**：外置存储重新连接后，校验已下载文件期间禁用 **Resume**、重试及恢复更新按钮，并显示黄色叹号与正在校验的提示；检查结束后显示校验结果。
- **下载时保持常亮**：**Settings → Steam → Keep screen awake while downloading** 默认开启，偏好持久保存，修改即时生效。它会在应用处于前台且下载进行时阻止自动锁屏；暂停、完成或失败后释放下载的常亮占用，不影响仍显示中的游戏画面自身的常亮需求。
- **后台限制**：iOS/iPadOS 26 及以上会申请持续后台处理；系统终止任务时，下载会安全暂停；若系统拒绝申请，则退回短暂的后台宽限时间，结束后再暂停。已完成分块会保留，应用恢复活跃后继续下载。手动锁屏或切换应用仍受 iOS 限制；常亮开关不保证后台下载始终不中断，也不能防止外置存储断连。详见 [Steam 游戏库与下载说明](docs/STEAM_LIBRARY.md)。

### 11. 外置游戏存储与 Steam 游戏库

- **授权外置目录**：进入 **Settings → Storage → External storage → Add or reauthorize folder**，通过“文件”选择已连接的本地外置存储上的可写目录。游戏文件留在外置存储中，通过 `C:\External\<folder-id>` 访问；应用会保存目录授权以供重新连接。
- **使用已有游戏和游戏库**：普通 Windows 游戏可通过程序浏览器中的 `drive_c/External/<folder-id>` 添加；Steam 游戏库使用所选目录下的 `steamapps`，自动发现其中已有的安装清单，并将外置游戏库注册到 Windows Steam 客户端。
- **选择下载位置**：可在外置存储设置中指定新 Steam 下载的全局默认位置，也可在单个游戏的安装页面选择内置存储或已连接的外置目录，且不改变全局默认。已排队、未完成的下载、更新与修复会保留原安装位置；外置存储不可用时不会静默改存到内置存储。剩余空间按实际目标磁盘显示。
- **连接状态反馈**：游戏库的外置磁盘图标用绿色、黄色、红色分别表示已连接、部分连接和不可用。设置页显示各目录的可用状态、剩余空间，并提供 **Check connected folders** 检查操作。外置存储不可用时保留游戏条目与设置，游戏卡片置灰，恢复访问前禁止启动。
- **下载中断恢复**：磁盘断连会停止受影响的下载；重新连接原可写目录后自动校验已下载文件，期间禁用 Resume 并显示黄色校验提示。恢复时验证并修复缺失或损坏的分块，不会仅凭旧进度记录认为文件完整。
- **安全断开与重新授权**：先停止游戏、下载和存档同步，再点 **Safely disconnect**，最后拔出设备。**Reconnect** 使用已保存授权；若权限失效，重新选择原目录即可保留游戏路径。**Remove mapping** 只移除映射，不删除外置文件。
- **存储边界**：该功能是目录映射，不会合并磁盘容量，也不会自动迁移已有的内置安装。Windows 系统文件和用户目录仍位于内置存储；保存在外置游戏目录旁的存档仍依赖该磁盘。Steam Cloud 会将磁盘不可用视为访问失败，而非存档已删除。运行游戏或写入期间拔盘仍可能中断游戏、丢失未保存数据，具体设备兼容性仍需真机验证。配置、恢复和限制详见[外置游戏存储说明](docs/EXTERNAL_STORAGE.md)。

---

## 安装与使用指南

### 环境要求

- **设备**：主要面向 **iPad、iPhoneDuo 等大屏机型**，需满足兼容的 iOS/iPadOS 17+ 运行环境。3D 游戏推荐 A17 Pro 或 M1 芯片及以上设备，但硬件规格本身不保证游戏兼容性。
- **JIT 编译权限**：通过 iDeck 的 **Enable JIT** 流程使用 [StikDebug](https://github.com/stikdebug/stikdebug) 或内置 StikJIT，并完成相应的开发签名与配对。内置 JIT 需要 iOS/iPadOS 26+，应用内配对需要 27+；仅有已调试标记，不代表准备 JIT 内存所需的调试器连接已就绪。
- **侧载签名工具**：[SideStore](https://sidestore.io/)、[AltStore](https://altstore.io/)、[Sideloadly](https://sideloadly.io/) 或 Xcode。

### 详细步骤

1. **下载 IPA**：
   - 前往 [**GitHub Actions 构建流水线**](https://github.com/LxnChan/iDeck/actions?query=workflow%3A%22Build+iDeck+IPA%22+is%3Asuccess)；
   - 打开 **Build iDeck IPA** 工作流最新一条带绿色对勾的记录，标题会显示本次构建对应的修改；
   - 在底部的 **Artifacts** 处下载 **`iDeck-fork-<sha>`**，解压即可提取出最新的 IPA 安装包。
   - 安装时使用其中的 `.ipa`，无需下载另外的 `-source` 与 `-relink` 产物。
2. **签名并安装**：
   - 使用你常用的签名工具（个人免费开发者证书即可）完成签名安装。
   - **注意**：必须同时保留并对 `MadeiraJITHelper.appex` 扩展进行签名，并确保勾选允许调试权限（`get-task-allow`）。
3. **启用 JIT**：
   - 进入 **Settings → JIT → JIT setup**，选择 JIT 方式，并按对应方式完成配对或导入本机配对文件。
   - 确保本地调试连接可用，然后在 iDeck 中点击 **Enable JIT**。已验证的兼容 VPN 可以提供该连接；连接已可用或 JIT 已就绪时，不强制使用 LocalDevVPN。
   - 内置方式若提示 Developer Disk Image 问题，可使用 DDI 恢复操作；要求与排错方法见 [JIT 配置说明](docs/JIT.md)。
4. **配置网络代理（可选，国内/受限网络推荐）**：
   - 点击主界面齿轮图标进入 **Settings**。
   - 在 **Network Proxy** 分组中开启总开关，选择 **HTTP** 或 **SOCKS5**。
   - 输入代理服务器 IP（如本机运行则为 `127.0.0.1`，内网代理则填写如 `192.168.31.2`）与端口。
   - 按需勾选 **App Native Proxy** 与 **Wine & Steam Proxy**。
5. **使用外置存储（可选）**：
   - 连接外置存储后，进入 **Settings → Storage → External storage → Add or reauthorize folder**，在“文件”中选择可写目录。
   - 将其设为新 Steam 下载的默认位置、在单个游戏安装页选择该位置，或通过 `C:\External\<folder-id>` 浏览已有游戏。
   - 拔出前先停止游戏、下载与存档同步，再使用 **Safely disconnect**。详见[外置游戏存储说明](docs/EXTERNAL_STORAGE.md)。

---

## 启动 Steam 前置检查清单

初次使用时，点击主界面或设置中的 **Check all prerequisites（检查前置条件）**：

| 步骤 | 检查项目 | 说明与操作 |
| --- | --- | --- |
| 1 | **Local Runtime（本地运行时）** | 点击 **Prepare runtime** 初始化 Wine 环境并解压核心组件（本版本已自带完整 CJK 中文字体集，包括宋体与微软雅黑）。 |
| 2 | **Steam Client（Steam 文件）** | 在指定 Wine 路径（`wine/drive_c/Steam32BundleLab` 或 `wine/drive_c/Steam32Lab`）放入兼容的 Windows Steam 文件。 |
| 3 | **Development Signing（开发签名）** | 检查当前安装包是否具有调试权限，缺少需使用有效配置描述文件重新签名。 |
| 4 | **JIT Setup（JIT 授权）** | 通过 iDeck 的 Enable JIT 使用 StikDebug 或内置 StikJIT；JIT 尚未就绪时需提供兼容的本地调试连接，LocalDevVPN 是其中一种方案。 |
| 5 | **Launch Steam** | 所有准备项亮起绿灯后，点击 **Launch Steam Big Picture** 或进入桌面模式启动。 |

---

## 从源码构建

```sh
# 递归拉取子模块克隆仓库
git clone --recurse-submodules https://github.com/LxnChan/iDeck.git
cd iDeck
```

新克隆的源码不包含已编译的运行时库和配套资源。请先参考[运行时同步说明](docs/RUNTIME_SYNC.md)与[构建指南](docs/BUILDING.md)准备所需输入，仅克隆仓库不足以完成完整构建。

使用 Xcode 打开 `app/Madeira.xcodeproj`：

1. 选择 Scheme 为 `Madeira`。
2. 在 **Signing & Capabilities** 中选择你自己的 Apple 开发者账号与 Team。
3. 连接 iOS / iPadOS 设备，点击 Run 进行编译安装。

深入阅读参考文档：
- [快速入门文档 (英文)](docs/GETTING_STARTED.md)
- [构建详细指南 (英文)](docs/BUILDING.md)
- [JIT 配置与排错指南 (英文)](docs/JIT.md)
- [外置游戏存储与恢复说明 (英文)](docs/EXTERNAL_STORAGE.md)
- [键盘、鼠标与触控板说明 (英文)](docs/KEYBOARD_MOUSE.md)
- [运行时同步与 CI 产物说明 (英文)](docs/RUNTIME_SYNC.md)
- [分发要求与合规声明 (英文)](docs/DISTRIBUTION.md)

---

## 问题反馈与支持范围

- **在本仓库反馈**：使用本仓库 IPA 遇到的 Bug、游戏兼容性、安装/JIT、构建或打包问题，请提交至 **[LxnChan/iDeck Issues](https://github.com/LxnChan/iDeck/issues)**。
- **请勿向上游提交本分支问题**：不要在上游 iDeck、Madeira 或其他上游项目中，针对这些 IPA 发起 Issue、Discussion 或支持请求，也不要向其社群转交此类问题。该要求同时适用于下载的构建产物和使用本仓库源码在本地编译的 IPA。请先在本仓库诊断，必要的上游协调也由本仓库开展。
- **提供复现信息**：请附设备型号、iOS/iPadOS 版本、构建号、提交 SHA 或 Actions 构建链接、签名/JIT 方式、复现步骤和脱敏日志。下载问题还请注明内置或外置存储，以及当时是否锁屏或切到后台。

---

## 致谢与开源许可

- **iDeck**：基于 [kuscholar/iDeck](https://github.com/kuscholar/iDeck) 及其贡献者的工作。
- **Madeira**：感谢 Will Faust 及其贡献者构建了整个底层架构、图形驱动集成（DXMT）与 iOS 运行时。
- **上游生态**：致谢 Wine、FEX-Emu、DXMT、StikDebug / StikJIT、idevice 等优秀上游开源工程。
- **设计启发**：[DroidDeck](https://github.com/Droid-Deck/DroidDeck)。
- **开源许可证**：iDeck 新增代码遵循 **GPL-3.0-or-later** 许可证，上游各模块保留原有许可证（包括 LGPL、MIT、BSD、MPL 等），详见 [COPYING](COPYING)、[CREDITS.md](CREDITS.md) 及 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

*免责声明：Steam、SteamOS、Steam Big Picture 及 Steam Deck 均为 Valve Corporation 的商标或注册商标。iPhone、iPad、iOS、iPadOS 与 Metal 均为 Apple Inc. 的商标。iDeck 是独立的开源技术研究项目，与 Valve Corporation 或 Apple Inc. 无任何关联或官方背书。*
