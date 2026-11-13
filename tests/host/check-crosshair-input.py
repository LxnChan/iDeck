#!/usr/bin/env python3
"""Exercise production touch handlers with scripted UIKit touches and a fake clock.

Runs without an iOS SDK on a Swift host. The harness extracts the actual
MetalBackedView trackpad/Crosshair methods, substitutes only platform services,
and captures Wine packets. --source-only checks wiring without a Swift compiler;
it does not replace the executable checks or a device/game acceptance test.
"""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'app/Madeira/ContentView.swift').read_text(encoding='utf-8')
library = (root / 'app/Madeira/Library.swift').read_text(encoding='utf-8')
start = source.index('    // S2 desktop mode: trackpad-style pointer.')
trackpad = source[start:source.index('\n}\n\n/// Arrow-key', start)]
reset_start = source.index('    func resetTouchState() {')
reset = source[reset_start:source.index('\n    }', reset_start) + 6]
gate_start = source.index('    static func suppressing(touchpad: Bool, desktop: Bool) -> Bool {')
gate_policy = source[gate_start:source.index('\n    }', gate_start) + 6]
assert trackpad.count('guard desktopMode || InputSettings.shared.relative else {') == 4
for phase in ('Began', 'Moved', 'Ended', 'Cancelled'):
    assert f'override func touches{phase}' in trackpad
assert 'if !input.touchMode {' in library[library.index('struct LibraryPointerSettings:'):]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true')
args = parser.parse_args()
if args.source_only:
    print('PASS: Crosshair reaches every production touch phase and exposes hold delay (source checks only)')
    raise SystemExit(0)

