import Foundation
import SwiftUI
import UIKit
import AVFoundation

enum MicrophoneManager {
    static func requestPermission() {
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission { granted in
                fputs("[audio] microphone permission: \(granted ? "granted" : "denied")\n", stderr)
            }
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                fputs("[audio] microphone permission: \(granted ? "granted" : "denied")\n", stderr)
            }
        }
    }
}

extension Notification.Name {
    static let appMenuAddCustomGame = Notification.Name("appMenuAddCustomGame")
    static let appMenuLaunchDesktop = Notification.Name("appMenuLaunchDesktop")
    static let appMenuLaunchSteamDesktop = Notification.Name("appMenuLaunchSteamDesktop")
    static let appMenuLaunchSteamBigPicture = Notification.Name("appMenuLaunchSteamBigPicture")
    static let appMenuAbout = Notification.Name("appMenuAbout")
}

@MainActor
final class MadeiraAppDelegate: UIResponder, UIApplicationDelegate {
    static var orientationMask: UIInterfaceOrientationMask = .allButUpsideDown

    func application(_ application: UIApplication, supportedInterfaceOrientationsFor window: UIWindow?) -> UIInterfaceOrientationMask {
        Self.orientationMask
    }

    override func buildMenu(with builder: UIMenuBuilder) {
        super.buildMenu(with: builder)
        guard builder.system == .main else { return }

        // Remove standard menus not part of the requested specification
        builder.remove(menu: .edit)
        builder.remove(menu: .format)
        builder.remove(menu: .window)

        // 1. File Menu: 添加自定义游戏（关联右上角加号逻辑）、退出
        let addGameCmd = UIKeyCommand(
            title: "添加自定义游戏",
            action: #selector(handleMenuAddCustomGame),
            input: "n",
            modifierFlags: .command
        )
        addGameCmd.discoverabilityTitle = "添加自定义游戏"

        let exitCmd = UIKeyCommand(
            title: "退出",
            action: #selector(handleMenuExit),
            input: "q",
            modifierFlags: .command
        )
        exitCmd.discoverabilityTitle = "退出"

        let fileMenu = UIMenu(
            title: "File",
            identifier: .file,
            children: [addGameCmd, exitCmd]
        )
        if builder.menu(for: .file) != nil {
            builder.replace(menu: .file, with: fileMenu)
        } else {
            builder.insertSibling(fileMenu, beforeMenu: .help)
        }

        // 2. View Menu: Desktop、Steam Launcher (Desktop)、Steam Big Picture
        let desktopCmd = UIKeyCommand(
            title: "Desktop",
            action: #selector(handleMenuDesktop),
            input: "1",
            modifierFlags: .command
        )
        desktopCmd.discoverabilityTitle = "Desktop"

        let steamLauncherCmd = UIKeyCommand(
            title: "Steam Launcher (Desktop)",
            action: #selector(handleMenuSteamLauncher),
            input: "2",
            modifierFlags: .command
        )
        steamLauncherCmd.discoverabilityTitle = "Steam Launcher (Desktop)"

        let steamBigPictureCmd = UIKeyCommand(
            title: "Steam Big Picture",
            action: #selector(handleMenuSteamBigPicture),
            input: "3",
            modifierFlags: .command
        )
        steamBigPictureCmd.discoverabilityTitle = "Steam Big Picture"

        let viewMenu = UIMenu(
            title: "View",
            identifier: .view,
            children: [desktopCmd, steamLauncherCmd, steamBigPictureCmd]
        )
        if builder.menu(for: .view) != nil {
            builder.replace(menu: .view, with: viewMenu)
        } else {
            builder.insertSibling(viewMenu, afterMenu: .file)
        }

        // 3. Help Menu: About
        let aboutCmd = UICommand(
            title: "About",
            action: #selector(handleMenuAbout)
        )
        let helpMenu = UIMenu(
            title: "Help",
            identifier: .help,
            children: [aboutCmd]
        )
        if builder.menu(for: .help) != nil {
            builder.replace(menu: .help, with: helpMenu)
        } else {
            builder.insertSibling(helpMenu, afterMenu: .view)
        }
    }

