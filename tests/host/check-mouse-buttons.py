#!/usr/bin/env python3
"""Exercise actual hardware mouse button routing with scripted UIKit contacts.

The Swift harness uses the production source arbitration, interception, mask
decoding and Wine packet emission methods. UIKit and device callbacks are
replaced with small stubs; no iOS SDK or physical mouse is required.
--source-only verifies extraction/wiring without running the behavioral checks.
"""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'app/Madeira/HardwareInput.swift').read_text(encoding='utf-8')
pure = source.split('// MARK: - Pure input mapping', 1)[1].split('// MARK: - Device glue', 1)[0]


def method(signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end].replace('private func ', 'func ', 1)


names = (
    'private func buttonChanged(', 'private func resolvePendingButton(',
    'private func syncButtons()', 'private func releaseAll(',
    'func interceptTouches(', 'private func pointerButtons(',
    'func uikitButtons(', 'func fingerTouches(',
    'func shouldIgnore(_ t:', 'func shouldIgnore(_ touches:',
    'private func compatibilityTouch(', 'private func resolveCompatibilityClick(',
    'private func postPointerButtons()',
    'func uikitMoved(', 'func uikitScroll(', 'private func scrolled(',
    'private func resetRawMouseSources()',
)
methods = '\n'.join(method(signature) for signature in names)
held = source.split('    // MARK: held state (main thread)', 1)[1].split('    // MARK: cursor and lock state', 1)[0]
held = held.replace('private ', '')
observer = source.split('final class PointerButtonObserver:', 1)[1].split('final class PointerFallback:', 1)[0]
for phase in ('began', 'moved', 'ended', 'cancelled'):
    assert f'HardwareInput.shared.interceptTouches(touches, event, .{phase})' in observer
for setting in ('cancelsTouchesInView', 'delaysTouchesBegan', 'delaysTouchesEnded'):
    assert f'{setting} = false' in observer
assert 'view.addGestureRecognizer(PointerButtonObserver())' in source
detach = method('private func detachMouse(')
assert 'if remaining.isEmpty {\n            resetRawMouseSources()' in detach
assert 'resetRawMouseSources()' not in method('private func releaseAll(')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true')
args = parser.parse_args()
if args.source_only:
    print('PASS: extracted actual mouse routing/state and passive button observer wiring (source checks only)')
    raise SystemExit(0)

stubs = r'''
import Foundation
#if canImport(CoreGraphics)
import CoreGraphics
#endif
typealias CFTimeInterval = Double
enum TestClock { static var now: Double = 10 }
func CACurrentMediaTime() -> Double { TestClock.now }

struct Packet: Equatable {
    var x: Int32, y: Int32, flags: UInt32, data: UInt32
}
var packets: [Packet] = []
func winios_pointer(_ x: Int32, _ y: Int32, _ flags: UInt32, _ data: UInt32) {
    packets.append(Packet(x: x, y: y, flags: flags, data: data))
}

class UIView {
    var bounds = CGRect(x: 0, y: 0, width: 1024, height: 768)
}
final class UITouch: Hashable {
    enum TouchType { case direct, indirectPointer }
    enum Phase { case began, moved, stationary, ended, cancelled }
    var type: TouchType, phase: Phase
    var majorRadius: CGFloat
    var point: CGPoint
    var view: UIView? = UIView()
    init(_ type: TouchType = .indirectPointer, phase: Phase = .began,
         radius: CGFloat = 0, point: CGPoint = CGPoint(x: 100, y: 100)) {
        self.type = type; self.phase = phase; majorRadius = radius; self.point = point
    }
    func location(in view: UIView?) -> CGPoint { point }
    static func == (a: UITouch, b: UITouch) -> Bool { a === b }
    func hash(into h: inout Hasher) { h.combine(ObjectIdentifier(self)) }
}
final class UIEvent {
    struct ButtonMask: OptionSet {
        var rawValue: Int
        static let primary = ButtonMask(rawValue: 1)
        static let secondary = ButtonMask(rawValue: 2)
        static func button(_ number: Int) -> ButtonMask {
            ButtonMask(rawValue: 1 << (number - 1))
        }
    }
    var buttonMask: ButtonMask
    var allTouches: Set<UITouch>?
    init(_ mask: ButtonMask = [], _ touches: Set<UITouch> = []) {
        buttonMask = mask; allTouches = touches
    }
}
enum MetalBackedView {
    static var keyboardTarget: UIView? = UIView()
    static var cursor = CGPoint.zero
}
final class InputSettings {
    static let shared = InputSettings()
    var mouseMode = true
    var ignoreTouchesWithMouse = true
    var diagnostics = false
}
'''

