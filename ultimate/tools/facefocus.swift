import Foundation
import Vision
import AppKit
// usage: facefocus img1 img2 ...  -> "path<TAB>x%<TAB>y%<TAB>n" (top-left origin, % of the image)
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("\(path)\t-\t-\t0"); continue
    }
    let req = VNDetectFaceRectanglesRequest()
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    let faces = (req.results as? [VNFaceObservation]) ?? []
    guard !faces.isEmpty else { print("\(path)\t-\t-\t0"); continue }
    // the biggest face is the subject; Vision's origin is bottom-left
    let f = faces.max(by: { $0.boundingBox.height < $1.boundingBox.height })!.boundingBox
    let x = (f.midX) * 100
    let y = (1 - f.midY) * 100
    print(String(format: "%@\t%.1f\t%.1f\t%d", path, x, y, faces.count))
}
