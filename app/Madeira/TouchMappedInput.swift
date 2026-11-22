import Foundation
import SwiftUI
import UIKit

// MARK: - Pure mapped touch state

enum TouchMappedAction: Equatable {
    case none, key(Int32), mouseLeft, mouseRight, keyboardToggle
    case stick([Int32], deadzone: Double)
}

enum TouchMappedEvent: Equatable {
    case key(Int32, Bool), pointer(UInt32), keyboardToggle
}

/// Input ownership must not depend on SwiftUI committing a visual @State change.
/// A quick down/up, or a move before the next render, still produces every edge.
struct TouchMappedState {
    let action: TouchMappedAction
    private(set) var down = false
    private(set) var direction = -1
    private var keys = Set<Int32>()

    mutating func update(x: Double = 0, y: Double = 0, down next: Bool) -> [TouchMappedEvent] {
        let wasDown = down
        down = next
        if case .stick(let mapping, let deadzone) = action {
            direction = -1
            if next, x.isFinite, y.isFinite, hypot(x, y) >= deadzone {
                var angle = atan2(x, -y) * 180 / .pi
                if angle < 0 { angle += 360 }
                direction = Int((angle + 22.5) / 45) % 8
            }
            var held = Set<Int32>()
            if mapping.count == 4, direction >= 0 {
                // Clockwise sectors: up, up/right, right, right/down, ...
                held.insert(mapping[direction / 2])
                if direction % 2 == 1 { held.insert(mapping[(direction / 2 + 1) % 4]) }
            }
            let events = keys.subtracting(held).sorted().map { TouchMappedEvent.key($0, false) }
                + held.subtracting(keys).sorted().map { TouchMappedEvent.key($0, true) }
            keys = held
            return events
        }
        guard next != wasDown else { return [] }
        switch action {
        case .key(let vk): return [.key(vk, next)]
        case .mouseLeft: return [.pointer(next ? 0x0002 : 0x0004)]
        case .mouseRight: return [.pointer(next ? 0x0008 : 0x0010)]
        case .keyboardToggle: return next ? [.keyboardToggle] : []
        case .none, .stick: return []
        }
    }
}

// MARK: - UIKit touch delivery

/// Bounded timing only; never log key codes or text typed into the guest.
@MainActor enum TouchDeliveryTiming {
    private static var samples = 0
    static func record(_ touch: UITouch, receivedAt: TimeInterval) {
        let milliseconds = max(0, receivedAt - touch.timestamp) * 1000
        guard samples < 8 || (milliseconds >= 50 && samples < 24) else { return }
        samples += 1
        fputs(String(format: "[touch-control] began delivery-ms=%.1f sample=%d\n", milliseconds, samples), stderr)
    }
}

/// Gameplay uses raw touch callbacks, as TouchPadSurface already does for
/// XInput. SwiftUI gestures remain responsible for arranging controls in edit mode.
struct TouchMappedSurface: UIViewRepresentable {
    let action: TouchMappedAction
    var haptics = false
    let changed: (Bool, Int) -> Void

    func makeUIView(context: Context) -> TouchMappedView { TouchMappedView() }
    func updateUIView(_ view: TouchMappedView, context: Context) {
        view.configure(action: action, haptics: haptics, changed: changed)
    }
    static func dismantleUIView(_ view: TouchMappedView, coordinator: ()) { view.releaseAll() }
}

final class TouchMappedView: UIView {
    private var state = TouchMappedState(action: .none)
    private var finger: ObjectIdentifier?
    private var start = CGPoint.zero
    private var previousSize = CGSize.zero
    private var haptics = false
    private var changed: ((Bool, Int) -> Void)?

    init() {
        super.init(frame: .zero)
        backgroundColor = .clear
        NotificationCenter.default.addObserver(self, selector: #selector(releaseAll),
            name: UIApplication.willResignActiveNotification, object: nil)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    deinit { NotificationCenter.default.removeObserver(self) }

    func configure(action: TouchMappedAction, haptics: Bool, changed: @escaping (Bool, Int) -> Void) {
        if state.action != action {
            releaseAll()
            state = TouchMappedState(action: action)
        }
        self.haptics = haptics
        self.changed = changed
    }
    override func layoutSubviews() {
        super.layoutSubviews()
        if previousSize != bounds.size { releaseAll(); previousSize = bounds.size }
    }
    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window == nil { releaseAll() }
    }
    @objc func releaseAll() {
        finger = nil
        apply(down: false)
    }
    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard UIApplication.shared.applicationState == .active,
              finger == nil, let touch = touches.first else { return }
        let receivedAt = ProcessInfo.processInfo.systemUptime
        finger = ObjectIdentifier(touch)
        start = touch.location(in: self)
        apply(down: true)
        TouchDeliveryTiming.record(touch, receivedAt: receivedAt)
    }
    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard UIApplication.shared.applicationState == .active else { releaseAll(); return }
        guard let touch = touches.first(where: { ObjectIdentifier($0) == finger }) else { return }
        let point = touch.location(in: self)
        apply(x: Double(point.x - start.x), y: Double(point.y - start.y), down: true)
    }
    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) { finish(touches) }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { finish(touches) }
    private func finish(_ touches: Set<UITouch>) {
        if touches.contains(where: { ObjectIdentifier($0) == finger }) { releaseAll() }
    }
    private func apply(x: Double = 0, y: Double = 0, down: Bool) {
        let wasDown = state.down, oldDirection = state.direction
        let events = state.update(x: x, y: y, down: down)
        // Enqueue input before feedback or observable UI changes.
        for event in events {
            switch event {
            case .key(let vk, let pressed): winios_post_key(vk, pressed ? 1 : 0)
            case .pointer(let flags): winios_pointer(0, 0, flags, 0)
            case .keyboardToggle: MetalBackedView.toggleKeyboard()
            }
        }
        if haptics && !wasDown && state.down { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
        if wasDown != state.down || oldDirection != state.direction { changed?(state.down, state.direction) }
    }
}

extension ControlAction {
    func touchMapping(diameter: CGFloat) -> TouchMappedAction {
        switch self {
        case .key(let vk): return .key(vk)
        case .mouseLeft: return .mouseLeft
        case .mouseRight: return .mouseRight
        case .keyboardToggle: return .keyboardToggle
        case .joystickWASD, .joystickArrows:
            return .stick(stickKeys ?? [], deadzone: Double(diameter * 0.22))
        case .none, .pad: return .none
        }
    }
}
