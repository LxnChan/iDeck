[English](README.md) · [简体中文](README.zh-CN.md)

<p align="center">
  <img src="docs/assets/ideck/icon.png" width="156" alt="iDeck">
</p>
<h1 align="center">iDeck (Enhanced Fork)</h1>
<p align="center"><strong>Steam & Windows PC Gaming on iOS & iPadOS</strong></p>
<p align="center">
  <a href="https://discord.gg/aQdsaJyTM"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fdiscord.com%2Fapi%2Finvites%2FaQdsaJyTM%3Fwith_counts%3Dtrue&query=%24.approximate_member_count&suffix=%20members&label=Discord&logo=discord&logoColor=white&color=5865F2&style=for-the-badge" alt="Join the iDeck Discord"></a>
</p>
<p align="center">
  <a href="docs/GETTING_STARTED.md"><img src="https://img.shields.io/badge/Platform-iOS%20%26%20iPadOS%2017%2B-007AFF" alt="iOS and iPadOS"></a>
  <a href="docs/IDECK.md"><img src="https://img.shields.io/badge/Status-Active%20Development-success" alt="Active Development"></a>
  <a href="https://github.com/willfaust/Madeira"><img src="https://img.shields.io/badge/Powered%20by-Madeira%20%2B%20Wine%20%2B%20FEX-28C7D9" alt="Powered by Madeira"></a>
  <a href="COPYING"><img src="https://img.shields.io/badge/License-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later"></a>
</p>

iDeck brings Valve's Steam client and Windows PC games to iPhone and iPad, running locally through **Madeira, Wine, FEX-Emu, DXMT, and Metal**. Connect a physical controller, touch screen, or virtual gamepad to play your PC games on the go—**no streaming PC required**.

This fork introduces critical enhancements for **iPad multitasking & screen layout**, **native CJK/Chinese font support**, **HTTP/SOCKS5 proxy support for restricted networks**, **streamlined UI workflows**, and **automated CI builds**.

> **SteamOS experience, iOS underneath.** iDeck runs Windows Steam and PC titles through compatibility layers and instruction translation. It does not install Linux SteamOS, nor does it convert every game into an ARM-native iOS binary.

<p align="center">
  <img src="docs/assets/ideck/demo-landscape-ccw90-1.5x.gif" width="831" alt="Landscape iDeck demo: launching Steam and a PC game on iPhone, played at 1.5× speed">
  <br><sub>On-device demo · 1.5× playback speed · Experimental build</sub>
</p>

---

## What's New in this Fork

### 1. 🈲 Full CJK / Chinese Font Support (No More Tofu Boxes `□□□□`)
- **Authentic Bundled SimSun Font (`simsun.ttc`)**: Integrates the complete Windows SimSun & NSimSun font (`simsun.ttc`), providing full ASCII/Latin support (resolving English letters turning into boxes in dialog Edit controls such as the "Run" dialog) and comprehensive GBK/GB2312 Chinese characters alongside core Wine fonts (`tahoma.ttf`, `system.ttf`).
- **Automatic Wine Registry Injections**: Injects `FontLink\SystemLink`, `FontSubstitutes`, and `Wine\Fonts\Replacements` into `user.reg` and `system.reg` to map all common fonts (Microsoft YaHei, SimHei, KaiTi, FangSong) to SimSun.
- **System-wide Fix**: Resolves missing font glyphs / tofu boxes in Wine configuration utilities, `regedit.exe`, Windows installer wizards, UI dialogs, and Chinese-localized PC games on iOS/iPadOS 18+.

### 2. 📱 iPad Screen & Safe Area Optimization
- **Status Bar Collision Prevention**: Dynamically detects iPad devices and automatically reserves a 24pt+ safe area margin at the top in Wine session views.
- **Title Bar & Window Controls Protection**: Prevents iPad system status indicators (StikDebug back-pill, clock, battery, VPN icon) from obscuring Wine window title bars, menus, and window controls (`_ [] X`).
- **Header Conflict Fixes**: Eliminated visual overlap between the Big Picture toggle, brand titles, and the status bar.

### 3. 🌐 Dual-Layer HTTP & SOCKS5 Network Proxy
- **Master & Protocol Selector**: Configurable via the in-app Settings menu supporting both **HTTP** and **SOCKS5** protocols with custom Host and Port.
- **Granular Controls**:
  - **App Native Proxy**: Injected into `URLSessionConfiguration.connectionProxyDictionary`. Proxies Steam Guard sign-in, Steam Cloud save synchronization, depot game downloads, and game metadata/artwork.
  - **Wine & Steam Internal Proxy**:
    - CEF web helper (`steamwebhelper.exe`): Automatically injects `-proxy-server="protocol://host:port"` command-line flag, granting full access to Steam Store, Community, and Workshop.
    - Windows Registry (`Internet Settings`): Automatically sets `ProxyEnable=1` and `ProxyServer` for WinINet-based components.
    - POSIX Environment: Exports `http_proxy`, `https_proxy`, and `all_proxy` across the runtime environment.
- **Local & LAN Support**: Supports local loopback proxies (e.g., Shadowsocks, Surge, Loon running on `127.0.0.1`) and LAN gateways (`192.168.x.x`).

