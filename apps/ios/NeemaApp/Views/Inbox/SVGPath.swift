import SwiftUI

/// A small SVG path-data parser: enough for the web's own icon paths
/// (M/L/H/V/C/S/Q/T/A/Z, absolute and relative, implicit repeats), so a
/// channel glyph is the same shape on every platform.
enum SVGPath {
    static func path(_ d: String, in box: CGFloat = 24) -> Path {
        var p = Path()
        var tokens = tokenize(d)[...]
        var cmd: Character = "M"
        var cur = CGPoint.zero, start = CGPoint.zero, lastCtrl: CGPoint? = nil, lastQuad: CGPoint? = nil
        func num() -> CGFloat? {
            guard let t = tokens.first, case .number(let v) = t else { return nil }
            tokens = tokens.dropFirst()
            return v
        }
        func pt(_ rel: Bool) -> CGPoint? {
            guard let x = num(), let y = num() else { return nil }
            return rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y)
        }
        while let t = tokens.first {
            if case .command(let c) = t { cmd = c; tokens = tokens.dropFirst() }
            let rel = cmd.isLowercase
            switch cmd.uppercased() {
            case "M":
                guard let a = pt(rel) else { tokens = []; break }
                p.move(to: a); cur = a; start = a; lastCtrl = nil; lastQuad = nil
                cmd = rel ? "l" : "L"   // further pairs are line-tos
            case "L":
                guard let a = pt(rel) else { tokens = []; break }
                p.addLine(to: a); cur = a; lastCtrl = nil; lastQuad = nil
            case "H":
                guard let x = num() else { tokens = []; break }
                let a = CGPoint(x: rel ? cur.x + x : x, y: cur.y)
                p.addLine(to: a); cur = a; lastCtrl = nil; lastQuad = nil
            case "V":
                guard let y = num() else { tokens = []; break }
                let a = CGPoint(x: cur.x, y: rel ? cur.y + y : y)
                p.addLine(to: a); cur = a; lastCtrl = nil; lastQuad = nil
            case "C":
                guard let c1 = pt(rel), let c2 = pt(rel), let a = pt(rel) else { tokens = []; break }
                p.addCurve(to: a, control1: c1, control2: c2); cur = a; lastCtrl = c2; lastQuad = nil
            case "S":
                guard let c2 = pt(rel), let a = pt(rel) else { tokens = []; break }
                let c1 = lastCtrl.map { CGPoint(x: 2 * cur.x - $0.x, y: 2 * cur.y - $0.y) } ?? cur
                p.addCurve(to: a, control1: c1, control2: c2); cur = a; lastCtrl = c2; lastQuad = nil
            case "Q":
                guard let c1 = pt(rel), let a = pt(rel) else { tokens = []; break }
                p.addQuadCurve(to: a, control: c1); cur = a; lastQuad = c1; lastCtrl = nil
            case "T":
                guard let a = pt(rel) else { tokens = []; break }
                let c1 = lastQuad.map { CGPoint(x: 2 * cur.x - $0.x, y: 2 * cur.y - $0.y) } ?? cur
                p.addQuadCurve(to: a, control: c1); cur = a; lastQuad = c1; lastCtrl = nil
            case "A":
                guard let rx = num(), let ry = num(), let rot = num(), let large = num(), let sweep = num(), let a = pt(rel) else { tokens = []; break }
                arc(&p, from: cur, to: a, rx: rx, ry: ry, rotation: rot, large: large != 0, sweep: sweep != 0)
                cur = a; lastCtrl = nil; lastQuad = nil
            case "Z":
                p.closeSubpath(); cur = start; lastCtrl = nil; lastQuad = nil
            default:
                tokens = []
            }
        }
        return p
    }

    private enum Token { case command(Character), number(CGFloat) }

    private static func tokenize(_ d: String) -> [Token] {
        var out: [Token] = []
        var num = ""
        func flush() {
            if !num.isEmpty, let v = Double(num) { out.append(.number(CGFloat(v))) }
            num = ""
        }
        for ch in d {
            if ch.isLetter && ch != "e" && ch != "E" {
                flush(); out.append(.command(ch))
            } else if ch == "-" || ch == "+" {
                // A sign starts a new number unless it follows an exponent.
                if let last = num.last, last != "e", last != "E" { flush() }
                num.append(ch)
            } else if ch == "." {
                // "1.5.5" is two numbers: 1.5 and .5
                if num.contains(".") && !num.contains("e") && !num.contains("E") { flush() }
                num.append(ch)
            } else if ch.isNumber || ch == "e" || ch == "E" {
                num.append(ch)
            } else {
                flush()
            }
        }
        flush()
        return out
    }

    /// An SVG elliptical arc as cubic béziers (the endpoint-to-centre conversion of the SVG spec, appendix B.2.4).
    private static func arc(_ p: inout Path, from p1: CGPoint, to p2: CGPoint, rx rx0: CGFloat, ry ry0: CGFloat, rotation: CGFloat, large: Bool, sweep: Bool) {
        if p1 == p2 { return }
        var rx = abs(rx0), ry = abs(ry0)
        if rx == 0 || ry == 0 { p.addLine(to: p2); return }
        let phi = rotation * .pi / 180
        let cosPhi = cos(phi), sinPhi = sin(phi)
        let dx = (p1.x - p2.x) / 2, dy = (p1.y - p2.y) / 2
        let x1p = cosPhi * dx + sinPhi * dy
        let y1p = -sinPhi * dx + cosPhi * dy
        var lambda = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
        if lambda > 1 { lambda = sqrt(lambda); rx *= lambda; ry *= lambda }
        let num = max(0, rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p)
        let den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
        var coef = den == 0 ? 0 : sqrt(num / den)
        if large == sweep { coef = -coef }
        let cxp = coef * (rx * y1p / ry)
        let cyp = coef * -(ry * x1p / rx)
        let cx = cosPhi * cxp - sinPhi * cyp + (p1.x + p2.x) / 2
        let cy = sinPhi * cxp + cosPhi * cyp + (p1.y + p2.y) / 2
        func angle(_ ux: CGFloat, _ uy: CGFloat, _ vx: CGFloat, _ vy: CGFloat) -> CGFloat {
            let dot = ux * vx + uy * vy
            let len = sqrt(ux * ux + uy * uy) * sqrt(vx * vx + vy * vy)
            var a = acos(max(-1, min(1, dot / len)))
            if ux * vy - uy * vx < 0 { a = -a }
            return a
        }
        let theta1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
        var delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
        if !sweep && delta > 0 { delta -= 2 * .pi }
        if sweep && delta < 0 { delta += 2 * .pi }
        let segments = max(1, Int(ceil(abs(delta) / (.pi / 2))))
        let step = delta / CGFloat(segments)
        var t = theta1
        for _ in 0..<segments {
            let t2 = t + step
            let alpha = sin(step) * (sqrt(4 + 3 * pow(tan(step / 2), 2)) - 1) / 3
            func point(_ a: CGFloat) -> CGPoint {
                let x = rx * cos(a), y = ry * sin(a)
                return CGPoint(x: cosPhi * x - sinPhi * y + cx, y: sinPhi * x + cosPhi * y + cy)
            }
            func deriv(_ a: CGFloat) -> CGPoint {
                let x = -rx * sin(a), y = ry * cos(a)
                return CGPoint(x: cosPhi * x - sinPhi * y, y: sinPhi * x + cosPhi * y)
            }
            let s = point(t), e = point(t2), ds = deriv(t), de = deriv(t2)
            let c1 = CGPoint(x: s.x + alpha * ds.x, y: s.y + alpha * ds.y)
            let c2 = CGPoint(x: e.x - alpha * de.x, y: e.y - alpha * de.y)
            p.addCurve(to: e, control1: c1, control2: c2)
            t = t2
        }
    }
}

