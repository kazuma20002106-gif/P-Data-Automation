import re
import random
import os
import csv
import subprocess
import time
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright

# 【総監督専用：ダイレクトワープURL】
TARGET_URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/cgi-bin/nc-v05-003.php?cd_ps=2&bai=21.7391&nmk_kisyu=L+%25E9%259D%25A9%25E5%2591%25BD%25E6%25A9%259F%25E3%2583%25B4%25E3%2582%25A1%25E3%2583%25AB%25E3%2583%25B4%25E3%2583%25AC%25E3%2582%25A4%25E3%2583%25B4+D"

def push_to_github():
    """【Phase 10.0】強化型・自動輸送プロトコル"""
    print("\n--- [SYNC] クラウド同期フェーズ ---")
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["git", "add", "master_data.csv"], check=True)
        res = subprocess.run(["git", "commit", "-m", f"Auto-update: {now_str}"], capture_output=True, text=True)
        if "nothing to commit" not in res.stdout:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ [SYNC] クラウドへの輸送が完了しました！")
        else:
            print("💡 [SYNC] 新しい変更がないため輸送を待機します。")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️ [SYNC] 自動輸送に失敗。GitHub Desktopで手動Pushしてください。")
    except Exception as e:
        print(f"⚠️ [SYNC] 予期せぬエラー: {e}")

def extract_precise_data(page):
    """【Phase 10.0】黄金律・自動アライメント抽出ロジック"""
    labels = ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    result = {label: "未検出" for label in labels}
    js_code = r"() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); const n = []; let node; while(node = w.nextNode()) { n.push(node.nodeValue.trim()); } return n.filter(t => t !== ''); }"
    try:
        lines = page.evaluate(js_code)
        bonus_idx = next((i for i, line in enumerate(lines) if "BONUS" in line.upper()), -1)
        if bonus_idx != -1:
            end_label_idx = -1
            for j in range(bonus_idx, min(bonus_idx + 16, len(lines))):
                if "最大放出数" in lines[j]:
                    end_label_idx = j
                    break
            if end_label_idx != -1:
                current_labels = lines[bonus_idx : end_label_idx + 1]
                data_start_idx = end_label_idx + 1
                candidate_data = lines[data_start_idx : min(data_start_idx + 20, len(lines))]
                exp_idx = next((i for i, l in enumerate(current_labels) if "確率" in l), -1)
                act_idx = next((i for i, v in enumerate(candidate_data) if "1/" in v), -1)
                offset = max(0, act_idx - exp_idx) if exp_idx != -1 and act_idx != -1 else 0
                aligned_data = candidate_data[offset : offset + len(current_labels)]
                for l_idx, l_str in enumerate(current_labels):
                    for label in labels:
                        if label in l_str and l_idx < len(aligned_data):
                            m = re.search(r'([\d.,/\-]+)', aligned_data[l_idx])
                            if m: result[label] = m.group(1)
    except: pass
    return result

def get_dais(page):
    print("[SYSTEM] 台番号スキャン中...")
    page.wait_for_timeout(5000)
    js = "() => { const d = new Set(); document.querySelectorAll('a, div, span').forEach(el => { let t = el.innerText ? el.innerText.trim() : ''; if (/^\\d{3,4}(番台)?$/.test(t)) d.add(t.replace('番台', '')); }); return Array.from(d); }"
    raw = page.evaluate(js)
    cleaned = sorted(list(set([d.zfill(4) for d in raw if d.isdigit() and int(d) >= 111])))
    print(f"[SYSTEM] ターゲット: {len(cleaned)} 台")
    return cleaned

def patrol(page, dais):
    if not dais: return
    print("[SYSTEM] 巡回開始。")
    first = dais[0]
    for d in [first, first.lstrip("0")]:
        loc = page.get_by_text(d, exact=True).first
        if loc.count() > 0:
            loc.click(force=True)
            break
    page.wait_for_timeout(5000)
    for i, dai in enumerate(dais):
        print(f"--- [{i+1}/{len(dais)}] No.{dai} ---")
        try: page.wait_for_selector("text=BONUS", timeout=10000)
        except: pass
        data = extract_precise_data(page)
        save_csv(dai, data)
        print(f"  -> {'SUCCESS' if '未検出' not in data['BONUS'] else 'FAILED'}")
        if i < len(dais) - 1:
            btn = None
            for txt in ["次台", ">>", "次へ"]:
                loc = page.get_by_text(txt, exact=False).first
                if loc.count() > 0 and loc.is_visible():
                    btn = loc; break
            if btn: btn.click(); page.wait_for_timeout(3000)
            else: break

def save_csv(dai, data):
    fn = "master_data.csv"
    # 時:分まで記録
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    labels = ["取得日", "台番号", "BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    exists = os.path.isfile(fn)
    with open(fn, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if not exists: w.writerow(labels)
        w.writerow([now_str, dai] + [data.get(l, "未検出") for l in labels[2:]])

def main():
    with sync_playwright() as p:
        user_data_dir = os.path.abspath("./user_data_victory")
        context = p.chromium.launch_persistent_context(
            user_data_dir, headless=False,
            args=['--disable-blink-features=AutomationControlled'],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.pages[0]
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        try:
            print("[SYSTEM] 第8世代・精密タイムスタンプエンジン、点火。")
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
            dais = get_dais(page)
            if dais:
                patrol(page, dais)
                push_to_github()
            else: print("[ERROR] 台番号未検出")
        except: traceback.print_exc()
        finally: context.close()

if __name__ == "__main__": main()