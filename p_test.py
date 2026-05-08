import re
import random
import os
import csv
import subprocess
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# ターゲット設定：直接機種ページへワープ
TARGET_URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/cgi-bin/nc-v05-003.php?cd_ps=2&bai=21.7391&nmk_kisyu=L+%25E9%259D%25A9%25E5%2591%25BD%25E6%25A9%259F%25E3%2583%25B4%25E3%2582%25A1%25E3%2583%25AB%25E3%2583%25B4%25E3%2583%25AC%25E3%2582%25A4%25E3%2583%25B4+D"

def push_to_github():
    """取得したデータを自動的にGitHubへアップロードする（輸送フェーズ）"""
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
    """人間らしいランダムな待機"""
    page.wait_for_timeout(int(random.uniform(min_sec, max_sec) * 1000))

def handle_popups(page):
    """邪魔なポップアップを即座に排除"""
    popup_buttons = ["閉じる", "OK", "x", "×"]
    for btn_text in popup_buttons:
        try:
            loc = page.get_by_text(btn_text, exact=True).first
            if loc.count() > 0 and loc.is_visible():
                loc.click(force=True, timeout=1000)
        except: pass

def detect_captcha(page) -> bool:
    """CAPTCHA（ロボット確認）が表示されているか検知"""
    keywords = ["私は人間です", "ロボットではありません", "ロボットですか", "確認コード", "画像を選択"]
    for kw in keywords:
        if page.get_by_text(kw, exact=False).count() > 0:
            return True
    # iframeの中にある場合も考慮（簡易検知）
    if page.locator("iframe[src*='captcha'], iframe[src*='recaptcha']").count() > 0:
        return True
    return False

def wait_for_captcha_bypass(page):
    """人間がCAPTCHAを解除するのをじっと待つ"""
    if detect_captcha(page):
        print("\n⚠️ 警告: セキュリティ・チャレンジ（ロボット確認）を検知しました。")
        print("💡 ブラウザ上で手動でチェックを入れ、パズルを解いてください。")
        print("💡 一度解けば、次回からはセッションが維持される設定に変更しました。")
        
        # 台番号または特定の要素が表示されるまで、最大10分間待機
        try:
            page.wait_for_selector("text=BONUS, .machine-name, .dai-number", timeout=600000)
            print("✅ 人間による解除を確認しました。処理を再開します。")
            page.wait_for_timeout(2000)
        except:
            print("❌ 待機タイムアウト。プログラムを終了します。")
            return False
    return True

def extract_precise_data(page):
    """ページ内から特定のラベルに基づきデータを精密抽出"""
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
        bonus_indices = [i for i, line in enumerate(lines) if "BONUS" in line.upper()]
        
        for idx in bonus_indices:
            for j in range(idx, min(idx + 40, len(lines))):
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
    """ページから全台番号を自動抽出"""
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
    cleaned = sorted(list(set([d.zfill(4) for d in raw_dais if d.isdigit() and 111 <= int(d) <= 500])))
    print(f"純化された台番号（計 {len(cleaned)} 台）: {cleaned}")
    return cleaned

def patrol_dai_list(page, dais):
    """全台を巡回してデータを強奪"""
    first_dai = dais[0]
    print(f"台番号をクリック中: {first_dai}")
    for d in [first_dai, first_dai.lstrip("0")]:
        loc = page.get_by_text(d, exact=True).first
        if loc.count() > 0:
            loc.click(force=True)
            break
    
    print("初回アクセスのため、データ描画を待ちます...")
    page.wait_for_timeout(5000)

    for i, dai in enumerate(dais):
        print(f"\n========== 台番号 {dai} ==========")
        handle_popups(page)
        
        # データの出現を待つ
        try:
            page.wait_for_selector("text=BONUS", timeout=10000)
        except: pass

        extracted = extract_precise_data(page)
        
        if any(v != "未検出" for v in extracted.values()):
            save_to_csv(dai, extracted)
            print(f"台番号 {dai}: 抽出成功")
        else:
            print(f"⚠️ 台番号 {dai}: 抽出失敗（未検出）")

        if i < len(dais) - 1:
            next_btn = page.locator("text=次台, text=>>, text=次へ").first
            if next_btn.count() > 0:
                next_btn.click()
                wait_random(page)
            else:
                print("「次台」ボタンが見つかりません。")
                break

def save_to_csv(dai_no, data):
    fn = "master_data.csv"
    today = datetime.now().strftime("%Y-%m-%d")
    labels = ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    exists = os.path.isfile(fn)
    try:
        with open(fn, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not exists:
                writer.writerow(["取得日", "台番号"] + labels)
            writer.writerow([today, dai_no] + [data.get(l, "未検出") for l in labels])
    except Exception as e:
        print(f"CSV保存エラー: {e}")

def main():
    with sync_playwright() as p:
        # プロファイル保存用フォルダ（なければ作成）
        user_data_dir = os.path.join(os.getcwd(), "user_data")
        
        # 永続コンテキスト（セッション情報を保存するモード）で起動
        # ※ブラウザとコンテキストが合体したような動作になります
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        # 永続コンテキストでは最初から1枚ページが開いているため、それを使う
        page = context.pages[0]

        try:
            print(f"目的の機種ページへアクセス中...")
            page.goto(TARGET_URL, wait_until="networkidle")
            
            # ロボット確認が出た場合の待機（一度解除すれば次回は出にくくなります）
            if not wait_for_captcha_bypass(page):
                return

            dais = get_all_target_dais(page)
            if dais:
                patrol_dai_list(page, dais)
                push_to_github()
            else:
                print("エラー: 台番号が見つかりませんでした。")
            
        except Exception as e:
            print(f"実行エラー: {e}")
        finally:
            print("5秒後に終了します...")
            page.wait_for_timeout(5000)
            context.close() # 永続コンテキストを閉じることでデータが保存されます

if __name__ == "__main__":
    main()