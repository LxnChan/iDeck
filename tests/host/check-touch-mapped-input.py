#!/usr/bin/env python3
"""Compile mapped touch state and production UIView callbacks with host UI stubs.

Checks edges without a SwiftUI render, independent controls, quick taps, stick
transitions, cancellation, remapping, resize, removal and app inactivity.
--source-only checks extraction and wiring on hosts without Swift.
"""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
source = (app / 'TouchMappedInput.swift').read_text(encoding='utf-8')
pure = source.split('// MARK: - Pure mapped touch state', 1)[1].split('// MARK: - UIKit touch delivery', 1)[0]
view = source[source.index('final class TouchMappedView: UIView {'):source.index('\nextension ControlAction {')]
# Host UI stubs implement selector registration without an Objective-C runtime.
view = view.replace('#selector(releaseAll)', '"releaseAll"').replace('@objc ', '')
content = (app / 'ContentView.swift').read_text(encoding='utf-8')
for start, end in [('struct HoldKeyView:', 'final class JoystickPadState:'),
                   ('struct JoystickKeyView:', '// SwiftUI wrapper'),
                   ('struct TouchControlButton:', 'struct MappingPanel:')]:
    section = content.split(start, 1)[1].split(end, 1)[0]
    assert 'TouchMappedSurface(' in section, start
assert 'including: m.editing ? .all : .subviews' in content
assert 'TouchMappedInput.swift in Sources' in (root / 'app/Madeira.xcodeproj/project.pbxproj').read_text()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true')
if parser.parse_args().source_only:
    print('PASS: mapped input extraction and gameplay surface wiring (Swift execution not run)')
    raise SystemExit(0)

stubs = r'''
var delivered: [TouchMappedEvent] = []
var feedback = 0
class UIView {
    struct Color { static let clear = Color() }
    var backgroundColor: Color?
    var bounds: CGRect
    var window: Bool? = true
    init(frame: CGRect) { bounds = frame }
    func layoutSubviews() {}
    func didMoveToWindow() {}
    func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {}
    func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {}
    func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {}
    func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {}
}
class UITouch: Hashable {
    var point = CGPoint.zero
    func location(in view: UIView) -> CGPoint { point }
    static func == (lhs: UITouch, rhs: UITouch) -> Bool { lhs === rhs }
    func hash(into hasher: inout Hasher) { hasher.combine(ObjectIdentifier(self)) }
}
struct UIEvent {}
class UIApplication {
    enum State { case active, inactive }
    static let shared = UIApplication()
    static let willResignActiveNotification = "inactive"
    var applicationState = State.active
}
class NotificationCenter {
    static let `default` = NotificationCenter()
    func addObserver(_ observer: Any, selector: String, name: String, object: Any?) {}
    func removeObserver(_ observer: Any) {}
}
struct UIImpactFeedbackGenerator {
    enum Style { case light }
    init(style: Style) {}
    func impactOccurred() { feedback += 1 }
}
enum TouchDeliveryTiming { static func record(_ touch: UITouch, receivedAt: TimeInterval) {} }
func winios_post_key(_ vk: Int32, _ down: Int32) { delivered.append(.key(vk, down != 0)) }
func winios_pointer(_ x: Int32, _ y: Int32, _ flags: UInt32, _ data: Int32) { delivered.append(.pointer(flags)) }
enum MetalBackedView { static func toggleKeyboard() { delivered.append(.keyboardToggle) } }
'''

