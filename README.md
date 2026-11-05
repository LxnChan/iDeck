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
  <a href="https://github.com/LxnChan/iDeck/actions"><img src="https://img.shields.io/badge/Build-GitHub%20Actions-brightgreen?logo=github-actions" alt="Build Status"></a>
  <a href="docs/GETTING_STARTED.md"><img src="https://img.shields.io/badge/Platform-iOS%20%26%20iPadOS%2017%2B-007AFF" alt="iOS and iPadOS"></a>
  <a href="docs/IDECK.md"><img src="https://img.shields.io/badge/Status-Active%20Development-success" alt="Active Development"></a>
  <a href="https://github.com/willfaust/Madeira"><img src="https://img.shields.io/badge/Powered%20by-Madeira%20%2B%20Wine%20%2B%20FEX-28C7D9" alt="Powered by Madeira"></a>
  <a href="COPYING"><img src="https://img.shields.io/badge/License-GPL--3.0--or--later-blue" alt="GPL-3.0-or-later"></a>
</p>

iDeck brings Valve's Steam client and Windows PC games to iPhone and iPad, running locally through **Madeira, Wine, FEX-Emu, DXMT, and Metal**. Connect a physical controller, touch screen, or virtual gamepad to play your PC games on the go—**no streaming PC required**.

