"""Plan and carry out a context-aware reorganization of a drive or folder.

Folders that only make sense as a whole are moved whole; everything else file by file.
Rules, checked from the top of the tree down; the first that matches wins:
  1. Private   name means "private" in some language    -> Private\\<name>   (folders and files)
  2. Apps      program/game folder or code repository    -> Programs\\Apps\\<name>
  3. Albums    named folder of mostly photos/videos       -> Albums\\<year>\\<name>
  4. Folders   named folder mixing documents with media   -> Folders\\<name>  (a course, a project)
  5. Files     <Type>\\<Year>, photos by label; subtitles, sidecars and thumbnails follow
               the video/photo they belong to.
Generic folders (Downloads, DCIM, New folder, 2021, ...) are never kept whole.

Never opens files. Console output is counts only; names go only to CSVs on the drive.

    python plan.py --root E:\\                     # plan: writes plan.csv + review-folders.csv
    python plan.py --root E:\\ --review            # re-plan using your edits in review-folders.csv
                                                  # (Action: whole / split / skip / inside)
    python plan.py --root E:\\ --execute           # move according to plan.csv, write undo log
"""
import argparse
import csv
import os
import re
import shutil
import stat
import time
from collections import Counter

CATEGORIES = {
    "Images": "jpg jpeg png gif bmp tif tiff webp heic heif raw cr2 cr3 nef arw dng orf rw2 psd svg ico",
    "Videos": "mp4 mkv avi mov wmv flv webm m4v 3gp mpg mpeg ts mts m2ts vob",
    "Audio": "mp3 wav flac aac m4a ogg wma opus amr aiff mid midi",
    "Documents": "pdf doc docx txt rtf odt xls xlsx csv ods ppt pptx odp md epub mobi pages key numbers",
    "Archives": "zip rar 7z tar gz tgz bz2 xz iso img",
    "Programs": "exe msi apk xapk dmg bat cmd ps1 jar",
}
EXT_CAT = {"." + e: c for c, exts in CATEGORIES.items() for e in exts.split()}
# Files that belong to a video/audio/photo with the same base name.
COMPANION_EXTS = {".srt", ".vtt", ".ttml", ".ass", ".ssa", ".sub", ".idx", ".sbv", ".smi", ".sup", ".lrc", ".cue",
                  ".xmp", ".aae", ".nfo", ".description", ".json", ".thm"}
MAIN_CATS = {"Images", "Videos", "Audio", "Documents"}
DOC_LIKE = {"Documents", "Other", "Archives", "Programs"}

LETTER = r"[^\W\d_]"   # any letter, Arabic included
PRIVATE_WORDS = ["خاص", "خاصة", "خاصه", "الخاص", "الخاصة", "سري", "سرية", "شخصي", "شخصية",
                 "private", "privat", "privé", "prive", "privado", "privada", "privato", "privee", "privée",
                 "özel", "ozel", "personal", "personlig", "personligt", "persönlich", "secret", "secrets"]
PRIVATE = re.compile(rf"(?<!{LETTER})(?:{'|'.join(map(re.escape, PRIVATE_WORDS))})(?!{LETTER})", re.I)

GENERIC = re.compile(r"""^(?:
    downloads?|desktop|documents|my\ documents|pictures|my\ pictures|photos?|images?|videos?|my\ videos|
    movies|music|my\ music|audio|media|dcim|camera|screenshots?|sent|backups?|old|misc|other|others|files|
    data|temp|tmp|users?|home|storage|internal\ storage|sdcard|phone|android|recovered|new\ folder.*|
    ny\ mapp.*|nouveau\ dossier.*|neuer\ ordner.*|nuova\ cartella.*|nueva\ carpeta.*|yeni\ klas.*|
    whatsapp.*|telegram.*|messenger|instagram|snapchat|facebook|viber|signal|
    programs?|software|apps?|برامج|البرامج|برنامج|تطبيقات|övrigt?|ovrigt?|
    \d{3}[a-z]+|\d+|\d{4}[-_.\ ]\d{1,2}.*|
    مجلد\ جديد.*|صور|الصور|فيديو|فيديوهات|الفيديو|تحميلات|التنزيلات|مستندات|موسيقى|نسخة\ احتياطية|جديد.*|
    \..*
)$""", re.I | re.X)

SKIP_AT_ROOT = {"$recycle.bin", "system volume information", "organized", "found.000"}
SKIP_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}
MAX_WHOLE = 3000   # a "whole" folder bigger than this is more likely a dump than a unit
HIDDEN_SYSTEM = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM


