import re
import random
import os
import csv
import subprocess
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# 【総監督専用：ダイレクトワープURL】
TARGET_URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/cgi-bin/nc-v05-003.php?cd_ps=2&bai=21.7391&nmk_kisyu=L+%25E9%259D%25A9%25E5%2591%25BD%25E6%25A9%259F%25E3%2583%25B4%25E3%2582%25A1%25E3%2583%25AB%25E3%2583%25B4%25E3%2583%25AC%25E3%2582%25A4%25E3%2583%25B4+D"

def push_to_github():
    print("\n--- クラウド同期（GitHub輸送）を開始します ---")
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["git", "add", "master_data.csv"], check=True)
        result = subprocess.run(["git", "commit", "-m", f"Auto-update: {now_str}"], capture_output=True, text=True)
        if "nothing to commit" in result.stdout:
            print("更新データがないため、同期をスキップしました。")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ クラウド（GitHub）への同期が完了しました！")
    except Exception as e:
        print(f"❌ 同期エラー: {e}")

def wait_random(page, min_sec=3.0, max_sec=5.0):
    page.wait_for_timeout(int(random.uniform(min_sec, max_sec) * 1000))

def handle_popups(page):
    for btn_text in ["閉じる", "OK", "x", "×"]:
        try:
            loc = page.get_by_text(btn_text, exact=True).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(force=True, timeout=1000)
        except: pass

def extract_precise_data(page):
    labels = ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    result = {label: "未検出" for label in labels}
    js_code = r"""
    () => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        const textNodes = [];
        let node;
        while(node = walker.nextNode()) {
            const txt = node.nodeValue.trim();
            if(txt !== "") textNodes.push(txt);
        }
        return textNodes;
    }
    """
    try:
        lines = page.evaluate(js_code)
        bonus_idx = next((i for i, line in enumerate(lines) if "BONUS" in line.upper()), -1)
        if bonus_idx != -1:
            for j in range(bonus_idx, min(bonus_idx + 40, len(lines))):
                for label in labels:
                    if label in lines[j]:
                        val_idx = j + 1
                        if val_idx < len(lines):
                            match = re.search(r'([\d.,/]+)', lines[val_idx])
                            if match: result[label] = match.group(1)
    except: pass
    return result

def get_all_target_dais(page):
    print("台一覧ページから対象番号を抽出中...")
    
    try:
        print("データ要素（数字）の出現を待機しています（最大5秒）...")
        page.wait_for_selector(r"text=/\d{3,4}/", timeout=5000)
    except Exception:
        pass

    page.wait_for_timeout(3000)
    
    page.screenshot(path="debug_screen.png")
    
    js_code = r"""() => {
        const dais = new Set();
        document.querySelectorAll('a, div, span').forEach(el => {
            if (!el.innerText) return;
            let txt = el.innerText.trim();
            if (/^\d{3,4}(番台)?$/.test(txt)) dais.add(txt.replace('番台', ''));
        });
        return Array.from(dais);
    }"""
    raw_dais = page.evaluate(js_code)
    print(f"【デバッグ】画面から抽出された生データ: {raw_dais}")
    
    cleaned = sorted(list(set([d.zfill(4) for d in raw_dais if d.isdigit() and int(d) >= 1])))
    print(f"✅ 台数確定: {len(cleaned)} 台")
    return cleaned

def patrol_dai_list(page, dais):
    if not dais: return
    first_dai = dais[0]
    print(f"最初の台 ({first_dai}) を開きます...")
    for d in [first_dai, first_dai.lstrip("0")]:
        loc = page.get_by_text(d, exact=True).first
        if loc.count() > 0:
            loc.click(force=True)
            break
            
    for i, dai in enumerate(dais):
        print(f"\n--- [{i+1}/{len(dais)}] 台番号 {dai} ---")
        handle_popups(page)
        try: 
            page.wait_for_selector("text=BONUS", timeout=10000)
        except: pass

        extracted = extract_precise_data(page)
        if any(v != "未検出" for v in extracted.values()):
            save_to_csv(dai, extracted)
            print("結果: 取得成功")
        else: 
            print("結果: 未検出")

        if i < len(dais) - 1:
            next_btn = None
            for sel in ["text='次台'", "text='>>'", "text='次へ'"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    next_btn = loc
                    break
                    
            if next_btn:
                next_btn.click()
                wait_random(page)
            else: 
                break

def save_to_csv(dai_no, data):
    fn = "master_data.csv"
    today = datetime.now().strftime("%Y-%m-%d")
    exists = os.path.isfile(fn)
    try:
        with open(fn, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not exists:
                writer.writerow(["取得日", "台番号", "BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"])
            writer.writerow([today, dai_no] + [data.get(l, "未検出") for l in ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]])
    except Exception as e: 
        print(f"CSV保存エラー: {e}")

def main():
    with sync_playwright() as p:
        user_data_dir = os.path.join(os.getcwd(), "user_data_victory")
        context = p.chromium.launch_persistent_context(
            user_data_dir, 
            headless=False,
            slow_mo=50,
            args=["--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Referer": "https://www.pscube.jp/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Upgrade-Insecure-Requests": "1"
            }
        )
        page = context.pages[0]
        
        # navigator.webdriverの無効化（超重要：Playwrightの痕跡を消し去る）
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print("【司令部より】ハイブリッド・復活プロトコルで接続中...")
            page.goto(TARGET_URL, wait_until="networkidle")
            handle_popups(page)
            
            dais = get_all_target_dais(page)
            if dais:
                patrol_dai_list(page, dais)
                push_to_github()
            else: 
                print("エラー: 台番号を検出できませんでした。")
        except Exception as e: 
            print(f"異常発生: {e}")
            try:
                page.screenshot(path="debug_error.png")
            except: pass
        finally:
            page.wait_for_timeout(5000)
            context.close()

if __name__ == "__main__":
    main()