    override func canPerformAction(_ action: Selector, withSender sender: Any?) -> Bool {
        if action == #selector(handleMenuAddCustomGame) ||
           action == #selector(handleMenuExit) ||
           action == #selector(handleMenuDesktop) ||
           action == #selector(handleMenuSteamLauncher) ||
           action == #selector(handleMenuSteamBigPicture) ||
           action == #selector(handleMenuAbout) {
            return true
        }
        return super.canPerformAction(action, withSender: sender)
    }

    @objc func handleMenuAddCustomGame(_ sender: Any?) {
        NotificationCenter.default.post(name: .appMenuAddCustomGame, object: nil)
        LibraryModel.shared.showAddGame = true
        LibraryController.shared.commands.send("add")
    }

    @objc func handleMenuExit(_ sender: Any?) {
        if LibraryModel.shared.current != nil {
            LibraryModel.shared.requestQuit()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            exit(0)
        }
    }

    @objc func handleMenuDesktop(_ sender: Any?) {
        NotificationCenter.default.post(name: .appMenuLaunchDesktop, object: nil)
    }

    @objc func handleMenuSteamLauncher(_ sender: Any?) {
        NotificationCenter.default.post(name: .appMenuLaunchSteamDesktop, object: nil)
    }

    @objc func handleMenuSteamBigPicture(_ sender: Any?) {
        NotificationCenter.default.post(name: .appMenuLaunchSteamBigPicture, object: nil)
    }

    @objc func handleMenuAbout(_ sender: Any?) {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        let appName = Bundle.main.infoDictionary?["CFBundleDisplayName"] as? String ?? (IDeckState.enabled ? "iDeck" : "Madeira")
        let alert = UIAlertController(
            title: "\(appName) v\(version) (\(build))",
            message: "PC gaming and Windows compatibility layer for iPadOS / iOS powered by FEX-Emu, Wine, and Metal graphics translation.\n\nCreated by Will Faust, with contributions by Nick, Jfishin, Jesse, Dan Perks, bahacan16, spitefulowl, meshoklv, TheHadesc, and the open-source community.",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "OK", style: .default))
        for scene in UIApplication.shared.connectedScenes {
            if let windowScene = scene as? UIWindowScene,
               let root = windowScene.windows.first(where: { $0.isKeyWindow })?.rootViewController {
                var top = root
                while let presented = top.presentedViewController {
                    top = presented
                }
                top.present(alert, animated: true)
                break
            }
        }
    }
}

enum GameSessionOrientation {
    @MainActor private static var locked = false

    static func setLandscapeLocked(_ enabled: Bool) {
        DispatchQueue.main.async { applyLandscapeLock(enabled) }
    }

    @MainActor private static func applyLandscapeLock(_ enabled: Bool) {
        guard UIDevice.current.userInterfaceIdiom == .phone else { return }
        let wasLocked = locked
        locked = enabled
        MadeiraAppDelegate.orientationMask = enabled ? .landscape : .allButUpsideDown
        guard enabled || wasLocked else { return }
        for case let scene as UIWindowScene in UIApplication.shared.connectedScenes where scene.activationState == .foregroundActive {
            for window in scene.windows {
                window.rootViewController?.setNeedsUpdateOfSupportedInterfaceOrientations()
            }
            scene.requestGeometryUpdate(.iOS(interfaceOrientations: enabled ? .landscape : .portrait)) { error in
                LogStore.shared.log("[orientation] rotation request failed: \(error.localizedDescription)")
            }
        }
    }
}

@main
struct MadeiraApp: App {
    @UIApplicationDelegateAdaptor(MadeiraAppDelegate.self) private var appDelegate
    init() {
        // madeira-bcd: the Metal Performance HUD's performance insights (the
        // notes that stack up left of its panel: shader compiles, similar render
        // passes, blit encoders) cover the game. Off unless madeira.cfg says
        // env.MTL_HUD_INSIGHTS_ENABLED = 1, which is exported later and wins.
        setenv("MTL_HUD_INSIGHTS_ENABLED", "0", 0)
        // ml1172: read the screen on the main thread; library entries, whose
        // default Resolution comes from it, are also made on other threads.
        _ = ResolutionChoices.screen
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .modifier(ClaimGamepadEvents())
                .onAppear {
                    GamepadInput.shared.start()
                    HardwareInput.shared.start()
                    MicrophoneManager.requestPermission()
                    JITNetworkShortcut.shared.restoreLeftover()   // also starts its network path monitor
                }
                // madeira://jit-network/... (the Madeira JIT shortcut returning, JITNetwork.swift),
                // else madeira://play?exe=... (Home Screen shortcuts, SavesAndShortcuts.swift).
                .onOpenURL { url in if !JITNetworkShortcut.shared.handle(url) { ShortcutRouter.shared.handle(url) } }
        }
    }
}