def list_separator():
    """Excel opens CSVs with the regional list separator (';' on Swedish Windows)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as k:
            return winreg.QueryValueEx(k, "sList")[0] or ","
    except OSError:
        return ","


def year_of(mtime):
    y = time.localtime(mtime).tm_year if mtime > 0 else 0
    return str(y) if y >= 1980 else "Unknown-Year"


class Dir:
    __slots__ = ("files", "subdirs", "n", "cats", "catsize", "years", "size", "dll", "exe", "git", "exe_below",
                 "private_dirs", "unreadable")

    def __init__(self):
        self.files, self.subdirs, self.private_dirs = [], [], []
        self.n, self.size = 0, 0
        self.cats, self.catsize, self.years = Counter(), Counter(), Counter()
        self.dll = self.exe = self.git = self.exe_below = self.unreadable = False


def scan(root):
    """Read the folder tree (names, sizes, dates only) and total up every subtree."""
    dirs, stack = {}, [root]
    while stack:
        path = stack.pop()
        d = dirs[path] = Dir()
        try:
            entries = list(os.scandir(path))
        except OSError:
            d.unreadable = True
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    attrs = e.stat(follow_symlinks=False).st_file_attributes
                    if attrs & (stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_SYSTEM):
                        continue
                    if path == root and e.name.lower() in SKIP_AT_ROOT:
                        continue
                    if e.name.lower() == ".git":
                        d.git = True
                        continue
                    d.subdirs.append(e.path)
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    if e.name.lower() in SKIP_FILES or (st.st_file_attributes & HIDDEN_SYSTEM) == HIDDEN_SYSTEM:
                        continue
                    ext = os.path.splitext(e.name)[1].lower()
                    d.files.append((e.name, ext, st.st_size, st.st_mtime))
                    d.dll |= ext == ".dll"
                    d.exe |= ext == ".exe"
            except OSError:
                continue
    # Subtree totals, deepest folders first.
    for path in sorted(dirs, key=lambda p: p.count(os.sep), reverse=True):
        d = dirs[path]
        for name, ext, size, mtime in d.files:
            cat = "Companion" if ext in COMPANION_EXTS else EXT_CAT.get(ext, "Other")
            d.cats[cat] += 1
            d.catsize[cat] += size
            d.years[year_of(mtime)] += 1
            d.n += 1
            d.size += size
        for sub in d.subdirs:
            s = dirs[sub]
            # Private folders are always pulled out on their own, so they don't count toward the parent.
            if PRIVATE.search(os.path.basename(sub)):
                d.private_dirs.append(sub)
                continue
            d.private_dirs.extend(s.private_dirs)
            d.n += s.n
            d.size += s.size
            d.cats.update(s.cats)
            d.catsize.update(s.catsize)
            d.years.update(s.years)
            d.git |= s.git
            d.exe_below |= s.exe or s.dll or s.exe_below
    return dirs


PART_OF_PROGRAM = re.compile(r"^(x86|x64|x32|amd64|arm64|win(32|64|dows)?|32|64|32.?bit|64.?bit|bin|setup|"
                             r"install(er)?|crack|patch|keygen|data|program|app|files|mac|linux)$", re.I)


def whole_rule(name, d, dirs):
    """Return (rule, destination) when this folder should move as one unit, else None."""
    if PRIVATE.search(name):
        return "Private", os.path.join("Private", name)
    if d.git:
        return "Apps", os.path.join("Programs", "Apps", name)
    if GENERIC.match(name):
        return ("Skip", "") if d.dll else None
    # A program/game folder is mostly program files by size; a folder of videos or a downloads
    # dump that merely contains an installer is not. A folder of several installers is split.
    installers = sum(1 for f in d.files if f[1] in (".exe", ".msi"))
    collection = installers >= 2 and installers * 2 >= len(d.files) and not (d.dll or d.exe_below)
    program_bytes = (d.catsize["Programs"] + d.catsize["Other"]) / d.size if d.size else 0
    program_count = (d.cats["Programs"] + d.cats["Other"]) / d.n if d.n else 0
    program_share = program_bytes if program_count >= 0.4 else 0   # one big installer among photos isn't a program
    # "Games\Chess" is a container of programs: each child is its own program.
    # "Skin Finer\x64" is one program split into parts: the parent is the program.
    container = not (d.exe or d.dll) and any(
        (dirs[s].exe or dirs[s].dll or dirs[s].exe_below) and not PART_OF_PROGRAM.match(os.path.basename(s))
        for s in d.subdirs)
    if (d.exe or d.exe_below) and program_share >= 0.5 and not collection and not container:
        return "Apps", os.path.join("Programs", "Apps", name)
    n = d.n - d.cats["Companion"]
    # A folder holding programs further down is a container: each program is handled on its own.
    if n < 2 or d.n > MAX_WHOLE or d.exe_below:
        return None
    media = d.cats["Images"] + d.cats["Videos"]
    if n >= 5 and media / n >= 0.9:
        year = Counter({y: c for y, c in d.years.items() if y != "Unknown-Year"}).most_common(1)
        return "Albums", os.path.join("Albums", year[0][0] if year else "Unknown-Year", name)
    kinds = sum(1 for c, k in d.cats.items() if k and c != "Companion")
    if kinds >= 2 and sum(d.cats[c] for c in DOC_LIKE) / n >= 0.10:
        return "Folders", os.path.join("Folders", name)
    return None


def plan_files(path, d, labels):
    """File-by-file destinations for one folder; companions follow their main file."""
    out, mains = [], []
    companions = []
    for name, ext, size, mtime in d.files:
        src = os.path.join(path, name)
        if PRIVATE.search(os.path.splitext(name)[0]):
            out.append([src, "Private", "Private"])
            continue
        cat = EXT_CAT.get(ext, "Other")
        if ext in COMPANION_EXTS:
            companions.append((src, name, mtime))
            continue
        folder = cat
        if cat == "Images" and src in labels:
            folder = os.path.join("Images", labels[src])
        dest = os.path.join(folder, year_of(mtime))
        if cat in MAIN_CATS:
            mains.append((os.path.splitext(name)[0], cat, dest))
        out.append([src, dest, "Files"])
    # Thumbnails: a photo with exactly the same base name as a video follows the video.
    videos = {stem: dest for stem, cat, dest in mains if cat == "Videos"}
    for row in out:
        stem = os.path.splitext(os.path.basename(row[0]))[0]
        if row[2] == "Files" and EXT_CAT.get(os.path.splitext(row[0])[1].lower()) == "Images" and stem in videos:
            row[1], row[2] = videos[stem], "Companion"
    for src, name, mtime in companions:
        best = None
        for stem, cat, dest in mains:
            if (name.startswith(stem + ".") or name.startswith(stem + "_")) and (not best or len(stem) > len(best[0])):
                best = (stem, dest)
        if best:
            out.append([src, best[1], "Companion"])
        else:
            out.append([src, os.path.join("Other", year_of(mtime)), "Files"])
    return [tuple(r) for r in out]


def make_plan(root, labels, overrides):
    dirs = scan(root)
    entries, review, counts = [], [], Counter()
    skipped_dirs = 0

    stack = [(root, "")]   # (folder, destination prefix: set inside a private folder you chose to sort)
    while stack:
        path, prefix = stack.pop()
        d = dirs[path]
        if d.unreadable:
            skipped_dirs += 1
            continue
        if path != root:
            name = os.path.basename(path)
            action = overrides.get(path, "")
            if action == "skip":
                counts["Left in place (your choice)"] += d.n
                continue
            rule = None if action == "split" else whole_rule(name, d, dirs)
            if action == "inside":
                rule = ("Private", os.path.join("Private", name))   # private by your choice, whatever its name
            if action == "inside":
                # Move into Private\<name>, but sort what's inside by the same rules.
                counts["Private (sorted inside)"] += d.n
                review.append((path, "Private", d.n, round(d.size / 2**20), os.path.join(prefix, rule[1])))
                stack.extend((s, os.path.join(prefix, rule[1])) for s in d.subdirs)
                for src, dest, r in plan_files(path, d, labels):
                    entries.append((src, os.path.join(prefix, rule[1], dest), r, "file", 1))
                continue
            if rule:
                rule = (rule[0], os.path.join(prefix, rule[1]))
            if action == "whole" and not rule:
                rule = ("Folders", os.path.join("Folders", name))
            if rule and rule[0] == "Skip":
                counts["Left in place (program files)"] += d.n
                continue
            if rule:
                if rule[0] in ("Albums", "Folders"):
                    # Pull private subfolders out first, then move the rest of the folder whole.
                    for p in d.private_dirs:
                        pn = dirs[p].n
                        entries.append((p, os.path.join(prefix, "Private", os.path.basename(p)), "Private", "dir", pn))
                        review.append((p, "Private", pn, round(dirs[p].size / 2**20), os.path.join("Private", os.path.basename(p))))
                        counts["Private (whole folders)"] += 1
                        counts["Private (files inside)"] += pn
                entries.append((path, rule[1], rule[0], "dir", d.n))
                review.append((path, rule[0], d.n, round(d.size / 2**20), rule[1]))
                counts[f"{rule[0]} (whole folders)"] += 1
                counts[f"{rule[0]} (files inside)"] += d.n
                continue
        for src, dest, rule in plan_files(path, d, labels):
            entries.append((src, os.path.join(prefix, dest), rule, "file", 1))
            if not prefix:
                counts[rule if rule != "Files" else dest.split(os.sep)[0]] += 1
        stack.extend((s, prefix) for s in d.subdirs)
    return entries, review, counts, skipped_dirs


def unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    if os.path.isdir(path):
        base, ext = path, ""
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


def execute(root, plan_path, undo_dir):
    os.makedirs(undo_dir, exist_ok=True)
    # Keep the undo tool on the drive itself, so it can be undone from any computer.
    shutil.copy2(os.path.join(os.path.dirname(os.path.abspath(__file__)), "undo.ps1"), undo_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(undo_dir, f"move-log-{stamp}.csv")
    err_path = os.path.join(undo_dir, f"errors-{stamp}.txt")
    dest_root = os.path.join(root, "Organized")
    moved, errors, missing = Counter(), 0, 0
    with open(plan_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(log_path, "w", encoding="utf-8", newline="") as log, open(err_path, "w", encoding="utf-8") as err:
        writer = csv.writer(log, quoting=csv.QUOTE_ALL)
        writer.writerow(["Source", "Destination"])
        for i, row in enumerate(rows, 1):
            src = row["Source"]
            if not os.path.exists(src):
                missing += 1
                continue
            try:
                if row["Kind"] == "dir":
                    target = unique(os.path.join(dest_root, row["Destination"]))
                else:
                    target = unique(os.path.join(dest_root, row["Destination"], os.path.basename(src)))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.rename(src, target)
                writer.writerow([src, target])
                log.flush()
                moved[row["Kind"]] += 1
            except OSError as e:
                errors += 1
                err.write(f"{src}\t{e}\n")
            if i % 20000 == 0:
                print(f"... {i}/{len(rows)}")
    print(f"Moved: {moved['file']} files and {moved['dir']} whole folders   Errors: {errors}   "
          f"Already gone: {missing}")
    print(f"Undo log: {log_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--review", action="store_true", help="apply your edits from review-folders.csv")
    ap.add_argument("--choices", help="review-choices.csv saved from review.html (default: newest in Downloads)")
    ap.add_argument("--execute", action="store_true", help="move according to the existing plan.csv")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not root.endswith(os.sep):
        root += os.sep
    root = os.path.normpath(root) if len(root) > 3 else root
    plan_dir = os.path.join(root, "Organized", "_plan")
    plan_path = os.path.join(plan_dir, "plan.csv")
    review_path = os.path.join(plan_dir, "review-folders.csv")
    sep = list_separator()

    if args.execute:
        execute(root, plan_path, os.path.join(root, "Organized", "_undo"))
        return

    labels = {}
    labels_path = os.path.join(root, "Organized", "_labels", "photo-labels.csv")
    if os.path.exists(labels_path):
        with open(labels_path, encoding="utf-8", newline="") as f:
            labels = {r["Path"]: r["Label"] for r in csv.DictReader(f)}

    overrides = {}
    if args.review:
        sources = [(review_path, sep)]
        # Choices saved from review.html land in Downloads (the browser may add " (1)" to the name).
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        saved = [os.path.join(downloads, n) for n in os.listdir(downloads)
                 if n.startswith("review-choices") and n.endswith(".csv")] if os.path.isdir(downloads) else []
        if args.choices:
            saved = [args.choices]
        if saved:
            sources.append((max(saved, key=os.path.getmtime), ","))
        for path, delimiter in sources:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f, delimiter=delimiter):
                    a = (r.get("Action") or "").strip().lower()
                    if a in ("whole", "split", "skip", "inside"):
                        overrides[r["Folder"]] = a
        if saved:
            print(f"Using your choices from: {max(saved, key=os.path.getmtime)}")

    entries, review, counts, skipped = make_plan(root, labels, overrides)
    os.makedirs(plan_dir, exist_ok=True)
    with open(plan_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Source", "Destination", "Rule", "Kind", "Files"])
        w.writerows(entries)
    with open(review_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=sep)
        w.writerow(["Folder", "Rule", "Files", "SizeMB", "Destination", "Action"])
        for path, rule, n, mb, dest in sorted(review, key=lambda r: (r[1], r[0])):
            w.writerow([path, rule, n, mb, dest, overrides.get(path, "")])

    print("\n=== Plan (nothing moved) ===")
    for k, v in sorted(counts.items()):
        print(f"{k:34} {v}")
    print(f"Unreadable folders left in place: {skipped}")
    print(f"Folders to review: {review_path}")


if __name__ == "__main__":
    main()