stubs = r'''
import Foundation
#if canImport(CoreGraphics)
import CoreGraphics
#endif
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

struct Packet: Equatable {
    var x: Int32, y: Int32, flags: UInt32, data: UInt32
    var kind = "mouse"
}
var packets: [Packet] = []
func winios_pointer(_ x: Int32, _ y: Int32, _ flags: UInt32, _ data: UInt32) {
    packets.append(Packet(x: x, y: y, flags: flags, data: data))
}
func winios_screen_size(_ x: inout Int32, _ y: inout Int32) { x = 1920; y = 1080 }
func winios_post_touch_down(_ x: Int32, _ y: Int32) { packets.append(Packet(x: x, y: y, flags: 2, data: 0, kind: "touch")) }
func winios_post_touch_move(_ x: Int32, _ y: Int32) { packets.append(Packet(x: x, y: y, flags: 1, data: 0, kind: "touch")) }
func winios_post_touch_up(_ x: Int32, _ y: Int32) { packets.append(Packet(x: x, y: y, flags: 4, data: 0, kind: "touch")) }

enum TestClock { static var now: Double = 10 }
struct Date { var timeIntervalSinceReferenceDate: Double { TestClock.now } }
struct Deadline {
    var time: Double
    static func now() -> Deadline { Deadline(time: TestClock.now) }
    static func + (lhs: Deadline, rhs: Double) -> Deadline { Deadline(time: lhs.time + rhs) }
}
final class DispatchQueue {
    static let main = DispatchQueue()
    var work: [(time: Double, run: () -> Void)] = []
    func asyncAfter(deadline: Deadline, execute: @escaping () -> Void) {
        work.append((deadline.time, execute))
    }
    func advance(_ interval: Double) {
        let end = TestClock.now + interval
        while let next = work.indices.min(by: { work[$0].time < work[$1].time }), work[next].time <= end {
            let item = work.remove(at: next)
            TestClock.now = item.time
            item.run()
        }
        TestClock.now = end
    }
}
func fputs(_ text: String, _ sink: Int) {}
let stderr = 0
final class UIImpactFeedbackGenerator {
    enum Style { case medium }
    init(style: Style) {}
    func impactOccurred() {}
}
class UIView {
    var superview: UIView?
    func isDescendant(of view: UIView) -> Bool {
        self === view || superview?.isDescendant(of: view) == true
    }
    func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {}
    func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {}
    func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {}
    func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {}
}
final class UITouch: Hashable {
    enum Phase { case began, moved, ended, cancelled }
    enum Kind { case direct, indirectPointer }
    var phase: Phase = .began
    var type: Kind = .direct
    var view: UIView?
    var point: CGPoint
    init(_ x: Double = 100, _ y: Double = 100) { point = CGPoint(x: x, y: y) }
    func location(in view: UIView) -> CGPoint { point }
    static func == (a: UITouch, b: UITouch) -> Bool { a === b }
    func hash(into hasher: inout Hasher) { hasher.combine(ObjectIdentifier(self)) }
}
final class UIEvent {
    var allTouches: Set<UITouch>?
    init(_ touches: Set<UITouch>) { allTouches = touches }
}
final class InputSettings {
    static let shared = InputSettings()
    var relative = true, mouseMode = false, touchMode = false
    var sensRel = 2.0, sensAbs = 2.0, longPressDelay = 0.25
}
final class HardwareInput {
    enum TouchPhase { case began, moved, ended, cancelled }
    static let shared = HardwareInput()
    var mouseConnected = false, intercepted = false
    func interceptTouches(_ touches: Set<UITouch>, _ event: UIEvent?, _ phase: TouchPhase) -> Bool { intercepted }
    func fingerTouches(in touches: Set<UITouch>) -> Set<UITouch> { touches }
}
enum TouchMouseGate {
    enum Mode { case auto, on, off }
    static var mode: Mode = .auto
    static var padOverlay = false
GATE_POLICY
}
final class MetalBackedView: UIView {
    var tmResolved = false
    var tmDragTouch: UITouch?
    var touchModeCalls = 0
    private var touchPointerMode: Bool { InputSettings.shared.touchMode }
    private func tmResetGesture() { tmResolved = false; tmDragTouch = nil }
    private func mapTouch(_ t: UITouch) -> (Int32, Int32) { mapPoint(t.point) }
    private func mapPoint(_ p: CGPoint) -> (Int32, Int32) { (Int32(p.x), Int32(p.y)) }
    private func touchModeBegan(_ touches: Set<UITouch>) { touchModeCalls += 1 }
    private func touchModeMoved(_ touches: Set<UITouch>, _ event: UIEvent?) { touchModeCalls += 1 }
    private func touchModeEnded(_ touches: Set<UITouch>, _ event: UIEvent?) { touchModeCalls += 1 }
    private func touchModeCancelled(_ touches: Set<UITouch>) { touchModeCalls += 1 }
'''

