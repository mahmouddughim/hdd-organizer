"""Info pages ("ملحق") next to every program, so you can decide what to keep.

    python programs.py --root E:\\ --inventory OUT.csv   # list programs in the plan + their metadata
    python programs.py --root E:\\ --write DESC.json --inv OUT.csv   # after the move: write the .html pages
                                                     # (DESC.json optional: without it, metadata only)

Metadata comes from the program file itself (product, publisher, version, digital signature);
nothing is run. DESC.json maps a program's inventory Id to {"short", "about", "verdict", "why"}.
The page is named "<program>.1 - <short>.html", so sorting by name puts it right under the program.
"""
import argparse
import csv
import html
import json
import os
import re
import subprocess
import time

PROGRAM_EXTS = {".exe", ".msi", ".apk", ".xapk", ".dmg", ".jar"}

PS_META = r"""
$items = Get-Content -LiteralPath $args[0] -Encoding UTF8 | ConvertFrom-Json
$out = foreach ($p in $items) {
    $r = [ordered]@{ Path = $p; Product = ''; Company = ''; Version = ''; Description = ''; Signer = ''; Signed = '' }
    try {
        if ($p -like '*.exe') {
            $v = (Get-Item -LiteralPath $p).VersionInfo
            $r.Product = "$($v.ProductName)".Trim(); $r.Company = "$($v.CompanyName)".Trim()
            $r.Version = "$($v.ProductVersion)".Trim(); $r.Description = "$($v.FileDescription)".Trim()
        } elseif ($p -like '*.msi') {
            $wi = New-Object -ComObject WindowsInstaller.Installer
            $db = $wi.GetType().InvokeMember('OpenDatabase', 'InvokeMethod', $null, $wi, @($p, 0))
            foreach ($prop in 'ProductName', 'Manufacturer', 'ProductVersion') {
                $view = $db.GetType().InvokeMember('OpenView', 'InvokeMethod', $null, $db, @("SELECT Value FROM Property WHERE Property='$prop'"))
                $view.GetType().InvokeMember('Execute', 'InvokeMethod', $null, $view, $null) | Out-Null
                $rec = $view.GetType().InvokeMember('Fetch', 'InvokeMethod', $null, $view, $null)
                if ($rec) { $val = $rec.GetType().InvokeMember('StringData', 'GetProperty', $null, $rec, 1)
                    switch ($prop) { 'ProductName' { $r.Product = $val } 'Manufacturer' { $r.Company = $val } 'ProductVersion' { $r.Version = $val } } }
                $view.GetType().InvokeMember('Close', 'InvokeMethod', $null, $view, $null) | Out-Null
            }
        }
        if ($p -like '*.exe' -or $p -like '*.msi') {
            $s = Get-AuthenticodeSignature -LiteralPath $p
            $r.Signed = "$($s.Status)"
            if ($s.SignerCertificate) { $r.Signer = ($s.SignerCertificate.Subject -replace '^CN="?([^",]+).*$', '$1') }
        }
    } catch {}
    [pscustomobject]$r
}
@($out) | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $args[1] -Encoding UTF8
"""


def metadata(paths, workdir):
    """Product/publisher/version/signature for each path, read by Windows without running anything."""
    if not paths:
        return {}
    inp, out, script = (os.path.join(workdir, n) for n in ("meta-in.json", "meta-out.json", "meta.ps1"))
    with open(inp, "w", encoding="utf-8") as f:
        json.dump(paths, f, ensure_ascii=False)
    with open(script, "w", encoding="utf-8-sig") as f:
        f.write(PS_META)
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, inp, out], check=True)
    with open(out, encoding="utf-8-sig") as f:
        data = json.load(f)
    for p in (inp, out, script):
        os.remove(p)
    return {d["Path"]: d for d in (data if isinstance(data, list) else [data])}


def main_exe(folder):
    """The program's own .exe: the largest one closest to the top of the folder."""
    best = None
    for dirpath, _, files in os.walk(folder):
        depth = dirpath.count(os.sep)
        for name in files:
            if name.lower().endswith(".exe"):
                p = os.path.join(dirpath, name)
                key = (-depth, os.path.getsize(p))
                if best is None or key > best[0]:
                    best = (key, p)
    return best[1] if best else None


