"""Label every photo on a drive (Nature, People, Edited, Screenshots, ...) fully offline.

Images are decoded in memory, scored by a local CLIP model, and forgotten. Results go
only to a CSV on the drive itself; the console prints aggregate counts, never file names.
Moves nothing; plan.py reads the CSV to build Images\\<Label>\\<Year>.

    python classify.py --download             # one-time model download (needs internet)
    python classify.py --root E:\\ --limit 300  # quick trial on the first 300 photos
    python classify.py --root E:\\              # full run; resumable if interrupted
"""
import argparse
import csv
import os
import re
import sys
import time
from collections import Counter

MODEL, PRETRAINED = "ViT-B-16", "laion2b_s34b_b88k"

if "--download" not in sys.argv:
    os.environ["HF_HUB_OFFLINE"] = "1"   # never touch the network during classification
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

import torch  # noqa: E402
import open_clip  # noqa: E402
from PIL import Image, ImageFile  # noqa: E402

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = None
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# Each folder name maps to several descriptions; CLIP scores the photo against all of them.
PROMPTS = {
    "People": ["a photo of a person", "a photo of people", "a selfie", "a group photo of people",
               "a portrait photo of a face", "a photo of a child", "a photo of a family"],
    "Nature": ["a landscape photo of nature", "a photo of mountains", "a photo of the sea or a beach",
               "a photo of trees, a forest or a garden", "a photo of flowers or plants",
               "a photo of the sky, clouds or a sunset", "a photo of a desert", "a photo of a river or lake"],
    "Animals": ["a photo of an animal", "a photo of a cat", "a photo of a dog", "a photo of a bird",
                "a photo of a horse", "a photo of fish"],
    "Food": ["a photo of food", "a photo of a meal on a plate", "a photo of a drink or coffee", "a photo of a cake or dessert"],
    "City-Buildings": ["a photo of buildings", "a photo of a city street", "a photo of a mosque or a monument",
                       "a photo of the inside of a room or a house", "a photo of a car or a road"],
    "Documents": ["a photo of a document", "a photo of a paper page with text", "a scanned document",
                  "a photo of a receipt or an invoice", "a photo of an ID card or a certificate"],
    "Screenshots": ["a screenshot of a phone screen", "a screenshot of a computer screen",
                    "a screenshot of a chat conversation", "a screenshot of a website or an app"],
    "Graphics": ["a graphic design or a poster", "a meme with text", "a logo", "a cartoon or an illustration",
                 "a digital wallpaper", "a greeting card with text"],
}
CONFIDENCE = 0.40   # below this, the photo goes to Uncertain instead of a guess
MIN_SIDE = 200      # smaller images are icons / thumbnails / app cache

CLIP_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif"}
LABEL_BY_EXT = {".psd": "Edited", ".svg": "Graphics", ".ico": "Small-Icons",
                **{e: "Camera-RAW" for e in (".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2")}}
SKIP_DIRS = {"$recycle.bin", "system volume information", "organized", "found.000"}

SCREENSHOT_NAME = re.compile(r"screenshot|screen shot|skärmbild|capture d.?écran|لقطة|scr_|^screen_", re.I)
EDITORS = re.compile(r"photoshop|lightroom|snapseed|picsart|canva|gimp|facetune|vsco|affinity|"
                     r"pixelmator|photoroom|polarr|b612|meitu|faceapp|inshot|remini|luminar|capture one|"
                     r"paint\.net|fotor|prisma|lensa|retouch", re.I)


def edited_by_metadata(img):
    """True when an editing app wrote its name into the EXIF/XMP metadata."""
    try:
        software = str(img.getexif().get(0x0131, ""))   # EXIF 'Software' tag
        if EDITORS.search(software):
            return True
        xmp = img.info.get("xmp") or img.info.get("XML:com.adobe.xmp") or b""
        if isinstance(xmp, bytes):
            xmp = xmp[:20000].decode("utf-8", "ignore")
        return bool(EDITORS.search(xmp[:20000]))
    except Exception:
        return False