glue_stubs = r'''
final class HardwareInput {
    static var enabled = true
    static var focusEnabled = true
    static let moveFlag: UInt32 = 1
    static let absoluteFlag: UInt32 = 0x8000
    enum TouchPhase { case began, moved, ended, cancelled }
    var baseFocused = true
    var mouseFocused = true
    var mouseConnected = true
    var pointerLocked = false
    var hoverSeen = true
    var gcDeltaSeen = false
    var gcDeltaLive = false
    var gcScrollLive = false
    var mouseActive = false
    var touchClassLogged = 0
    var lastGCButtonAt: Double = 0
    var clickFocus = ClickFocus()
    var currentRoute = PointerRoute.absolute
    var route = PointerRoute.absolute
    var tickWheel = 0
    var lastAbsolute: (x: Int32, y: Int32)? = (100, 100)
    var motionLock = NSLock()
    var carry = MotionCarry()
    var wheel = WheelAccumulator()
    func setMouseInUse(_ on: Bool) {}
    func refreshFocus(_ why: String) {}
    func syncKeys() {}
    func startTicker() {}
    func bumpTicker() {}
    var motionDeltas: [(Double, Double)] = []
    func logRaw(_ source: String, _ dx: Double, _ dy: Double) {}
    func postMotion(_ dx: Double, _ dy: Double) { motionDeltas.append((dx, dy)) }
    func log(_ line: String) {}
    func noteUIKitPointer() {}
    func pointerHovered(at p: CGPoint, in view: UIView, inside: Bool) {
        lastAbsolute = (Int32(p.x), Int32(p.y))
    }
'''

