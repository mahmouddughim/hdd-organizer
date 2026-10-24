"""Turn review-folders.csv into a page you can edit in any browser (no Excel needed).

    python review_page.py --root E:\\        # writes Organized\\_plan\\review.html and opens it

Choose an action per folder, press save: the browser downloads review-choices.csv into your
Downloads folder, and `plan.py --review` picks it up from there. The page works offline.
"""
import argparse
import csv
import html
import json
import os
import webbrowser

from plan import list_separator

RULES_AR = {"Albums": "ألبوم", "Folders": "مجلد مختلط (مادة/مشروع)", "Apps": "برنامج أو لعبة", "Private": "خاص"}

PAGE = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>مراجعة المجلدات</title>
<style>
:root{--bg:#faf8f4;--card:#fff;--ink:#1f2328;--muted:#5b6370;--line:#e4e0d8;--accent:#1f6feb;--soft:#e8f0fe;--ok:#1a7f37}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--card:#1d2024;--ink:#e8e6e3;--muted:#a2a8b1;--line:#33373d;--accent:#6ea8fe;--soft:#1c2a40;--ok:#5cc27a}}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 "Segoe UI",Tahoma,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 120px}
h1{font-size:1.5rem;margin:0 0 6px} p{margin:6px 0;color:var(--muted)}
.bar{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0;align-items:center}
input,select,button{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:.95rem}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:middle}
th{background:var(--soft);position:sticky;top:0} tr.changed td{background:color-mix(in srgb,var(--accent) 10%,transparent)}
.path{direction:ltr;unicode-bidi:isolate;text-align:left;font-family:Consolas,monospace;font-size:.88rem;word-break:break-all}
.num{white-space:nowrap}
.save{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:var(--accent);color:#fff;border:0;
  padding:12px 28px;border-radius:999px;font-weight:700;box-shadow:0 4px 16px rgba(0,0,0,.2);cursor:pointer}
.done{color:var(--ok);font-weight:600}
</style></head><body><main>
<h1>مراجعة المجلدات التي ستُنقل كاملة</h1>
<p>كل سطر مجلد سيُنقل كما هو. إذا وافقت على الاقتراح فاتركه على «موافق». غيّر فقط ما لا يعجبك، ثم اضغط «حفظ اختياراتي» في الأسفل.</p>
<p>هذه الصفحة تعمل على جهازك فقط ولا ترسل شيئًا إلى أي مكان.</p>
<div class="bar">
  <input id="q" placeholder="ابحث باسم المجلد..." size="28">
  <select id="rf"><option value="">كل الأنواع</option>__RULE_OPTIONS__</select>
  <span id="count"></span> <span id="saved" class="done"></span>
</div>
<div class="wrap"><table>
<thead><tr><th>المجلد</th><th>النوع</th><th>الملفات</th><th>الحجم</th><th>سيذهب إلى</th><th>قرارك</th></tr></thead>
<tbody id="tb"></tbody></table></div>
<button class="save" id="save">حفظ اختياراتي</button>
</main>
<script>
const ROWS = __ROWS__;
const RULES = __RULES__;
const ACTIONS = [["", "موافق (كما هو مقترح)"], ["split", "فكّكه: رتّب ملفاته واحدًا واحدًا"], ["skip", "اتركه مكانه ولا تلمسه"]];
const INSIDE = ["inside", "انقله إلى Private ورتّب ما بداخله"];
const tb = document.getElementById("tb"), q = document.getElementById("q"), rf = document.getElementById("rf");
function size(mb) { return mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : mb + " MB"; }
function render() {
  const s = q.value.trim().toLowerCase(), r = rf.value; let n = 0; tb.innerHTML = "";
  ROWS.forEach((row, i) => {
    if (r && row.rule !== r) return;
    if (s && !row.folder.toLowerCase().includes(s)) return;
    n++;
    const tr = document.createElement("tr"); if (row.action !== row.initial) tr.className = "changed";
    const opts = (row.rule === "Private" ? ACTIONS.concat([INSIDE]) : ACTIONS)
      .map(([v, t]) => `<option value="${v}"${v === row.action ? " selected" : ""}>${t}</option>`).join("");
    tr.innerHTML = `<td class="path"></td><td>${RULES[row.rule] || row.rule}</td><td class="num">${row.files.toLocaleString()}</td>
      <td class="num">${size(row.mb)}</td><td class="path"></td><td><select data-i="${i}">${opts}</select></td>`;
    tr.children[0].textContent = row.folder; tr.children[4].textContent = row.dest;
    tb.appendChild(tr);
  });
  document.getElementById("count").textContent = n + " مجلد";
}
tb.addEventListener("change", e => { const i = e.target.dataset.i; if (i !== undefined) { ROWS[i].action = e.target.value; render(); } });
q.addEventListener("input", render); rf.addEventListener("change", render);
document.getElementById("save").addEventListener("click", () => {
  const esc = v => '"' + String(v).replace(/"/g, '""') + '"';
  const lines = ["Folder,Action"].concat(ROWS.filter(r => r.action).map(r => esc(r.folder) + "," + esc(r.action)));
  const blob = new Blob(["\\ufeff" + lines.join("\\r\\n")], {type: "text/csv"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "review-choices.csv"; a.click();
  document.getElementById("saved").textContent = "✓ حُفظت في مجلد التنزيلات (Downloads). يمكنك إغلاق الصفحة.";
});
render();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    plan_dir = os.path.join(root, "Organized", "_plan")
    with open(os.path.join(plan_dir, "review-folders.csv"), encoding="utf-8-sig", newline="") as f:
        rows = [{"folder": r["Folder"], "rule": r["Rule"], "files": int(r["Files"]), "mb": int(r["SizeMB"]),
                 "dest": r["Destination"], "action": r["Action"], "initial": r["Action"]}
                for r in csv.DictReader(f, delimiter=list_separator())]
    rule_options = "".join(f'<option value="{k}">{html.escape(v)}</option>' for k, v in RULES_AR.items())
    page = (PAGE.replace("__ROWS__", json.dumps(rows, ensure_ascii=False).replace("</", "<\\/"))
                .replace("__RULES__", json.dumps(RULES_AR, ensure_ascii=False))
                .replace("__RULE_OPTIONS__", rule_options))
    out = os.path.join(plan_dir, "review.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Review page: {out}  ({len(rows)} folders)")
    if not args.no_open:
        webbrowser.open("file:///" + out.replace("\\", "/"))


if __name__ == "__main__":
    main()
