// Draws the two layers of SuperMarioGalaxy.icon (guglis/README.md, "App-Icon"):
// - background.png: the centre of the Hubble image of the Pinwheel Galaxy (M101), cropped square,
//   tinted towards deep blue and darkened towards the edges.
//   Image: ESA/Hubble, CC BY 4.0, https://commons.wikimedia.org/wiki/File:M101_hires_STScI-PRC2006-10a.jpg
//   (the 3840 px rendering of that file).
// - foreground.png: a golden five-pointed star with rounded points, drawn here.
// usage: swift make_layers.swift <M101 jpg> <output Assets dir>
import AppKit

let args = CommandLine.arguments
let size = 1024

func canvas() -> (NSBitmapImageRep, CGContext) {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = context
    return (rep, context.cgContext)
}

func save(_ rep: NSBitmapImageRep, _ name: String) {
    try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(args[2])/\(name)"))
}

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: r, green: g, blue: b, alpha: a)
}

// Background: a 2600 px square around the galaxy's core (1877, 1494 in the 3840 x 3002 image).
do {
    let source = NSBitmapImageRep(data: try! Data(contentsOf: URL(fileURLWithPath: args[1])))!.cgImage!
    let side = 2600.0, coreX = 1877.0, coreY = 1494.0
    let crop = source.cropping(to: CGRect(x: coreX - side / 2, y: coreY - side / 2, width: side, height: side))!
    NSGraphicsContext.saveGraphicsState()
    let (rep, cg) = canvas()
    let full = CGRect(x: 0, y: 0, width: size, height: size)
    cg.interpolationQuality = .high
    cg.draw(crop, in: full)
    // Deep blue tint over the dark sky, then a vignette towards the edges.
    cg.setBlendMode(.color)
    cg.setFillColor(rgb(0.10, 0.18, 0.62, 0.35))
    cg.fill(full)
    cg.setBlendMode(.normal)
    let centre = CGPoint(x: size / 2, y: size / 2)
    let vignette = CGGradient(colorsSpace: nil, colors: [rgb(0.02, 0.03, 0.12, 0), rgb(0.02, 0.03, 0.12, 0.75)] as CFArray,
                              locations: [0.45, 1.0])!
    cg.drawRadialGradient(vignette, startCenter: centre, startRadius: 0, endCenter: centre, endRadius: CGFloat(size) * 0.72,
                          options: [.drawsAfterEndLocation])
    NSGraphicsContext.restoreGraphicsState()
    save(rep, "background.png")
}

// Foreground: the star, one point up. Stroking the outline with round joins rounds the points.
do {
    NSGraphicsContext.saveGraphicsState()
    let (rep, cg) = canvas()
    let centre = CGPoint(x: Double(size) / 2, y: Double(size) / 2 - 18)
    let outer = 330.0, inner = 175.0, rounding = 70.0
    let star = CGMutablePath()
    for i in 0..<10 {
        let radius = i % 2 == 0 ? outer : inner
        let angle = Double.pi / 2 + Double(i) * Double.pi / 5
        let point = CGPoint(x: centre.x + radius * cos(angle), y: centre.y + radius * sin(angle))
        if i == 0 { star.move(to: point) } else { star.addLine(to: point) }
    }
    star.closeSubpath()
    let shape = star.union(star.copy(strokingWithWidth: rounding, lineCap: .round, lineJoin: .round, miterLimit: 1))

    cg.saveGState()
    cg.addPath(shape)
    cg.clip()
    let gold = CGGradient(colorsSpace: nil, colors: [rgb(1.0, 0.93, 0.42), rgb(1.0, 0.80, 0.16), rgb(0.96, 0.58, 0.08)] as CFArray,
                          locations: [0, 0.55, 1])!
    cg.drawLinearGradient(gold, start: CGPoint(x: centre.x, y: centre.y + outer + 40), end: CGPoint(x: centre.x, y: centre.y - outer),
                          options: [])
    cg.restoreGState()
    NSGraphicsContext.restoreGraphicsState()
    save(rep, "foreground.png")
}
