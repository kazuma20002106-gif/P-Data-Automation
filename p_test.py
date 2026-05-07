import re
import random
import os
import csv
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/"
STATE_PATH = Path("state.json")

SEARCH_KEYWORD = "ヴァルヴレイヴ"
TARGET_MACHINE_NAME = "L革命機ヴァルヴレイヴ D"

# 対象となる台番号リスト（動的に取得するため初期化）
TARGET_DAI = []


def wait_random(page, min_sec=4.5, max_sec=7.5):
    wait_ms = int(random.uniform(min_sec, max_sec) * 1000)
    page.wait_for_timeout(wait_ms)

def handle_popups(page):
    """
    【新機能】画面を覆っているエラーや広告のポップアップを検知して消し去る
    """
    popup_buttons = ["閉じる", "OK", "決定", "Close", "同意する", "x", "×"]
    
    for btn_text in popup_buttons:
        try:
            # 画面に見えているボタンをすべてクリック
            locators = page.get_by_text(btn_text, exact=True)
            count = locators.count()
            for i in range(count):
                btn = locators.nth(i)
                if btn.is_visible():
                    print(f"ポップアップ・バスター：ボタン「{btn_text}」をクリックして消去します。")
                    btn.click(force=True, timeout=3000)
                    page.wait_for_timeout(1000)
        except:
            pass

def detect_captcha(page) -> bool:
    keywords = ["私は人間です", "ロボットではありません", "ロボットでないことを確認"]
    for keyword in keywords:
        try:
            elements = page.get_by_text(keyword, exact=False)
            count = elements.count()
            for i in range(count):
                if elements.nth(i).is_visible():
                    return True
        except:
            pass
    return False

def wait_for_manual_captcha_clear(page):
    raise Exception("Cloud environment detected CAPTCHA. Aborting.")