### 4. 🚀 Streamlined UI & Desktop Launch Mode
- **Native Game Library View**: Launches directly to the native Game Library view for immediate access to installed games and tools.
- **Lightweight Desktop Mode**: Launch Steam in traditional desktop client mode, dramatically reducing memory overhead compared to full Big Picture mode.
- **Accessible Diagnostics**: Easily switch between system diagnostics, wine configuration, and game library without getting trapped in subviews.

### 5. ⚙️ Automated CI/CD & Build Versioning
- **Auto-Incrementing Build Number**: Dynamically calculates and stamps build versions on every GitHub Actions workflow run (`CURRENT_PROJECT_VERSION`).
- **Pre-packaged Release Artifacts**: Automatically compiles and outputs ready-to-sign IPAs (`iDeck-fork-<sha>.ipa`).

---

## Installation & Setup

### Requirements
- **Device**: iPhone or iPad running iOS/iPadOS 17+ or 18+. (A17 Pro / M1 or higher recommended for 3D PC titles).
- **JIT Compiler**: Enabled via [StikDebug](https://github.com/stikdebug/stikdebug), StikJIT, or SideStore/AltStore JIT.
- **Sideloading Tool**: [SideStore](https://sidestore.io/), [AltStore](https://altstore.io/), [Sideloadly](https://sideloadly.io/), or Xcode.

### Step-by-Step

1. **Download the IPA**:
   - Download the latest build from the [GitHub Actions artifacts](https://github.com/LxnChan/iDeck/actions) or Releases tab.
2. **Sign and Sideload**:
   - Sideload using your preferred signing tool.
   - **Crucial**: Ensure `MadeiraJITHelper.appex` is signed alongside the main app, and the `get-task-allow` entitlement is preserved so debugging and JIT can attach.
3. **Enable JIT**:
   - Pair with StikDebug or launch via SideStore JIT before launching heavy 3D titles or Steam.
4. **Configure Network Proxy (Optional / Recommended for Restricted Regions)**:
   - Tap the Settings gear icon in the library.
   - Navigate to **Network Proxy Settings**.
   - Enable the master switch, select **HTTP** or **SOCKS5**, and enter your proxy IP and port.
   - Toggle **App Native Proxy** (for Steam auth and Depot downloads) and/or **Wine & Steam Proxy** (for Steam Store and CEF web pages).

---

## Before Steam: Prerequisites Checklist

When opening iDeck for the first time, navigate to the setup checker:

| Step | Component | Description |
| --- | --- | --- |
| 1 | **Local Runtime** | Tap **Prepare runtime** to initialize the Wine environment and extract core libraries. |
| 2 | **Fonts & CJK** | Included out of the box in this fork—no manual font copying required. |
| 3 | **Steam Client** | Provide a compatible Windows Steam client into the designated Wine prefix (`wine/drive_c/Steam32BundleLab` or `wine/drive_c/Steam32Lab`). |
| 4 | **Development Signing** | Requires a developer signature with task debugging permission. |
| 5 | **JIT Session** | Enable JIT via StikDebug/LocalDevVPN. Required for Wine's FEX translation layer. |

---

## Building from Source

```sh
# Clone the repository with submodules
git clone --recurse-submodules https://github.com/LxnChan/iDeck.git
cd iDeck
```

Open `app/Madeira.xcodeproj` in Xcode:
1. Select the `Madeira` scheme.
2. In Signing & Capabilities, select your personal or organization Apple Development Team.
3. Build and deploy to your connected iOS or iPadOS device.

Detailed build guides are available in:
- [Getting Started](docs/GETTING_STARTED.md)
- [Building the Project](docs/BUILDING.md)
- [JIT Configuration](docs/JIT.md)
- [Distribution Guidelines](docs/DISTRIBUTION.md)

---

## Community & Feedback

- **Upstream Project**: Built on [Madeira](https://github.com/willfaust/Madeira) by Will Faust and the upstream [iDeck](https://github.com/kuscholar/iDeck) community.
- **Discord**: Join discussions on the [iDeck Discord Server](https://discord.gg/aQdsaJyTM) or the [Madeira Discord](https://discord.gg/4t5mNjwCn7).
- **Issues**: Found a bug or compatibility quirk? Open an issue on GitHub with your device model, iOS version, build number, and logs.

---

## Credits & License

- **Madeira**: Will Faust and Madeira contributors for the core runtime, graphics translation (DXMT), and iOS device integration.
- **Upstream Tools**: Thanks to the developers of Wine, FEX-Emu, DXMT, StikDebug/StikJIT, and idevice.
- **Inspiration**: [DroidDeck](https://github.com/Droid-Deck/DroidDeck).
- **License**: iDeck additions are licensed under **GPL-3.0-or-later**. Upstream components retain their respective licenses (LGPL, MIT, BSD, MPL). See [COPYING](COPYING), [CREDITS.md](CREDITS.md), and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

*Disclaimer: Steam, SteamOS, Steam Big Picture, and Steam Deck are trademarks or registered trademarks of Valve Corporation. iPhone, iPad, iOS, iPadOS, and Metal are trademarks of Apple Inc. iDeck is an independent open-source project and is not affiliated with or endorsed by Valve Corporation or Apple Inc.*