def inventory(root, out_csv):
    plan_path = os.path.join(root, "Organized", "_plan", "plan.csv")
    items = []   # (name, kind, program path or folder, exe to read metadata from)
    with open(plan_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["Rule"] == "Apps" and r["Kind"] == "dir":
                items.append((os.path.basename(r["Source"]), "folder", r["Source"], main_exe(r["Source"])))
            elif r["Kind"] == "file" and os.path.splitext(r["Source"])[1].lower() in PROGRAM_EXTS \
                    and r["Destination"].startswith("Programs"):
                items.append((os.path.basename(r["Source"]), "installer", r["Source"], r["Source"]))
    meta = metadata([i[3] for i in items if i[3]], os.path.dirname(os.path.abspath(out_csv)))
    # Full paths stay on the drive; the inventory itself only carries an Id per program.
    paths_csv = os.path.join(root, "Organized", "_programs", "inventory-paths.csv")
    os.makedirs(os.path.dirname(paths_csv), exist_ok=True)
    with open(paths_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Id", "Source"])
        w.writerows((i, it[2]) for i, it in enumerate(items, 1))
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Id", "Name", "Kind", "MainExe", "Product", "Company", "Version", "Description", "Signer", "Signed", "SizeMB", "Modified"])
        for i, (name, kind, path, exe) in enumerate(items, 1):
            m = meta.get(exe, {}) if exe else {}
            if kind == "folder":
                size = sum(os.path.getsize(os.path.join(dp, n)) for dp, _, fs in os.walk(path) for n in fs)
            else:
                size = os.path.getsize(path)
            w.writerow([i, name, kind, os.path.basename(exe) if exe else "", m.get("Product", ""), m.get("Company", ""),
                        m.get("Version", ""), m.get("Description", ""), m.get("Signer", ""), m.get("Signed", ""),
                        round(size / 2**20, 1), time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))])
    print(f"Programs listed: {len(items)}")