tests = r'''
let arrows: [Int32] = [0x26, 0x27, 0x28, 0x25]
var stick = TouchMappedState(action: .stick(arrows, deadzone: 14))
assert(stick.update(down: true).isEmpty && stick.down && stick.direction == -1)
let points: [(Double, Double)] = [(0,-20),(20,-20),(20,0),(20,20),(0,20),(-20,20),(-20,0),(-20,-20)]
for (direction, point) in points.enumerated() {
    let events = stick.update(x: point.0, y: point.1, down: true)
    assert(stick.direction == direction && !events.isEmpty)
    assert(stick.update(x: point.0, y: point.1, down: true).isEmpty)
}
assert(stick.update(down: false) == [.key(0x25, false), .key(0x26, false)])
assert(stick.update(down: false).isEmpty)
assert(stick.update(x: .nan, y: 20, down: true).isEmpty && stick.direction == -1)
assert(stick.update(x: 0, y: -.infinity, down: true).isEmpty)
assert(stick.update(x: 0, y: -13.9, down: true).isEmpty)
assert(stick.update(x: 0, y: -14, down: true) == [.key(0x26, true)])
assert(stick.update(x: 20, y: -20, down: true) == [.key(0x27, true)])
assert(stick.update(x: 20, y: 0, down: true) == [.key(0x26, false)])
assert(stick.update(down: false) == [.key(0x27, false)])

func surface(_ action: TouchMappedAction) -> TouchMappedView {
    let result = TouchMappedView()
    // Deliberately ignore visual state: input still works without a render.
    result.configure(action: action, haptics: true) { _, _ in }
    result.bounds.size = CGSize(width: 64, height: 64)
    result.layoutSubviews()
    return result
}
let key = surface(.key(0x26)), touch = UITouch(), other = UITouch()
for _ in 0..<100 {
    key.touchesBegan([touch], with: nil)
    key.touchesBegan([other], with: nil) // another finger cannot replace the owner
    key.touchesMoved([touch], with: nil)
    key.touchesEnded([other], with: nil)
    key.touchesEnded([touch], with: nil)
    key.touchesCancelled([touch], with: nil)
}
assert(delivered == Array(repeating: [TouchMappedEvent.key(0x26, true), .key(0x26, false)], count: 100).flatMap { $0 })
assert(feedback == 100)
delivered = []
key.touchesBegan([touch], with: nil)
key.configure(action: .key(0x28), haptics: false) { _, _ in }
key.touchesEnded([touch], with: nil) // old finger cannot release a new mapping
key.touchesBegan([touch], with: nil)
key.touchesCancelled([touch], with: nil)
assert(delivered == [.key(0x26, true), .key(0x26, false), .key(0x28, true), .key(0x28, false)])

for interrupt in 0..<5 {
    delivered = []
    key.window = true
    UIApplication.shared.applicationState = .active
    key.touchesBegan([touch], with: nil)
    switch interrupt {
    case 0: key.releaseAll() // willResignActive / dismantle
    case 1: key.window = nil; key.didMoveToWindow()
    case 2: key.bounds.size.width += 1; key.layoutSubviews()
    case 3: key.touchesCancelled([touch], with: nil)
    default:
        UIApplication.shared.applicationState = .inactive
        key.touchesMoved([touch], with: nil)
    }
    key.touchesEnded([touch], with: nil)
    assert(delivered == [.key(0x28, true), .key(0x28, false)])
}
delivered = []
key.touchesBegan([touch], with: nil) // inactive touches ignored
assert(delivered.isEmpty)
UIApplication.shared.applicationState = .active
let mouse = surface(.mouseLeft), mouseTouch = UITouch()
key.touchesBegan([touch], with: nil)
mouse.touchesBegan([mouseTouch], with: nil)
key.touchesEnded([touch], with: nil)
mouse.touchesEnded([mouseTouch], with: nil)
assert(delivered == [.key(0x28, true), .pointer(2), .key(0x28, false), .pointer(4)])
delivered = []
let right = surface(.mouseRight), keyboard = surface(.keyboardToggle)
right.touchesBegan([touch], with: nil); right.releaseAll()
keyboard.touchesBegan([touch], with: nil); keyboard.releaseAll()
assert(delivered == [.pointer(8), .pointer(16), .keyboardToggle])
delivered = []
touch.point = .zero
let joystick = surface(.stick(arrows, deadzone: 14))
joystick.touchesBegan([touch], with: nil)
touch.point = CGPoint(x: 20, y: -20)
joystick.touchesMoved([touch], with: nil)
touch.point = CGPoint(x: 20, y: 0)
joystick.touchesMoved([touch], with: nil)
joystick.releaseAll()
assert(delivered == [.key(0x26, true), .key(0x27, true), .key(0x26, false), .key(0x27, false)])
print("PASS: immediate touch edges, 100 taps without rendering, stick sectors, independent controls and lifecycle releases")
'''
with tempfile.TemporaryDirectory(prefix='madeira-touch-input-') as tmp:
    src = Path(tmp) / 'main.swift'
    exe = Path(tmp) / ('check.exe' if os.name == 'nt' else 'check')
    src.write_text('import Foundation\n' + pure + stubs + view + tests, encoding='utf-8')
    subprocess.run([os.environ.get('SWIFTC', 'swiftc'), str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
