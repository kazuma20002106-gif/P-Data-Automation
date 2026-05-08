import re
import random
import os
import csv
import subprocess
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# ターゲット設定
TARGET_URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/cgi-bin/nc-v05-003.php?cd_ps=2&bai=21.7391&nmk_kisyu=L+%25E9%259D%25A9%25E5%2591%25BD%25E6%25A9%259F%25E3%2583%25B4%25E3%2582%25A1%25E3%2583%25AB%25E3%2583%25B4%25E3%2583%25AC%25E3%2582%25A4%25E3%2583%25B4+D"

def push_to_github():
    """取得したデータを自動的にGitHubへアップロードする"""
    print("\n--- クラウド同期を開始します ---")
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["git", "add", "master_data.csv"], check=True)
        result = subprocess.run(["git", "commit", "-m", f"Auto-update: {now_str}"], capture_output=True, text=True)
        if "nothing to commit" in result.stdout:
            print("更新データがないため、スキップしました。")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ クラウド（GitHub）への同期が完了しました！")
    except Exception as e:
        print(f"❌ 同期エラー: {e}")

def wait_random(page, min_sec=3.0, max_sec=5.0):
    page.wait_for_timeout(int(random.uniform(min_sec, max_sec) * 1000))

def handle_popups(page):
    popup_buttons = ["閉じる", "OK", "x", "×"]
    for btn_text in popup_buttons:
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
        # 大文字小文字に関わらずBONUSを探す
        bonus_indices = [i for i, line in enumerate(lines) if "BONUS" in line.upper()]
        for idx in bonus_indices:
            # ラベルが見つかったら、その後ろ30個のテキストノードを走査して数値を探す
            for j in range(idx, min(idx + 30, len(lines))):
                for label in labels:
                    if label in lines[j]:
                        val_idx = j + 1
                        if val_idx < len(lines):
                            val = lines[val_idx]
                            match = re.search(r'([\d.,/]+)', val)
                            if match: result[label] = match.group(1)
            if result["BONUS"] != "未検出": break
    except: pass
    return result

def get_all_target_dais(page):
    print("ページから対象の全台番号を自動抽出します...")
    page.wait_for_timeout(3000)
    js_code = r"""
    () => {
        const dais = new Set();
        document.querySelectorAll('a, div, span').forEach(el => {
            let txt = el.innerText.trim();
            if (/^\d{3,4}(番台)?$/.test(txt)) dais.add(txt.replace('番台', ''));
        });
        return Array.from(dais);
    }
    """
    raw_dais = page.evaluate(js_code)
    # ヴァルヴレイヴの台番号帯（111〜500程度）に絞り込み
    cleaned = sorted(list(set([d.zfill(4) for d in raw_dais if d.isdigit() and 111 <= int(d) <= 500])))
    print(f"純化された台番号（計 {len(cleaned)} 台）: {cleaned}")
    return cleaned

def patrol_dai_list(page, dais):
    # 最初の台をクリックして巡回を開始
    first_dai = dais[0]
    print(f"台番号を検索中: {first_dai}")
    for d in [first_dai, first_dai.lstrip("0")]:
        loc = page.get_by_text(d, exact=True).first
        if loc.count() > 0:
            loc.click(force=True)
            break
    
    # 初回のデータ描画待ちを大幅に強化（8秒）
    print("初回アクセスのため、データ描画を確実に待ちます（8秒）...")
    page.wait_for_timeout(8000)

    for i, dai in enumerate(dais):
        print(f"\n========== 台番号 {dai} ==========")
        handle_popups(page)
        
        # データの出現を粘り強く待つ（最大15秒）
        print("データの描画を待機しています（最大15秒）...")
        try:
            page.wait_for_selector("text=BONUS", timeout=15000)
        except:
            print("データ描画の待機がタイムアウトしました。")

        extracted = extract_precise_data(page)
        
        # 少なくとも何らかのデータが取れていれば保存
        if any(v != "未検出" for v in extracted.values()):
            save_to_csv(dai, extracted)
            print(f"台番号 {dai}: 抽出成功")
        else:
            print(f"⚠️ 台番号 {dai}: データの取得に失敗しました（未検出）。")

        if i < len(dais) - 1:
            # 次台ボタンの検索を強化
            print(f"「次台」ボタンを探して、次の台 ({dais[i+1]}) へ遷移します...")
            next_btn = page.locator("text=次台, text=>>, text=次へ").first
            if next_btn.count() > 0:
                next_btn.click()
                # 遷移後のランダム待機
                wait_random(page)
            else:
                print("「次台」ボタンが見つかりませんでした。巡回を終了します。")
                break

def save_to_csv(dai_no, extracted_data):
    filename = "master_data.csv"
    today_str = datetime.now().strftime("%Y-%m-%d")
    labels = ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    file_exists = os.path.isfile(filename)
    try:
        with open(filename, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["取得日", "台番号"] + labels)
            row_data = [today_str, dai_no] + [extracted_data.get(l, "未検出") for l in labels]
            writer.writerow(row_data)
    except Exception as e:
        print(f"CSV保存エラー: {e}")

def main():
    with sync_playwright() as p:
        # ローカル実行のため画面を表示
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print(f"目的の機種ページへ直接アクセスします...")
            page.goto(TARGET_URL, wait_until="networkidle")
            
            dais = get_all_target_dais(page)
            if dais:
                patrol_dai_list(page, dais)
                push_to_github() # すべて完了後にGitHubへ同期
            else:
                print("エラー: 台番号が1台も検出されませんでした。")
            
        except Exception as e:
            print(f"実行中に致命的なエラーが発生しました: {e}")
        finally:
            print("5秒後にブラウザを終了します...")
            page.wait_for_timeout(5000)
            browser.close()

if __name__ == "__main__":
    main()