/// The inbox's channel-tab glyphs — the web's own SVG paths (lib/channels.tsx
/// and the "All" sparkle in ConversationsView.tsx), 24×24, filled, tinted by the caller.
enum ChannelIcons {
    static let whatsApp = "M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"
    static let messenger = "M12 0C5.373 0 0 4.974 0 11.111c0 3.497 1.745 6.616 4.472 8.652V24l4.086-2.242c1.09.301 2.246.464 3.442.464 6.627 0 12-4.974 12-11.111C24 4.974 18.627 0 12 0zm1.191 14.963l-3.055-3.26-5.963 3.26L10.732 8l3.131 3.26L19.752 8l-6.561 6.963z"
    static let facebook = "M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"
    static let instagram = "M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"
    /// The "All" tab (ConversationsView.tsx SparkleIcon).
    static let sparkle = "M12 2l1.9 5.6L19.5 9l-5.6 1.9L12 16.5 10.1 10.9 4.5 9l5.6-1.4L12 2zm6.5 11l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6z"

    static func of(_ channel: String) -> String? {
        switch channel {
        case "all": return sparkle
        case "whatsapp": return whatsApp
        case "messenger": return messenger
        case "facebook": return facebook
        case "instagram": return instagram
        default: return nil
        }
    }
}

/// One of the web's 24×24 icon paths, filled with the current tint, at `size` points.
struct SVGIcon: View {
    let d: String
    var size: CGFloat = 14
    var body: some View {
        SVGShape(d: d).fill(style: FillStyle(eoFill: true)).frame(width: size, height: size)
    }
}

struct SVGShape: Shape {
    let d: String
    func path(in rect: CGRect) -> Path {
        let p = SVGPath.path(d)
        let s = min(rect.width, rect.height) / 24
        return p.applying(CGAffineTransform(scaleX: s, y: s).translatedBy(x: rect.minX / max(s, 0.0001), y: rect.minY / max(s, 0.0001)))
    }
}