> [!TIP]
> ### 📦 Download Pre-built IPA (Artifacts Guide)
> You don't need a Mac or Xcode to build iDeck! Pre-compiled, ready-to-sign IPAs are built automatically by GitHub Actions on every push:
> 1. Go to the [**Actions** tab](https://github.com/LxnChan/iDeck/actions?query=workflow%3A%22Build+iDeck+IPA%22+is%3Asuccess).
> 2. Click the topmost completed run with a green checkmark (e.g. `Build iDeck IPA`).
> 3. Scroll down to the bottom of the summary page to the **Artifacts** section.
> 4. Click **`iDeck-fork-<sha>`** to download the ZIP file containing the compiled IPA package (`iDeck-fork-*.ipa`).
> *(Note: You must be signed in to your GitHub account to download workflow artifacts).*

<p align="center">
  <img src="docs/assets/ideck/demo-landscape-ccw90-1.5x.gif" width="831" alt="Landscape iDeck demo: launching Steam and a PC game on iPhone, played at 1.5× speed">
  <br><sub>On-device demo · 1.5× playback speed · Experimental build</sub>
</p>

---

## What's New in this Fork

### 1. 🈲 Full CJK / Chinese Font Support (No More Tofu Boxes `□□□□`)
- **SimSun (`simsun.ttc`) & Microsoft YaHei (`msyh.ttc`) Bundled**: Includes authentic Windows SimSun/NSimSun (18.3 MB) and Microsoft YaHei/YaHei UI (19.7 MB) TrueType font collections directly inside the app bundle.
- **Fixed Latin Letters in Edit Controls**: Resolves typed English letters turning into rectangles in dialog Edit controls (such as the Wine "Run" dialog).
- **Fixed Steam Chinese Glyphs**: Steam's VGUI and Chromium/CEF DirectWrite engines require `Microsoft YaHei` by default. Bundling `msyh.ttc` and registering it in `[Fonts]` completely fixes missing Chinese glyphs in the Steam login window, client store, and friends list.
- **Automated FontLink**: Injects `FontLink\SystemLink` mapping `Segoe UI`, `Tahoma`, `Arial`, `Lucida Sans`, and `MS Sans Serif` to `msyh.ttc,Microsoft YaHei` and `simsun.ttc,SimSun`.

### 2. 📱 iPad Immersive Full-Screen (Zero Black Bars) & Frosted Navigation Bar
- **Eliminated iPad Top Double Inset**: Fixed a layout bug where iPad applied both an unignored safe area and an additional manual `topInset`, causing an unsightly 48pt+ black gap above the screen.
- **True Full-Screen Session**: In Wine sessions, the iPad display is now edge-to-edge full screen (`.statusBarHidden(true)` and `.ignoresSafeArea(edges: .all)`), matching iPhone behavior. The floating HUD menu button (`≡`) now rests comfortably at the top corner.
- **Frosted Material Background**: Applied system frosted blur material (`UIBlurEffect(style: .systemMaterial)`) to the game library navigation bar and search bar, preventing game cards from bleeding through when scrolling down.

### 3. 🖱️ Snappy Pointer & Customizable Long-Press Threshold
- **Halved Long-Press Delay**: Reduced default Absolute trackpad mode long-press drag threshold from `0.5s` to `0.25s`, making window dragging, selection, and clicking much snappier.
- **Customizable Slider**: Added a custom slider in **Settings → Pointer** and in-game HUD (`0.15s` – `0.60s`, step `0.05s`) with persistent user preference storage.

### 4. 🚀 Tri-Launcher Home Layout & On-Demand Library
- **Side-by-Side Launcher Buttons**: The top of the library now features three responsive capsule buttons side-by-side:
  - **`Desktop`**: Starts the Wine desktop and Explorer file manager.
  - **`Steam Launcher`**: Starts lightweight Windows Steam in normal desktop client mode (no Big Picture CEF overhead).
  - **`Steam Big Picture Mode`**: Starts full controller-optimized Steam Big Picture mode (`-bigpicture`).
- **Context Menus & Gamepad Focus**: Long-press any Steam button for direct launch options; full D-pad left/right highlight navigation support.
- **Settings Toggle**: Added a dedicated **Steam Client** section in Settings with a "Launch mode" picker.
- **Lazy-Loaded "Not installed" Group**: The "Not installed" section on the home page is now collapsed by default and completely skips loading covers while folded, drastically saving bandwidth and memory.

### 5. 🌐 Dual-Layer HTTP & SOCKS5 Network Proxy
- **Master & Protocol Selector**: Configurable via the in-app Settings menu supporting both **HTTP** and **SOCKS5** protocols with custom Host and Port.
- **Granular Controls**:
  - **App Native Proxy**: Injected into `URLSessionConfiguration.connectionProxyDictionary`. Proxies Steam Guard sign-in, Steam Cloud save synchronization, depot game downloads, and game metadata/artwork.
  - **Wine & Steam Internal Proxy**:
    - CEF web helper (`steamwebhelper.exe`): Automatically injects `-proxy-server="protocol://host:port"` command-line flag, granting full access to Steam Store, Community, and Workshop.
    - Windows Registry (`Internet Settings`): Automatically sets `ProxyEnable=1` and `ProxyServer` for WinINet-based components.
    - POSIX Environment: Exports `http_proxy`, `https_proxy`, and `all_proxy` across the runtime environment.
- **Local & LAN Support**: Supports local loopback proxies (e.g., Shadowsocks, Surge, Loon running on `127.0.0.1`) and LAN gateways (`192.168.x.x`).

### 6. ⚙️ Automated CI/CD & Build Versioning
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
   - Go to [**GitHub Actions**](https://github.com/LxnChan/iDeck/actions?query=workflow%3A%22Build+iDeck+IPA%22+is%3Asuccess) and open the latest successful `Build iDeck IPA` workflow run.
   - Download the **`iDeck-fork-<sha>`** artifact at the bottom of the summary page and unzip it.
2. **Sign and Sideload**:
   - Sideload using your preferred signing tool.
   - **Crucial**: Ensure `MadeiraJITHelper.appex` is signed alongside the main app, and the `get-task-allow` entitlement is preserved so debugging and JIT can attach.
3. **Enable JIT**:
   - Pair with StikDebug or launch via SideStore JIT before launching heavy 3D titles or Steam.
4. **Configure Network Proxy (Optional / Recommended for Restricted Regions)**:
   - Tap the Settings tab in the library.
   - Navigate to **Network Proxy**.
   - Enable the master switch, select **HTTP** or **SOCKS5**, and enter your proxy IP and port.
   - Toggle **App Native Proxy** and/or **Wine & Steam Proxy** as needed.

---

## Before Steam: Prerequisites Checklist

When opening iDeck for the first time, navigate to the setup checker:

| Step | Component | Description |
| --- | --- | --- |
| 1 | **Local Runtime** | Tap **Prepare runtime** to initialize the Wine environment and extract core libraries. |
| 2 | **Fonts & CJK** | Included out of the box in this fork (both SimSun and Microsoft YaHei)—no manual font copying required. |
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