PAGE = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#faf8f4;--card:#fff;--ink:#1f2328;--muted:#5b6370;--line:#e4e0d8;--accent:#1f6feb;--ok:#1a7f37;--warn:#9a6700;--bad:#c62828}}
@media (prefers-color-scheme:dark){{:root{{--bg:#15171a;--card:#1d2024;--ink:#e8e6e3;--muted:#a2a8b1;--line:#33373d;--accent:#6ea8fe;--ok:#5cc27a;--warn:#e3b341;--bad:#ff7b72}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:17px/1.8 "Segoe UI",Tahoma,Arial,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:1.6rem;margin:0 0 4px;line-height:1.35}} .sub{{color:var(--muted);margin:0 0 20px}}
.verdict{{border-radius:12px;padding:12px 16px;margin:16px 0;background:var(--card);border:1px solid var(--line);border-inline-start:6px solid var(--v)}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;margin:16px 0}}
td{{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}} td:first-child{{color:var(--muted);width:34%}}
tr:last-child td{{border-bottom:0}} .ltr{{direction:ltr;unicode-bidi:isolate;font-family:Consolas,monospace;font-size:.92em}}
h2{{font-size:1.15rem;margin:24px 0 6px}}
</style></head><body><main>
<h1>{name_html}</h1>
<p class="sub">{short}</p>
<div class="verdict" style="--v:var(--{vcolor})"><strong>{vlabel}</strong><br>{verdict}</div>
<h2>ما هذا البرنامج؟</h2>
<p>{about}</p>
<h2>معلومات من ملف البرنامج نفسه</h2>
<table>
<tr><td>اسم الملف</td><td class="ltr">{name}</td></tr>
<tr><td>النوع</td><td>{kind}</td></tr>
<tr><td>اسم المنتج</td><td class="ltr">{product}</td></tr>
<tr><td>الشركة</td><td class="ltr">{company}</td></tr>
<tr><td>الإصدار</td><td class="ltr">{version}</td></tr>
<tr><td>التوقيع الرقمي</td><td>{signature}</td></tr>
<tr><td>الحجم</td><td>{size} MB</td></tr>
<tr><td>تاريخ الملف</td><td class="ltr">{modified}</td></tr>
</table>
</main></body></html>
"""

VERDICTS = {"keep": ("ok", "يستحق الإبقاء"), "maybe": ("warn", "حسب حاجتك"), "delete": ("bad", "غالبًا يمكن حذفه")}
SIGNED = {"Valid": "موقّع وسليم", "NotSigned": "غير موقّع", "HashMismatch": "التوقيع لا يطابق: الملف مُعدَّل!",
          "UnknownError": "تعذّر التحقق", "NotTrusted": "موقّع بشهادة غير موثوقة"}


def safe(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip()[:60]


def write_pages(root, inv_csv, desc_json):
    desc = {}
    if desc_json and os.path.exists(desc_json):
        with open(desc_json, encoding="utf-8") as f:
            desc = json.load(f)
    with open(inv_csv, encoding="utf-8-sig", newline="") as f:
        inv = {r["Id"]: r for r in csv.DictReader(f)}
    with open(os.path.join(root, "Organized", "_programs", "inventory-paths.csv"), encoding="utf-8-sig", newline="") as f:
        source = {r["Id"]: r["Source"] for r in csv.DictReader(f)}
    # Where did each program end up? Read it from the newest undo log.
    undo_dir = os.path.join(root, "Organized", "_undo")
    log = max((os.path.join(undo_dir, n) for n in os.listdir(undo_dir) if n.startswith("move-log-")), key=os.path.getmtime)
    with open(log, encoding="utf-8-sig", newline="") as f:
        final = {r["Source"]: r["Destination"] for r in csv.DictReader(f)}
    written = missing = 0
    for pid, r in inv.items():
        name = r["Name"]
        d, target = desc.get(pid), final.get(source.get(pid, ""))
        if not target:
            missing += 1
            continue
        if not d:
            # No written description: the page still shows what the program file says about itself.
            label = r["Product"] or r["Description"] or os.path.splitext(name)[0]
            d = {"short": label, "verdict": "maybe",
                 "about": "لا يوجد شرح مكتوب لهذا البرنامج بعد. المعلومات في الجدول أدناه مأخوذة من ملف البرنامج نفسه، "
                          "ويمكنك البحث عن اسم المنتج على الإنترنت لمعرفة المزيد.",
                 "why": "اقرأ اسم المنتج والشركة في الجدول، وقرّر إن كنت ما زلت تحتاجه."}
        vcolor, vlabel = VERDICTS.get(d.get("verdict", "maybe"), VERDICTS["maybe"])
        sig = SIGNED.get(r["Signed"], r["Signed"] or "لا ينطبق")
        if r["Signer"]:
            sig += f" — {html.escape(r['Signer'])}"
        page = PAGE.format(
            title=html.escape(name), name_html=html.escape(d.get("title", name)), short=html.escape(d["short"]),
            vcolor=vcolor, vlabel=vlabel, verdict=html.escape(d.get("why", "")), about=html.escape(d["about"]),
            name=html.escape(name), kind="مجلد برنامج أو لعبة" if r["Kind"] == "folder" else "ملف تثبيت",
            product=html.escape(r["Product"] or "—"), company=html.escape(r["Company"] or "—"),
            version=html.escape(r["Version"] or "—"), signature=sig, size=r["SizeMB"], modified=r["Modified"])
        base = os.path.basename(target)   # final name (may have gained " (1)")
        path = os.path.join(os.path.dirname(target), f"{base}.1 - {safe(d['short'])}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        written += 1
    print(f"Info pages written: {written}   Not moved: {missing}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--inventory")
    ap.add_argument("--write")
    ap.add_argument("--inv", help="inventory CSV to use with --write")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if args.inventory:
        inventory(root, args.inventory)
    elif args.write:
        write_pages(root, args.inv, args.write)


if __name__ == "__main__":
    main()