def save_to_csv(dai_no, extracted_data):
    """
    データをマスターCSVファイルに永続的に蓄積する。
    ファイルが存在しない場合はヘッダーを自動生成する。
    """
    filename = "master_data.csv"
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    labels = ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    file_exists = os.path.isfile(filename)
    
    try:
        with open(filename, mode='a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            if not file_exists:
                # 1列目に取得日を追加
                header = ["取得日", "台番号"] + labels
                writer.writerow(header)
                
            # データ行の1列目にも取得日を挿入
            row_data = [today_str, dai_no]
            for label in labels:
                row_data.append(extracted_data.get(label, "未検出"))
                
            writer.writerow(row_data)
            print(f"台番号 {dai_no} のデータを {filename} に蓄積しました。")
    except Exception as e:
        print(f"CSV保存中にエラーが発生しました: {e}")

def extract_precise_data(page):
    labels = ["BONUS", "BIG", "REG", "BIG確率", "REG確率", "最大継続", "合成確率", "累計ゲーム", "最終ゲーム", "最大放出数"]
    result = {label: "未検出" for label in labels}
    
    # TreeWalkerを使用して純粋なテキストノードを配列化するJS
    js_code = r"""
    () => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        const textNodes = [];
        let node;
        while(node = walker.nextNode()) {
            const txt = node.nodeValue.trim();
            if(txt !== "") {
                textNodes.push(txt);
            }
        }
        return textNodes;
    }
    """
    
    try:
        # JSを実行し、テキストノードの配列をPythonで受け取る
        lines = page.evaluate(js_code)
        
        # BONUSのインデックスをすべて探す
        bonus_indices = [i for i, line in enumerate(lines) if line == "BONUS" or line.startswith("BONUS ")]
        
        for idx in bonus_indices:
            end_label_idx = -1
            # BONUSから最大15個先まで探索し、ラベル列の終わり「最大放出数」を探す
            for j in range(idx, min(idx + 16, len(lines))):
                if lines[j] == "最大放出数" or lines[j].startswith("最大放出数 "):
                    end_label_idx = j
                    break
            
            if end_label_idx != -1:
                # ラベル列の塊（ブロック）
                current_labels = lines[idx : end_label_idx + 1]
                # その直後に来るデータ列の塊（ブロック）
                data_start_idx = end_label_idx + 1
                current_data = lines[data_start_idx : data_start_idx + len(current_labels)]
                
                # インデックスを同期させて順番通りにマッピング
                for l_idx, l_str in enumerate(current_labels):
                    # 前方一致などでゴミが入っている可能性も考慮し、純粋なラベル名に補正
                    matched_label = None
                    for label in labels:
                        if l_str == label or l_str.startswith(label + " ") or l_str.startswith(label + ":"):
                            matched_label = label
                            break
                            
                    if matched_label and l_idx < len(current_data):
                        val = current_data[l_idx]
                        
                        # 数値または確率表記か判定（カンマ、小数点、スラッシュを含む）
                        if re.match(r'^[\d.,/]+$', val):
                            result[matched_label] = val
                        else:
                            # テキスト内に数値が含まれる場合のフォールバック抽出
                            match = re.search(r'([\d.,/]+)', val)
                            if match:
                                result[matched_label] = match.group(1)
                                
                # BONUSが正常に抽出できていれば、正しいブロックを見つけたと判断して探索終了
                if result["BONUS"] != "未検出":
                    break
                    
    except Exception as e:
        print(f"テキスト抽出でエラー発生: {e}")
            
    filtered_result = {k: v for k, v in result.items() if v != "未検出"}
    return filtered_result if filtered_result else {"データ": "全て未検出"}

# (機種検索とクリックはURL直アクセスにより不要となったため削除済)

def click_dai_number(page, dai_no):
    print(f"台番号を検索中: {dai_no}")
    normalized = dai_no.lstrip("0")
    candidates = [page.get_by_text(dai_no, exact=True), page.get_by_text(normalized, exact=True)]
    for locator in candidates:
        if locator.count() > 0:
            target = locator.first
            target.scroll_into_view_if_needed()
            target.click(force=True)
            page.wait_for_load_state("domcontentloaded")
            return True
    return False

def scrape_detail_page(page, dai_no):
    print(f"\n========== 台番号 {dai_no} ==========")
    handle_popups(page)
    print("データの描画を待機しています（最大5秒）...")
    try:
        page.wait_for_selector("text=BONUS", state="visible", timeout=5000)
        print("データの描画を検知しました。抽出を開始します。")
    except Exception:
        print("データ描画の待機がタイムアウトしました（既に描画済みの可能性もあります）。")
        
    handle_popups(page)

    extracted = extract_precise_data(page)
    
    if extracted.get("データ") == "全て未検出":
        print("データが未検出です。リロードして再試行します...")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        handle_popups(page)
        extracted = extract_precise_data(page)

    for key, value in extracted.items():
        print(f"{key}: {value}")
        
    if extracted.get("データ") != "全て未検出":
        save_to_csv(dai_no, extracted)
        
    # ※画像撮影に関する処理は完全にパージ（削除）済

def get_all_target_dais(page):
    print("ページから対象の全台番号を自動抽出します...")
    page.wait_for_timeout(3000)
    
    js_code = r"""
    () => {
        const els = document.querySelectorAll('a, div, span, button');
        const dais = new Set();
        for (let el of els) {
            let txt = el.innerText;
            if (!txt) continue;
            txt = txt.trim();
            // P-CUBEでは「0111」や「0111番台」のように表示されることが多い
            if (/^\d{3,4}$/.test(txt)) {
                dais.add(txt);
            } else if (/^\d{3,4}番台$/.test(txt)) {
                dais.add(txt.replace('番台', ''));
            }
        }
        return Array.from(dais).sort((a, b) => parseInt(a) - parseInt(b));
    }
    """
    raw_dais = page.evaluate(js_code)
    
    # 最強の純化フィルター
    cleaned_dais = []
    for d in raw_dais:
        d = d.strip()
        if d.isdigit():
            # 4桁にゼロ埋め
            padded = d.zfill(4)
            # 0から始まる4桁（1000番台以上のノイズを消すため）であれば追加
            if padded.startswith("0") and len(padded) == 4:
                # さらに "0100" や "0109" といった明らかなノイズ（111より前）を弾く
                if int(padded) >= 111:
                    cleaned_dais.append(padded)

    # 重複排除とソート
    final_dais = sorted(list(set(cleaned_dais)))
    print(f"純化された台番号（計 {len(final_dais)} 台）: {final_dais}")
    return final_dais

def patrol_dai_list(page):
    if not TARGET_DAI:
        return
        
    first_dai = TARGET_DAI[0]
    try:
        wait_random(page)
        # まず最初の台をクリックして詳細ページへ
        if click_dai_number(page, first_dai):
            if detect_captcha(page): wait_for_manual_captcha_clear(page)
            # 初回アクセスの描画遅延に対応する確実な待機（3秒）
            print("初回アクセスのため、データ描画を確実に待ちます（3秒）...")
            page.wait_for_timeout(3000)
            scrape_detail_page(page, first_dai)
            wait_random(page)
            
            # 以降は「次台」ボタンを使用して全台を横移動巡回（リミッター解除）
            for i in range(1, len(TARGET_DAI)):
                next_dai = TARGET_DAI[i]
                try:
                    print(f"「次台」ボタンを探して、次の台 ({next_dai}) へ遷移します...")
                    
                    next_btn_candidates = [
                        page.get_by_role("button", name=re.compile("次台|次へ|>>")),
                        page.get_by_text(re.compile("次台|次へ|>>|次の台")),
                        page.locator("a:has-text('次台')"),
                        page.locator("a:has-text('>>')")
                    ]
                    
                    clicked = False
                    for btn_loc in next_btn_candidates:
                        if btn_loc.count() > 0 and btn_loc.first.is_visible():
                            btn_loc.first.click()
                            page.wait_for_load_state("domcontentloaded")
                            clicked = True
                            break
                            
                    if not clicked:
                        print("「次台」ボタンが見つかりませんでした。巡回を終了します。")
                        break
                        
                    wait_random(page)
                    if detect_captcha(page): wait_for_manual_captcha_clear(page)
                    
                    # 【安全装置】機種名がまだ同じか確認
                    machine_name_visible = False
                    if page.get_by_text(TARGET_MACHINE_NAME, exact=False).count() > 0 or \
                       page.get_by_text("ヴァルヴレイヴ", exact=False).count() > 0:
                        machine_name_visible = True
                        
                    if not machine_name_visible:
                        print("【警告】機種名の表示が見つかりません。別の機種に遷移した可能性があるため巡回を中止します。")
                        break
                        
                    scrape_detail_page(page, next_dai)
                except Exception as e:
                    print(f"【巡回スキップ】台番号 {next_dai} の処理中にエラーが発生しました: {type(e).__name__} - {e}")
                    if "Target closed" in str(e) or "TargetClosedError" in type(e).__name__ or "Browser closed" in str(e):
                        print("【重要】ブラウザの強制終了を検知しました。本日の偵察を安全に終了します。")
                        return
                    continue
                
    except Exception as e:
        print(f"巡回中にエラーが発生しました: {e}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_options = {
            "viewport": {"width": 1366, "height": 900},
            "locale": "ja-JP",
            "timezone_id": "Asia/Tokyo",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "java_script_enabled": True,
            "bypass_csp": True,
            "extra_http_headers": {
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Upgrade-Insecure-Requests": "1"
            }
        }
        if STATE_PATH.exists(): context_options["storage_state"] = str(STATE_PATH)
        context = browser.new_context(**context_options)
        page = context.new_page()
        
        # navigator.webdriverの無効化（超重要：Playwrightの痕跡を消し去る）
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        print("目的の機種ページへ直接アクセスします...")
        TARGET_URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/cgi-bin/nc-v05-003.php?cd_ps=2&bai=21.7391&nmk_kisyu=L+%25E9%259D%25A9%25E5%2591%25BD%25E6%25A9%259F%25E3%2583%25B4%25E3%2582%25A1%25E3%2583%25AB%25E3%2583%25B4%25E3%2583%25AC%25E3%2582%25A4%25E3%2583%25B4+D"
        page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        
        if detect_captcha(page):
            raise Exception("CAPTCHA Blocked.")
            
        context.storage_state(path=str(STATE_PATH))
        
        global TARGET_DAI
        if not TARGET_DAI:
            TARGET_DAI = get_all_target_dais(page)
            
        patrol_dai_list(page)
        
        browser.close()

if __name__ == "__main__":
    main()