tests = r'''
func edges() -> [UInt32] { packets.map { $0.flags & ~UInt32(0x8001) } }
func clear() { packets.removeAll() }
func fresh() -> HardwareInput {
    clear(); InputSettings.shared.mouseMode = true; TestClock.now = 10
    return HardwareInput()
}
func settle(_ input: HardwareInput, _ t: UITouch) {
    TestClock.now += 0.060
    input.resolveCompatibilityClick(ObjectIdentifier(t))
}
func touch(_ input: HardwareInput, _ t: UITouch, _ phase: HardwareInput.TouchPhase,
           _ mask: UIEvent.ButtonMask = [], others: Set<UITouch> = []) -> Bool {
    switch phase {
    case .began: t.phase = .began
    case .moved: t.phase = .moved
    case .ended: t.phase = .ended
    case .cancelled: t.phase = .cancelled
    }
    return input.interceptTouches([t], UIEvent(mask, others.union([t])), phase)
}

// iPad pointer: an up with an empty mask must still end the consumed contact.
do {
    let input = fresh(), t = UITouch()
    assert(touch(input, t, .began, .primary))
    assert(input.gameButtons == [.left] && edges() == [2])
    assert(touch(input, t, .ended))
    assert(input.gameButtons.isEmpty && edges() == [2, 4])
    assert(input.fingerTouches(in: [t]).isEmpty)
}

// Pointer compatibility: a maskless contact clicks without any GC buttons.
do {
    let input = fresh(), t = UITouch()
    assert(touch(input, t, .began))
    assert(touch(input, t, .ended))
    assert(edges() == [2, 4])
}

// Observer and responder delivery of the same contact must emit one click.
do {
    let input = fresh(), t = UITouch()
    assert(touch(input, t, .began, .secondary))
    assert(touch(input, t, .began, .secondary))
    assert(touch(input, t, .ended))
    assert(touch(input, t, .ended))
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// iPhone AssistiveTouch: motion-only GC cannot disable synthesized clicks.
do {
    let input = fresh(), t = UITouch(.direct, radius: 0)
    input.mouseActive = true
    input.gcDeltaSeen = true
    assert(touch(input, t, .began))
    assert(packets.isEmpty)
    settle(input, t)
    assert(touch(input, t, .moved))
    t.majorRadius = 20 // The consumed contact keeps its identity through release.
    assert(touch(input, t, .ended))
    assert(edges() == [2, 4] && !input.gcButtonSeen)
}

// A maskless AssistiveTouch echo of a GC right click must never invent left.
do {
    let input = fresh(), echo = UITouch(.direct, radius: 0)
    input.lastGCButtonAt = 10
    input.buttonChanged(.right, true, at: 10)
    assert(touch(input, echo, .began))
    assert(input.fingerTouches(in: [echo]).isEmpty)
    assert(input.gameButtons == [.right] && edges() == [8])
    input.buttonChanged(.right, false, at: 10)
    assert(touch(input, echo, .ended))
    settle(input, echo)
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// UIKit may arrive first: a following raw right edge wins before fallback fires.
do {
    let input = fresh(), echo = UITouch(.direct, radius: 0)
    assert(touch(input, echo, .began))
    assert(packets.isEmpty)
    TestClock.now += 0.020
    input.lastGCButtonAt = TestClock.now
    input.buttonChanged(.right, true, at: TestClock.now)
    settle(input, echo)
    assert(input.gameButtons == [.right] && edges() == [8])
    input.buttonChanged(.right, false, at: TestClock.now)
    assert(touch(input, echo, .ended))
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// A short compatibility tap resolves to a complete click, even after its up.
do {
    let input = fresh(), t = UITouch(.direct, radius: 0)
    assert(touch(input, t, .began))
    assert(touch(input, t, .ended))
    assert(packets.isEmpty)
    settle(input, t)
    assert(input.gameButtons.isEmpty && edges() == [2, 4])
}

// Cancellation or focus loss before the compatibility delay produces no click.
do {
    let input = fresh(), t = UITouch(.direct, radius: 0)
    assert(touch(input, t, .began))
    assert(touch(input, t, .cancelled))
    settle(input, t)
    assert(packets.isEmpty)
}
do {
    let input = fresh(), t = UITouch(.direct, radius: 0)
    assert(touch(input, t, .began))
    input.baseFocused = false
    input.releaseAll("focus lost")
    settle(input, t)
    assert(packets.isEmpty)
}

// Pointer cancellation releases its buttons while the independent GC hold survives.
do {
    let input = fresh(), t = UITouch()
    input.buttonChanged(.left, true, at: 10)
    assert(touch(input, t, .began, .secondary))
    assert(touch(input, t, .cancelled))
    assert(input.gameButtons == [.left] && edges() == [2, 8, 16])
    clear()
    input.buttonChanged(.left, false, at: 10)
    assert(input.gameButtons.isEmpty && edges() == [4])
}

// A fallback press received without focus stays blocked until physically released.
do {
    let input = fresh()
    input.baseFocused = false
    input.uikitButtons([.right])
    assert(packets.isEmpty)
    input.baseFocused = true
    input.uikitButtons([.right])
    assert(packets.isEmpty && input.gameButtons.isEmpty)
    input.uikitButtons([])
    input.uikitButtons([.right])
    input.uikitButtons([])
    assert(edges() == [8, 16])
}

// A real fingertip remains excluded in Mouse mode, including a mixed event.
do {
    let input = fresh(), finger = UITouch(.direct, radius: 20), pointer = UITouch()
    assert(touch(input, finger, .began))
    assert(packets.isEmpty)
    assert(input.fingerTouches(in: [finger]) == [finger])
    assert(input.interceptTouches([finger, pointer], UIEvent(.secondary, [finger, pointer]), .began))
    assert(input.fingerTouches(in: [finger, pointer]) == [finger])
    assert(input.gameButtons == [.right])
    assert(touch(input, pointer, .ended, others: [finger]))
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// Outside Mouse mode, mixed events pass only the true finger to touch controls.
do {
    let input = fresh(), finger = UITouch(.direct, radius: 20), pointer = UITouch()
    InputSettings.shared.mouseMode = false
    assert(!input.interceptTouches([finger, pointer], UIEvent(.secondary, [finger, pointer]), .began))
    assert(input.fingerTouches(in: [finger, pointer]) == [finger])
    assert(input.gameButtons == [.right] && edges() == [8])
    assert(!input.interceptTouches([finger], UIEvent(.secondary, [finger, pointer]), .moved))
    assert(input.fingerTouches(in: [finger, pointer]) == [finger])
    assert(edges() == [8]) // A shared mask cannot turn the changed finger into another click.
    assert(touch(input, pointer, .ended, others: [finger]))
    assert(input.fingerTouches(in: [finger, pointer]) == [finger])
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// Masked direct compatibility contacts can coexist with a real finger.
do {
    let input = fresh(), finger = UITouch(.direct, radius: 20), pointer = UITouch(.direct, radius: 0)
    InputSettings.shared.mouseMode = false
    assert(!input.interceptTouches([finger, pointer], UIEvent(.secondary, [finger, pointer]), .began))
    assert(input.fingerTouches(in: [finger, pointer]) == [finger])
    assert(input.gameButtons == [.right] && edges() == [8])
    assert(!input.interceptTouches([finger], UIEvent(.secondary, [finger, pointer]), .moved))
    assert(input.fingerTouches(in: [finger, pointer]) == [finger])
    assert(touch(input, pointer, .ended, others: [finger]))
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// UIKit left/right combinations and a release that still has a live pointer.
do {
    let input = fresh(), left = UITouch(), right = UITouch()
    assert(touch(input, left, .began, .primary))
    assert(touch(input, right, .began, [.primary, .secondary], others: [left]))
    assert(input.gameButtons == [.left, .right])
    assert(touch(input, left, .ended, .secondary, others: [right]))
    assert(input.gameButtons == [.right])
    assert(touch(input, right, .ended))
    assert(input.gameButtons.isEmpty && edges() == [2, 8, 4, 16])
}

// GC first: mirror transitions and a delayed whole UIKit click post nothing.
do {
    let input = fresh(), t = UITouch()
    input.buttonChanged(.left, true, at: 10)
    assert(touch(input, t, .began, .primary))
    assert(touch(input, t, .ended))
    assert(input.gameButtons == [.left] && edges() == [2])
    input.buttonChanged(.left, false, at: 10)
    assert(touch(input, t, .began, .primary))
    assert(touch(input, t, .ended))
    assert(input.gameButtons.isEmpty && edges() == [2, 4])
}

// UIKit first: GC claims the same held button without another down or up.
do {
    let input = fresh(), t = UITouch()
    assert(touch(input, t, .began, .secondary))
    input.buttonChanged(.right, true, at: 10)
    assert(touch(input, t, .ended))
    assert(input.gameButtons == [.right] && edges() == [8])
    input.buttonChanged(.right, false, at: 10)
    assert(input.gameButtons.isEmpty && edges() == [8, 16])
}

// Each button has its own owner: GC left can coexist with UIKit right.
do {
    let input = fresh(), t = UITouch()
    input.buttonChanged(.left, true, at: 10)
    assert(touch(input, t, .began, .secondary))
    assert(input.gameButtons == [.left, .right])
    assert(touch(input, t, .ended))
    assert(input.gameButtons == [.left] && edges() == [2, 8, 16])
    input.buttonChanged(.left, false, at: 10)
    assert(input.gameButtons.isEmpty && edges() == [2, 8, 16, 4])
}

// Cancellation releases a fallback click; focus loss releases both sources.
do {
    let input = fresh(), t = UITouch(.direct, radius: 0)
    assert(touch(input, t, .began))
    settle(input, t)
    assert(touch(input, t, .cancelled))
    assert(input.gameButtons.isEmpty && edges() == [2, 4])
    clear()
    input.buttonChanged(.left, true, at: 10)
    input.uikitButtons([.right])
    input.baseFocused = false
    input.releaseAll("focus lost")
    assert(input.gameButtons.isEmpty && edges() == [2, 8, 4, 16])
    clear()
    input.buttonChanged(.left, false, at: 10)
    input.uikitButtons([.left, .right])
    assert(packets.isEmpty)
    input.baseFocused = true
    input.uikitButtons([.left, .right])
    assert(packets.isEmpty) // GC ownership survives focus loss; its echo stays ignored.
    input.uikitButtons([.right])
    assert(packets.isEmpty) // The blocked fallback hold also waits for a physical release.
    input.uikitButtons([])
    input.uikitButtons([.right])
    input.uikitButtons([])
    assert(edges() == [8, 16])
}

// Source reset on disconnect permits fallback when the GC stream disappears.
do {
    var sources = MouseButtonSources()
    sources.setGC(.right, pressed: true)
    sources.releaseAll()
    sources.setPointer([.right])
    assert(sources.wanted.isEmpty)
    sources.reset()
    sources.setPointer([.right])
    assert(sources.wanted == [.right])
}

// Raw buttons alone do not take ownership of UIKit motion or the wheel.
do {
    let input = fresh()
    input.currentRoute = .relative
    input.buttonChanged(.right, true, at: 10)
    clear()
    input.uikitMoved(3, -2, src: "test")
    input.uikitScroll(0, 14)
    assert(input.motionDeltas.count == 1 && input.motionDeltas[0].0 == 3 && input.motionDeltas[0].1 == -2)
    assert(edges() == [0x0800] && packets[0].data == 120)
    assert(!input.gcScrollLive)
}

// Raw motion alone suppresses duplicate motion, but UIKit still carries scroll.
do {
    let input = fresh()
    input.currentRoute = .relative
    input.gcDeltaSeen = true
    input.uikitMoved(3, -2, src: "test")
    input.uikitScroll(14, 0)
    assert(input.motionDeltas.isEmpty)
    assert(edges() == [0x1000] && packets[0].data == 120)
}

// A zero raw wheel sample does not claim ownership; a real one ignores echoes.
do {
    let input = fresh()
    input.scrolled(0, 0)
    input.uikitScroll(0, 14)
    assert(!input.gcScrollLive && edges() == [0x0800])
    clear()
    input.scrolled(0, 1)
    input.uikitScroll(0, 14)
    input.scrolled(1, 0)
    input.uikitScroll(14, 0)
    assert(input.gcScrollLive && edges() == [0x0800, 0x1000])
}

// Raw wheel takeover starts its own fraction, never mixing a fallback echo.
do {
    let input = fresh()
    input.uikitScroll(0, 7)
    assert(packets.isEmpty)
    input.scrolled(0, 0.5)
    input.uikitScroll(0, 7)
    assert(packets.isEmpty && input.wheel.y == 0.5)
    input.scrolled(0, 0.5)
    assert(edges() == [0x0800])
}

// Focus loss keeps raw ownership; disconnect restores independent fallbacks.
do {
    let input = fresh()
    input.currentRoute = .relative
    input.gcDeltaSeen = true
    input.gcDeltaLive = true
    input.scrolled(0, 1)
    input.baseFocused = false
    input.route = .blocked
    input.releaseAll("focus lost")
    clear()
    input.uikitScroll(0, 14)
    input.baseFocused = true
    input.route = .relative
    input.uikitMoved(3, -2, src: "test")
    input.uikitScroll(0, 14)
    assert(packets.isEmpty && input.motionDeltas.isEmpty)
    input.resetRawMouseSources()
    input.uikitMoved(3, -2, src: "test")
    input.uikitScroll(0, 14)
    assert(!input.gcDeltaSeen && !input.gcDeltaLive && !input.gcScrollLive)
    assert(input.motionDeltas.count == 1 && edges() == [0x0800])
}

print("PASS: actual mouse packet edges, pointer mask lifecycle, compatibility clicks, fingers, independent GC/UIKit button-motion-wheel arbitration, cancellation and focus releases")
'''

with tempfile.TemporaryDirectory(prefix='ideck-mouse-buttons-') as temp:
    temp = Path(temp)
    main, binary = temp / 'main.swift', temp / 'check'
    main.write_text(stubs + pure + glue_stubs + held + methods + '\n}\n' + tests,
                    encoding='utf-8')
    subprocess.run([os.environ.get('SWIFTC', 'swiftc'), str(main), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