tests = r'''
func fresh(relative: Bool = true) -> MetalBackedView {
    DispatchQueue.main.work.removeAll()
    TestClock.now = 10
    packets.removeAll()
    InputSettings.shared.relative = relative
    InputSettings.shared.touchMode = false
    InputSettings.shared.mouseMode = false
    InputSettings.shared.sensRel = 2
    HardwareInput.shared.intercepted = false
    TouchMouseGate.mode = .auto
    TouchMouseGate.padOverlay = false
    MetalBackedView.cursor = CGPoint(x: 1919, y: 1079)
    return MetalBackedView()
}
func begin(_ v: MetalBackedView, _ t: UITouch, others: Set<UITouch> = []) {
    t.view = v; t.phase = .began; v.touchesBegan([t], with: UIEvent(others.union([t])))
}
func move(_ v: MetalBackedView, _ t: UITouch, x: Double, y: Double, others: Set<UITouch> = []) {
    t.point = CGPoint(x: x, y: y); t.phase = .moved
    v.touchesMoved([t], with: UIEvent(others.union([t])))
}
func end(_ v: MetalBackedView, _ t: UITouch, others: Set<UITouch> = []) {
    t.phase = .ended; v.touchesEnded([t], with: UIEvent(others.union([t])))
}
func cancel(_ v: MetalBackedView, _ t: UITouch) {
    t.phase = .cancelled; v.touchesCancelled([t], with: UIEvent([t]))
}
func flagCount(_ flag: UInt32) -> Int { packets.filter { $0.flags & flag != 0 }.count }
func relativeOnly() { assert(packets.allSatisfy { $0.kind == "mouse" && $0.flags & 0x8000 == 0 }) }

for desktop in [false, true] {
    if desktop { setenv("MADEIRA_DESKTOP", "1", 1) } else { unsetenv("MADEIRA_DESKTOP") }

    // Motion reaches the relative branch in both session types, preserves
    // sign/fractional carry, and never clips at the cached desktop edge.
    var v = fresh(); var t = UITouch(); InputSettings.shared.sensRel = 0.5
    begin(v, t); move(v, t, x: 130, y: 85); move(v, t, x: 131, y: 84)
    assert(packets == [Packet(x: 15, y: -7, flags: 1, data: 0), Packet(x: 0, y: -1, flags: 1, data: 0)])
    assert(MetalBackedView.cursor == CGPoint(x: 1919, y: 1079))
    end(v, t); DispatchQueue.main.advance(1); relativeOnly(); assert(flagCount(2) == 0)

    // Small deltas accumulate; a lift/reset never lends carry to a new pan.
    v = fresh(); t = UITouch(); InputSettings.shared.sensRel = 0.25
    begin(v, t)
    for i in 1...4 { move(v, t, x: 100 + Double(i), y: 100) }
    assert(packets == [Packet(x: 1, y: 0, flags: 1, data: 0)])
    cancel(v, t); packets.removeAll(); t = UITouch(); begin(v, t)
    move(v, t, x: 101, y: 100); assert(packets.isEmpty); cancel(v, t)

    // A tap clicks without motion. Its delayed release stays flags-only
    // even if the pointer mode changes before the release executes.
    v = fresh(); t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.05); end(v, t)
    assert(packets == [Packet(x: 0, y: 0, flags: 2, data: 0)])
    InputSettings.shared.relative = false; DispatchQueue.main.advance(0.03)
    assert(packets.last == Packet(x: 0, y: 0, flags: 4, data: 0))

    // Two taps inside the pulse interval remain DOWN/UP/DOWN/UP; the
    // superseded timer cannot release the second press.
    v = fresh(); t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.001); end(v, t)
    t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.001); end(v, t)
    assert(packets.map { $0.flags } == [2, 4, 2])
    DispatchQueue.main.advance(0.024)
    assert(packets.map { $0.flags } == [2, 4, 2])
    DispatchQueue.main.advance(0.002)
    assert(packets.map { $0.flags } == [2, 4, 2, 4]); relativeOnly()

    // A deliberate stationary hold presses left, supports aiming while held,
    // and releases once on lift or cancellation.
    v = fresh(); t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.25)
    move(v, t, x: 120, y: 100); end(v, t)
    assert(packets == [Packet(x: 0, y: 0, flags: 2, data: 0), Packet(x: 40, y: 0, flags: 1, data: 0), Packet(x: 0, y: 0, flags: 4, data: 0)])
    relativeOnly()
    v = fresh(); t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.25); cancel(v, t)
    assert(flagCount(2) == 1 && flagCount(4) == 1); relativeOnly()

    // Reset both invalidates an armed timer and balances an existing hold.
    v = fresh(); t = UITouch(); begin(v, t); v.resetTouchState(); DispatchQueue.main.advance(1)
    assert(packets.isEmpty)
    v = fresh(); t = UITouch(); begin(v, t); v.resetTouchState()
    move(v, t, x: 120, y: 100); end(v, t); DispatchQueue.main.advance(1)
    assert(packets.isEmpty)   // phases from before focus loss cannot resume aiming/clicking
    v = fresh(); t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.25)
    InputSettings.shared.relative = false; v.resetTouchState()
    assert(packets == [Packet(x: 0, y: 0, flags: 2, data: 0), Packet(x: 0, y: 0, flags: 4, data: 0)])

    // Reset releases an unfinished tap, and its old timer cannot release
    // a new tap or hold. A stale ended/cancelled touch cannot arm a hold.
    v = fresh(); t = UITouch(); begin(v, t); DispatchQueue.main.advance(0.001); end(v, t)
    v.resetTouchState(); t = UITouch(); begin(v, t)
    DispatchQueue.main.advance(0.25)
    assert(packets.map { $0.flags } == [2, 4, 2])
    end(v, t); assert(packets.map { $0.flags } == [2, 4, 2, 4])
    v = fresh(); t = UITouch(); begin(v, t); t.phase = .ended
    DispatchQueue.main.advance(1); assert(packets.isEmpty)
    v = fresh(); t = UITouch(); begin(v, t); t.phase = .cancelled
    DispatchQueue.main.advance(1); assert(packets.isEmpty)

    // Two-finger tap is right-click; two-finger motion is wheel input.
    v = fresh(); t = UITouch(); var second = UITouch(140, 100)
    begin(v, t); begin(v, second, others: [t]); DispatchQueue.main.advance(0.05)
    end(v, t, others: [second]); end(v, second); DispatchQueue.main.advance(0.03)
    assert(packets == [Packet(x: 0, y: 0, flags: 8, data: 0), Packet(x: 0, y: 0, flags: 16, data: 0)])
    relativeOnly()
    v = fresh(); t = UITouch(); second = UITouch(140, 100)
    begin(v, t); begin(v, second, others: [t]); second.point.y = 114
    move(v, t, x: 100, y: 114, others: [second]); end(v, t, others: [second]); end(v, second)
    assert(packets == [Packet(x: 0, y: 0, flags: 0x800, data: 120)]); relativeOnly()

    // Cumulative slow motion and horizontal motion are drags, even when
    // every individual delta is small. A third finger cannot restore tap.
    v = fresh(); t = UITouch(); second = UITouch(140, 100)
    begin(v, t); begin(v, second, others: [t])
    for i in 1...14 {
        second.point.y = 100 + Double(i)
        move(v, t, x: 100, y: 100 + Double(i), others: [second])
    }
    end(v, t, others: [second]); end(v, second); DispatchQueue.main.advance(0.03)
    assert(flagCount(0x800) == 1 && flagCount(8) == 0)
    v = fresh(); t = UITouch(); second = UITouch(140, 100)
    begin(v, t); begin(v, second, others: [t]); second.point.x = 160
    move(v, t, x: 120, y: 100, others: [second])
    end(v, t, others: [second]); end(v, second); DispatchQueue.main.advance(0.03)
    assert(packets.isEmpty)
    v = fresh(); t = UITouch(); second = UITouch(140, 100)
    begin(v, t); begin(v, second, others: [t]); second.point.y = 114
    move(v, t, x: 100, y: 114, others: [second])
    let third = UITouch(120, 114); begin(v, third, others: [t, second])
    end(v, third, others: [t, second]); end(v, t, others: [second]); end(v, second)
    DispatchQueue.main.advance(0.03)
    assert(flagCount(0x800) == 1 && flagCount(8) == 0)

    // Adding a second finger ends an existing hold and cannot strand left
    // or turn that held gesture into a right-click.
    v = fresh(); t = UITouch(); second = UITouch(140, 100)
    begin(v, t); DispatchQueue.main.advance(0.25); begin(v, second, others: [t])
    end(v, t, others: [second]); end(v, second); DispatchQueue.main.advance(1)
    assert(flagCount(2) == 1 && flagCount(4) == 1 && flagCount(8) == 0)

    // A camera pan crossing tap slop never fires when it pauses or lifts.
    v = fresh(); t = UITouch(); begin(v, t); move(v, t, x: 112, y: 100)
    DispatchQueue.main.advance(0.5); end(v, t); assert(flagCount(2) == 0)
    v = fresh(); t = UITouch(); begin(v, t); cancel(v, t); DispatchQueue.main.advance(1)
    assert(packets.isEmpty)

    // Selecting Crosshair is an explicit request for touch mouse input,
    // including when a controller overlay is visible. A held control finger
    // belongs to its own view and must not convert aiming into scrolling.
    v = fresh(); t = UITouch(); TouchMouseGate.padOverlay = true
    let control = UITouch(20, 300); control.view = UIView()
    begin(v, t, others: [control]); move(v, t, x: 120, y: 115, others: [control])
    end(v, t, others: [control]); DispatchQueue.main.advance(1)
    assert(packets == [Packet(x: 40, y: 30, flags: 1, data: 0)])
    v = fresh(); t = UITouch(); TouchMouseGate.padOverlay = true
    begin(v, t, others: [control]); DispatchQueue.main.advance(0.05)
    end(v, t, others: [control]); DispatchQueue.main.advance(0.03)
    assert(packets.map { $0.flags } == [2, 4]); relativeOnly()

    // The explicit off setting still suppresses Crosshair. A touch that
    // began while disabled cannot join a new gesture when the gate changes.
    v = fresh(); t = UITouch(); TouchMouseGate.mode = .off
    begin(v, t); move(v, t, x: 120, y: 100); end(v, t); DispatchQueue.main.advance(1)
    assert(packets.isEmpty)
    v = fresh(); let swallowed = UITouch(); TouchMouseGate.mode = .off
    begin(v, swallowed); TouchMouseGate.mode = .auto; t = UITouch(140, 100)
    begin(v, t, others: [swallowed]); move(v, t, x: 160, y: 100, others: [swallowed])
    end(v, t, others: [swallowed]); end(v, swallowed); DispatchQueue.main.advance(1)
    assert(packets == [Packet(x: 40, y: 0, flags: 1, data: 0)])

    // Direct-touch precedence and hardware interception are preserved.
    v = fresh(); t = UITouch(); InputSettings.shared.touchMode = true
    begin(v, t); move(v, t, x: 120, y: 100); end(v, t)
    assert(v.touchModeCalls == 3 && packets.isEmpty)
    v = fresh(); t = UITouch(); HardwareInput.shared.intercepted = true
    begin(v, t); move(v, t, x: 120, y: 100); end(v, t); DispatchQueue.main.advance(1)
    assert(packets.isEmpty)
}

// Existing non-Crosshair direct touches and desktop trackpad still route
// through their own APIs/absolute coordinates.
unsetenv("MADEIRA_DESKTOP")
var v = fresh(relative: false), t = UITouch()
TouchMouseGate.padOverlay = true
begin(v, t); end(v, t); DispatchQueue.main.advance(1)
assert(packets.isEmpty)   // the auto gate still protects controller-only games
v = fresh(relative: false); t = UITouch()
begin(v, t); DispatchQueue.main.advance(0.05); end(v, t); DispatchQueue.main.advance(0.03)
assert(packets.count == 2 && packets.allSatisfy { $0.kind == "touch" && $0.x == 100 && $0.y == 100 })
setenv("MADEIRA_DESKTOP", "1", 1)
v = fresh(relative: false); t = UITouch(); begin(v, t); move(v, t, x: 80, y: 90)
assert(packets == [Packet(x: 1879, y: 1059, flags: 0x8001, data: 0)])
cancel(v, t)
print("PASS: production Crosshair handlers in desktop/direct sessions: relative motion, carry, taps, holds, wheel, balanced release/reset and routing precedence")
'''

with tempfile.TemporaryDirectory(prefix='ideck-crosshair-') as directory:
    directory = Path(directory)
    swift = directory / 'main.swift'
    executable = directory / ('check.exe' if os.name == 'nt' else 'check')
    swift.write_text(stubs.replace('GATE_POLICY', gate_policy) + reset + '\n' + trackpad + '\n}\n' + tests, encoding='utf-8')
    subprocess.run([os.environ.get('SWIFTC', 'swiftc'), str(swift), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
