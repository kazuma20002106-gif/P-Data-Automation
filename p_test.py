import re
import random
import os
import csv
import subprocess
import traceback
from datetime import datetime
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

URL = "https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c721601/"
SEARCH_KEYWORD = "ヴァルヴレイヴ"
TARGET_MACHINE_NAME = "L革命機ヴァルヴレイヴ D"

# 対象となる台番号リスト（動的に取得するため初期化）
TARGET_DAI = []

def push_to_github():
    print("\n--- [SYNC] クラウド同期フェーズ ---")
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(["git", "add", "master_data.csv"], check=True, capture_output=True)
        res = subprocess.run(["git", "commit", "-m", f"Auto-update: {now_str}"], capture_output=True, text=True)
        if "nothing to commit" not in res.stdout:
            subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
            print("✅ [SYNC] クラウドへの輸送が完了しました。")
    except FileNotFoundError:
        print("💡 [INFO] Gitコマンドが見つかりません。データはPC内に安全に保存されています。")
    except Exception as e:
        print(f"⚠️ [SYNC] 同期スキップ (ローカル保存は完了しています)")

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
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("クラウド上では手動CAPTCHA解除が不可能なため、即座にエラーとして終了します。")
        page.screenshot(path="debug_screen.png", full_page=True)
        raise Exception("クラウド環境でCAPTCHAが検出されました。ボット対策によりブロックされました。")
        
    print("CAPTCHAが検出されました。手動でCAPTCHAを解除してください。")
    for _ in range(300):
        page.wait_for_timeout(1000)
        try:
            if not detect_captcha(page):
                print("CAPTCHAの解除を確認しました。処理を再開します。")
                page.wait_for_timeout(3000)
                return
        except:
            pass
    raise TimeoutError("CAPTCHA解除待機がタイムアウトしました。")

def find_visible_input(page):
    input_candidates = ["input[type='text']", "input[type='search']", "input[type='number']", "input"]
    for selector in input_candidates:
        locators = page.locator(selector)
        for i in range(locators.count()):
            candidate = locators.nth(i)
            if candidate.is_visible() and candidate.is_enabled():
                return candidate
    return None

def click_search_or_press_enter(page, target_input):
    icon_selectors = ["button[type='submit']", "img[src*='search']", "img[src*='icon_search']", "button[class*='search']"]
    for selector in icon_selectors:
        try:
            elements = page.locator(selector)
            for i in range(elements.count()):
                btn = elements.nth(i)
                if btn.is_visible():
                    btn.click()
                    return True
        except: pass
    target_input.press("Enter")
    return False

def search_machine(page, keyword):
    print(f"検索キーワード「{keyword}」を入力します。")
    target_input = find_visible_input(page)
    if not target_input: raise Exception("入力欄未検出")
    target_input.fill("")
    target_input.type(keyword, delay=120)
    click_search_or_press_enter(page, target_input)
    print("検索処理を実行しました。ページ遷移を確実に待ちます...")
    page.wait_for_timeout(6000) 

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
    """【Phase 9.3】黄金律・自動アライメント（ズレ補正）抽出ロジック"""
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
        
        # BONUSの位置を探す（ブロックの先頭）
        bonus_indices = [i for i, line in enumerate(lines) if line == "BONUS" or line.startswith("BONUS ")]
        for idx in bonus_indices:
            end_label_idx = -1
            # ブロックの終端「最大放出数」を探す
            for j in range(idx, min(idx + 16, len(lines))):
                if lines[j] == "最大放出数" or lines[j].startswith("最大放出数 "):
                    end_label_idx = j
                    break
            
            if end_label_idx != -1:
                current_labels = lines[idx : end_label_idx + 1]
                data_start_idx = end_label_idx + 1
                
                # データを多め（約20個）に取得し、ズレ判定の素材とする
                candidate_data = lines[data_start_idx : min(data_start_idx + 20, len(lines))]
                
                # --- 【自動アライメント（位置合わせ）処理】 ---
                # 1. ラベル側の「確率」が最初に出現するインデックス（通常は3 = BIG確率）
                expected_prob_idx = next((i for i, l in enumerate(current_labels) if "確率" in l), -1)
                
                # 2. データ側の「確率フォーマット（1/xxx）」が最初に出現するインデックス
                actual_prob_idx = -1
                for i, val in enumerate(candidate_data):
                    if re.match(r'^1/[\d.,]+$', val):
                        actual_prob_idx = i
                        break
                
                # 3. ズレ（オフセット）の計算
                offset = 0
                if expected_prob_idx != -1 and actual_prob_idx != -1:
                    offset = actual_prob_idx - expected_prob_idx
                    if offset < 0: offset = 0 # 負のズレは想定外のため0
                
                # 4. ズレを適用し、不純物を切り捨てて正しいデータを抽出
                aligned_data = candidate_data[offset : offset + len(current_labels)]
                # ---------------------------------------------
                
                # ラベルと補正済みデータをマッピング
                for l_idx, l_str in enumerate(current_labels):
                    matched_label = None
                    for label in labels:
                        if l_str == label or l_str.startswith(label + " ") or l_str.startswith(label + ":"):
                            matched_label = label
                            break
                    
                    if matched_label and l_idx < len(aligned_data):
                        val = aligned_data[l_idx]
                        # 記号や不要文字を除去し、数値・ハイフンのみを保存
                        match = re.search(r'([\d.,/\-]+)', val)
                        if match:
                            result[matched_label] = match.group(1)
                
                if result["BONUS"] != "未検出":
                    break
                    
    except Exception as e:
        print(f"テキスト抽出でエラー発生: {e}")
        
    filtered_result = {k: v for k, v in result.items() if v != "未検出"}
    return filtered_result if filtered_result else {"データ": "全て未検出"}