class Photos(torch.utils.data.Dataset):
    def __init__(self, paths, preprocess):
        self.paths, self.preprocess = paths, preprocess

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        path = self.paths[i]
        try:
            with Image.open(path) as img:
                if min(img.size) < MIN_SIDE:
                    return torch.zeros(3, 224, 224), i, "Small-Icons"
                if SCREENSHOT_NAME.search(os.path.basename(path)):
                    return torch.zeros(3, 224, 224), i, "Screenshots"
                if edited_by_metadata(img):
                    return torch.zeros(3, 224, 224), i, "Edited"
                img.draft("RGB", (448, 448))   # fast JPEG downscale while decoding
                return self.preprocess(img.convert("RGB")), i, ""
        except Exception:
            return torch.zeros(3, 224, 224), i, "Unreadable"


def find_photos(root):
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.normcase(dirpath) == os.path.normcase(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in CLIP_EXTS or ext in LABEL_BY_EXT:
                yield os.path.join(dirpath, name), ext


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--out", help="labels CSV (default: <root>\\Organized\\_labels\\photo-labels.csv)")
    ap.add_argument("--limit", type=int, default=0, help="only process this many new photos (trial run)")
    ap.add_argument("--download", action="store_true", help="download the model once, then exit")
    args = ap.parse_args()

    if args.download:
        open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
        print("Model downloaded. Classification now runs offline.")
        return

    root = os.path.abspath(args.root)
    out = args.out or os.path.join(root, "Organized", "_labels", "photo-labels.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8", newline="") as f:
            done = {row["Path"] for row in csv.DictReader(f)}

    counts = Counter()
    pending = []
    new_file = not os.path.exists(out)
    with open(out, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["Path", "Label", "Confidence"])
        for path, ext in find_photos(root):
            if path in done:
                continue
            if ext in LABEL_BY_EXT:
                writer.writerow([path, LABEL_BY_EXT[ext], ""])
                counts[LABEL_BY_EXT[ext]] += 1
            else:
                pending.append(path)
            if args.limit and len(pending) >= args.limit:
                break
    print(f"Photos to classify: {len(pending)}  (already done: {len(done)})")
    if not pending:
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED, device=device)
    model.eval()
    tokenizer = open_clip.get_tokenizer(MODEL)
    labels = list(PROMPTS)
    with torch.no_grad():
        text_feats = []
        for label in labels:
            t = model.encode_text(tokenizer(PROMPTS[label]).to(device))
            t = t / t.norm(dim=-1, keepdim=True)
            t = t.mean(dim=0)
            text_feats.append(t / t.norm())
        text_feats = torch.stack(text_feats)

    loader = torch.utils.data.DataLoader(Photos(pending, preprocess), batch_size=64,
                                         num_workers=6, pin_memory=device == "cuda")
    start = time.time()
    seen = 0
    with open(out, "a", encoding="utf-8", newline="") as f, torch.no_grad():
        writer = csv.writer(f)
        for images, idxs, preset in loader:
            need = [k for k, p in enumerate(preset) if not p]
            probs = None
            if need:
                feats = model.encode_image(images[need].to(device, non_blocking=True))
                feats = feats / feats.norm(dim=-1, keepdim=True)
                probs = (100 * feats @ text_feats.T).softmax(dim=-1).cpu()
            j = 0
            for k, (i, p) in enumerate(zip(idxs.tolist(), preset)):
                if p:
                    label, conf = p, ""
                else:
                    score, best = probs[j].max(dim=0)
                    j += 1
                    label = labels[best] if score >= CONFIDENCE else "Uncertain"
                    conf = f"{score:.2f}"
                writer.writerow([pending[i], label, conf])
                counts[label] += 1
            f.flush()
            seen += len(idxs)
            if seen % 5000 < len(idxs):
                rate = seen / (time.time() - start)
                print(f"... {seen}/{len(pending)}  ({rate:.0f} photos/s, ~{(len(pending) - seen) / rate / 60:.0f} min left)")

    print(f"\n=== Labels ({device}, {time.time() - start:.0f}s) ===")
    for label, n in counts.most_common():
        print(f"{label:16} {n}")
    print(f"Labels file (stays on the drive): {out}")


if __name__ == "__main__":
    main()