def click_machine_name(page):
    print(f"機種を検索中: {TARGET_MACHINE_NAME}")
    
    # 強化ポイント：表記揺れを全て網羅する広域レーダーの復活
    search_patterns = [
        "L革命機ヴァルヴレイヴ D",
        "L革命機ヴァルヴレイヴD",
        "革命機ヴァルヴレイヴ"
    ]
    
    target_element = None
    print("機種の表示を探すため、画面を探索します...")
    
    for _ in range(15): 
        for pattern in search_patterns:
            try:
                # exact=False で部分一致を許容し、逃さずキャッチする
                locators = page.get_by_text(pattern, exact=False)
                for i in range(locators.count()):
                    if locators.nth(i).is_visible():
                        target_element = locators.nth(i)
                        break
            except: pass
            if target_element: break
        if target_element: break
            
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(1000)

    if target_element:
        print("ターゲットを確認しました。貫通クリックを実行します。")
        target_element.scroll_into_view_if_needed()
        target_element.click(force=True)
        page.wait_for_load_state("domcontentloaded")
        wait_random(page)
        return
        
    page.screenshot(path="debug_machine_not_found.png", full_page=True)
    raise Exception("機種未検出: debug_machine_not_found.png を確認してください。")

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
        is_github = os.getenv("GITHUB_ACTIONS") == "true"
        
        if is_github:
            print("☁️ GitHub Actions 環境での実行を検知しました。仮想ブラウザを起動します。")
            browser = p.chromium.launch(
                headless=False,
                slow_mo=300,
                args=['--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(
                storage_state="state.json" if os.path.exists("state.json") else None,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 900},
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                bypass_csp=True,
                extra_http_headers={
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    "Upgrade-Insecure-Requests": "1"
                }
            )
            page = context.new_page()
        else:
            print("💻 ローカルPC環境での実行を検知しました。永続プロファイルをロードします。")
            user_data_dir = os.path.abspath("./user_data_victory")
            context = p.chromium.launch_persistent_context(
                user_data_dir, 
                headless=False, 
                slow_mo=300,
                args=['--disable-blink-features=AutomationControlled'],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 900},
                locale="ja-JP",
                timezone_id="Asia/Tokyo",
                bypass_csp=True,
                extra_http_headers={
                    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                    "Upgrade-Insecure-Requests": "1"
                }
            )
            page = context.pages[0]
        
        # ボット検知回避（stealth）を適用
        stealth_sync(page)
        
        # navigator.webdriverの無効化（超重要：Playwrightの痕跡を消し去る）
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print("ページへアクセス中...")
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            
            search_machine(page, SEARCH_KEYWORD)
            if detect_captcha(page): wait_for_manual_captcha_clear(page)
            
            click_machine_name(page)
            
            global TARGET_DAI
            if not TARGET_DAI:
                TARGET_DAI = get_all_target_dais(page)
                
            patrol_dai_list(page)
            
            # 【自動同期】
            push_to_github()
            
        except Exception as e:
            print(f"\n[CRITICAL ERROR] 重大なエラーが発生しました:")
            traceback.print_exc()
        finally:
            if not is_github:
                print("クラウド環境と同期するため、現在のブラウザセッションを state.json に保存します...")
                context.storage_state(path="state.json")
            page.wait_for_timeout(5000)
            context.close()

if __name__ == "__main__":
    main()