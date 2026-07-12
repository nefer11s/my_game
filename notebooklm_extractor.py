import os
import sys
import json
import re
import time
import argparse

# 윈도우 환경에서 출력 인코딩 오류 예방
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# NotebookLM MCP 모듈 임포트
from notebooklm_tools.core.client import NotebookLMClient
from notebooklm_tools.utils.cdp import extract_cookies_via_existing_cdp
import notebooklm_tools.core.base as base

# 윈도우 크롬 User-Agent 멍키패치 적용
WINDOWS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
base.BaseClient._PAGE_FETCH_HEADERS["User-Agent"] = WINDOWS_UA

# _get_client / _get_async_client User-Agent 패치
original_get_client = base.BaseClient._get_client
def patched_get_client(self):
    client = original_get_client(self)
    client.headers["User-Agent"] = WINDOWS_UA
    return client
base.BaseClient._get_client = patched_get_client

original_get_async_client = base.BaseClient._get_async_client
def patched_get_async_client(self):
    client = original_get_async_client(self)
    client.headers["User-Agent"] = WINDOWS_UA
    return client
base.BaseClient._get_async_client = patched_get_async_client


# 천간 정의
STEMS = [
    '갑목(甲木)', '을목(乙木)', '병화(丙火)', '정화(丁火)', '무토(戊土)', 
    '기토(己土)', '경금(庚金)', '신금(辛金)', '임수(壬水)', '계수(癸水)'
]

# 계절 및 해당 월 정의
SEASONS = {
    '봄': {'desc': '봄 (인묘진월)', 'months': ['인월(寅月)', '묘월(卯月)', '진월(辰月)']},
    '여름': {'desc': '여름 (사오미월)', 'months': ['사월(巳月)', '오월(午月)', '미월(未月)']},
    '가을': {'desc': '가을 (신유술월)', 'months': ['신월(申月)', '유월(酉月)', '술월(戌月)']},
    '겨울': {'desc': '겨울 (해자축월)', 'months': ['해월(亥月)', '자월(子月)', '축월(丑月)']}
}

CHECKPOINT_FILE = 'checkpoint_extraction.json'
PDF_PATH = r"docs\nss-궁통보감-2023-fin_unlocked.pdf"
NOTEBOOK_TITLE = "궁통보감 사주 AI"

def get_live_client(retries=3):
    """CDP를 통해 실시간 크롬 세션을 하이재킹하여 NotebookLMClient 객체 생성"""
    for attempt in range(retries + 1):
        try:
            # 9222 포트의 디버깅 크롬 브라우저로부터 라이브 세션 추출
            result = extract_cookies_via_existing_cdp("http://127.0.0.1:9222", wait_for_login=True, login_timeout=15)
            
            client = NotebookLMClient(
                cookies=result["cookies"],
                csrf_token=result["csrf_token"],
                session_id=result["session_id"],
                build_label=result["build_label"]
            )
            return client
        except Exception as e:
            if attempt == retries:
                raise e
            print(f"    [!] Failed to connect to Chrome session (Attempt {attempt+1}/{retries+1}): {e}. Retrying in 5 seconds...")
            time.sleep(5)

def get_notebook_id(client):
    """기존 '궁통보감 사주 AI' 노트북 ID 조회, 없을 시 신규 생성"""
    print(f"[*] Checking for existing notebook: '{NOTEBOOK_TITLE}'...")
    notebooks = client.list_notebooks()
    
    for nb in notebooks:
        # 객체 속성 및 dict 키 접근 둘 다 안전하게 지원
        title = nb.title if hasattr(nb, "title") else nb.get("title", "")
        if NOTEBOOK_TITLE in title or title == NOTEBOOK_TITLE:
            notebook_id = nb.id if hasattr(nb, "id") else nb.get("id")
            print(f"[+] Found existing notebook. ID: {notebook_id}")
            return notebook_id
            
    # 없는 경우 새로 생성
    print(f"[*] Creating a new notebook named '{NOTEBOOK_TITLE}'...")
    new_nb = client.create_notebook(NOTEBOOK_TITLE)
    nid = new_nb.id if hasattr(new_nb, "id") else new_nb.get("id")
    print(f"[+] Notebook created successfully. ID: {nid}")
    return nid

def upload_pdf_source(client, notebook_id):
    """노트북에 궁통보감 PDF 소스가 있는지 검사 및 업로드"""
    print("[*] Checking notebook sources...")
    sources = client.get_notebook_sources_with_types(notebook_id)
            
    pdf_filename = os.path.basename(PDF_PATH)
    for src in sources:
        if pdf_filename in src.get("title", "") or "궁통보감" in src.get("title", ""):
            print(f"[+] PDF Source already exists in notebook. Source ID: {src['id']}")
            return src["id"]
            
    print(f"[*] PDF Source not found. Uploading '{PDF_PATH}' to notebook (This may take a few minutes)...")
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"Source PDF file not found at: {PDF_PATH}")
        
    # Python API의 add_file(notebook_id, file_path, wait=True) 호출
    upload_result = client.add_file(notebook_id, PDF_PATH, wait=True, wait_timeout=300.0)
    print("[+] PDF uploaded and processed successfully!")
    return upload_result.get("id")

def clean_json_text(text):
    """답변 텍스트에서 JSON 배열 부분만 추출하여 깔끔하게 정제"""
    match = re.search(r'```(?:json)?\s*(\[\s*\{.*\}\s*\])\s*```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
        
    match_arr = re.search(r'(\[\s*\{.*\}\s*\])', text, re.DOTALL)
    if match_arr:
        return match_arr.group(1).strip()
        
    return text.strip()

def query_client_with_retry(client, notebook_id, question, conversation_id=None, retries=2):
    """NotebookLM 쿼리 전송 및 재시도 처리"""
    for attempt in range(retries + 1):
        try:
            # list_notebooks를 가볍게 찔러서 세션 활성화
            client.list_notebooks()
            
            # query(notebook_id, question, conversation_id=conversation_id) 호출
            result = client.query(notebook_id, question, conversation_id=conversation_id)
            answer = result.get("answer", "")
            conv_id = result.get("conversation_id", "")
            return answer, conv_id
        except Exception as e:
            if attempt == retries:
                raise e
            print(f"    [!] Query failed (Attempt {attempt+1}/{retries+1}): {e}. Re-binding session and retrying in 5 seconds...")
            # 세션 만료 가능성을 예방하기 위해 CDP를 통해 클라이언트를 재생성합니다.
            try:
                client = get_live_client()
            except Exception:
                pass
            time.sleep(5)

def extract_stem_season(client, notebook_id, stem, season_name, season_info):
    """1개 천간 x 1개 계절에 대해 3단계 재귀검증 추출 실행"""
    months_str = ", ".join(season_info['months'])
    print(f"\n>>> Processing: {stem} - {season_info['desc']}")
    
    # -------------------------------------------------------------
    # [1단계: 초기 데이터 추출]
    # -------------------------------------------------------------
    print("  [Step 1] Requesting initial data extraction...")
    prompt_extract = (
        f"궁통보감 원문을 바탕으로 {stem}의 {season_info['desc']}({months_str}) 케이스에 대한 사주 AI 조건식 표를 JSON 형식으로 정리해줘. "
        f"반드시 아래 JSON 스키마를 완벽하게 준수하여 각 월별(총 3개 객체) 배열 형식으로만 답변해야 해. "
        f"설명이나 서두, 끝인사 같은 다른 텍스트는 배제하고 오직 규격에 맞춘 JSON 마크다운 코드블록(```json ... ```)으로만 반환해줘.\n\n"
        "JSON Schema:\n"
        "[\n"
        "  {\n"
        f"    \"일간\": \"{stem}\",\n"
        f"    \"계절\": \"{season_name}\",\n"
        "    \"월별\": \"인월(寅月) 또는 묘월(卯月) 또는 진월(辰月) 등 해당하는 월명\",\n"
        "    \"조후_및_용신\": {\n"
        "      \"핵심용신\": \"문헌에서 제시한 핵심 용신 오행/글자\",\n"
        "      \"보조용신\": \"보조 용신 또는 희신 오행/글자\",\n"
        "      \"취용요약\": \"해당 월령의 조후 및 억부 핵심 취용 요약\"\n"
        "    },\n"
        "    \"조건식\": [\n"
        "      {\n"
        "        \"조건\": \"명리학적 세부 조건 (예: 어떤 글자가 투출하거나 지지에 국을 이룰 때)\",\n"
        "        \"결과\": \"그 조건에 따른 성격(成格) 여부, 용신 선택법, 삶의 부귀빈천 결과\"\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "]"
    )
    
    answer_draft, conv_id = query_client_with_retry(client, notebook_id, prompt_extract)
    
    # -------------------------------------------------------------
    # [2단계: 1차 팩트체크 - 원전 교차 검증]
    # -------------------------------------------------------------
    print("  [Step 2] Performing 1st Fact-Check: Checking for cross-contamination of other stems...")
    prompt_fc1 = (
        f"방금 답변한 {stem}의 {season_name} JSON 데이터에 다른 천간(예: {stem} 외의 다른 오행 천간의 명조나 규칙)의 내용이 부주의하게 섞여 들어갔는지 "
        "궁통보감 원문 내용과 다시 한 번 정밀하게 교차 검증해줘. "
        "오류나 혼입이 발견된다면 수정 보정하고, 아무 설명 없이 보정된 최종 JSON 배열(```json ... ```)만 다시 출력해줘."
    )
    
    answer_fc1, conv_id = query_client_with_retry(client, notebook_id, prompt_fc1, conversation_id=conv_id)
    
    # -------------------------------------------------------------
    # [3단계: 2차 팩트체크 - 명리학 논리 검증]
    # -------------------------------------------------------------
    print("  [Step 3] Performing 2nd Fact-Check: Validating astrological logic consistency...")
    prompt_fc2 = (
        f"수정된 {stem}의 {season_name} JSON 데이터 내에서 용신, 보조용신, 희신, 기신 간의 생극제화와 조후 관계상 명리학적 모순(예: 기신과 용신이 섞였거나, 생조 관계가 붕괴되는 오류)이 없는지 논리적으로 최종 검증해줘. "
        "모순이 있다면 명리학 이치에 맞게 보정하고, 마찬가지로 설명 없이 오직 최종 완성된 JSON 배열(```json ... ```)만 최종 출력해줘."
    )
    
    answer_fc2, conv_id = query_client_with_retry(client, notebook_id, prompt_fc2, conversation_id=conv_id)
    
    # -------------------------------------------------------------
    # [4단계: JSON 파싱 및 구조 유효성 검사]
    # -------------------------------------------------------------
    print("  [Step 4] Parsing JSON and validating structure...")
    cleaned_json = clean_json_text(answer_fc2)
    
    try:
        parsed_data = json.loads(cleaned_json)
        if not isinstance(parsed_data, list):
            raise ValueError("Parsed data is not a list (array).")
            
        validated_list = []
        for item in parsed_data:
            monthly_record = {}
            monthly_record["일간"] = item.get("일간") or item.get("천간") or stem
            monthly_record["계절"] = item.get("계절") or season_name
            monthly_record["월별"] = item.get("월별") or item.get("월") or ""
            
            johoo_data = item.get("조후_및_용신") or {}
            monthly_record["핵심용신"] = johoo_data.get("핵심용신") or item.get("핵심용신") or ""
            monthly_record["보조용신"] = johoo_data.get("보조용신") or item.get("보조용신") or ""
            monthly_record["취용요약"] = johoo_data.get("취용요약") or item.get("조후요약") or item.get("취용요약") or ""
            
            cond_list = item.get("조건식") or []
            if not isinstance(cond_list, list):
                cond_list = []
            
            if not cond_list and item.get("명리학적조건식"):
                cond_list = [{"조건": "기본", "결과": item.get("명리학적조건식")}]
                
            monthly_record["조건식"] = cond_list
            validated_list.append(monthly_record)
            
        print(f"  [+] Step 4 Success! Extracted {len(validated_list)} monthly records.")
        return validated_list
    except Exception as e:
        print(f"  [!] JSON parsing/validation failed: {e}")
        # 실패 시 디버깅을 위해 생 텍스트 저장
        debug_file = f"data/error_{stem.replace('(', '_').replace(')', '')}_{season_name}.txt"
        os.makedirs("data", exist_ok=True)
        with open(debug_file, "w", encoding="utf-8") as df:
            df.write(answer_fc2)
        print(f"  [!] Raw text saved to {debug_file} for manual review.")
        raise e

def load_checkpoint():
    """체크포인트 파일 로드"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"completed": [], "records": []}
    return {"completed": [], "records": []}

def save_checkpoint(completed_keys, records):
    """체크포인트 파일 저장"""
    checkpoint_data = {
        "completed": completed_keys,
        "records": records
    }
    with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)

def main():
    parser = argparse.ArgumentParser(description="NotebookLM Gungtong Extraction Pipeline")
    parser.add_argument("--test", action="store_true", help="Run in test mode for only 1 stem/season")
    args = parser.parse_args()
    
    print("=== Gungtongbagam AI Database Extraction Pipeline ===")
    
    # 1. 라이브 클라이언트 생성 (CDP 연동)
    try:
        client = get_live_client()
        print("[+] CDP Connection successfully established.")
    except Exception as e:
        print(f"[!] CDP connection failed: {e}")
        print("[!] Please ensure Chrome is running on port 9222 and logged in to NotebookLM.")
        sys.exit(1)
        
    # 2. 노트북 획득
    try:
        notebook_id = get_notebook_id(client)
    except Exception as e:
        print(f"[!] Failed to get notebook ID: {e}")
        sys.exit(1)
        
    # 3. PDF 소스 업로드
    try:
        upload_pdf_source(client, notebook_id)
    except Exception as e:
        print(f"[!] Source PDF upload failed: {e}")
        sys.exit(1)
        
    # 4. 데이터 추출 루프 가동
    checkpoint = load_checkpoint()
    completed_keys = checkpoint.get("completed", [])
    records = checkpoint.get("records", [])
    
    os.makedirs("data", exist_ok=True)
    os.makedirs("docs", exist_ok=True)
    
    # 전체 작업 목록 작성
    tasks = []
    for stem in STEMS:
        for season_name, season_info in SEASONS.items():
            key = f"{stem}_{season_name}"
            tasks.append((key, stem, season_name, season_info))
            
    if args.test:
        print("\n[!] Running in TEST mode. Will only execute 1 task.")
        test_task = None
        for task in tasks:
            if task[1] == "을목(乙木)" and task[2] == "봄":
                test_task = task
                break
        if not test_task:
            test_task = tasks[0]
        tasks = [test_task]
        
    success_count = 0
    fail_count = 0
    
    start_time = time.time()
    
    for key, stem, season_name, season_info in tasks:
        if key in completed_keys and not args.test:
            print(f"[-] Already completed: {stem} - {season_name}. Skipping.")
            continue
            
        try:
            # 매 Task 시작 전마다 라이브 세션 쿠키를 동적으로 갱신하여 인스턴스 획득
            # 이를 통해 구글 측의 1회성 토큰 만료 정책을 완벽하게 우회합니다.
            live_client = get_live_client()
            
            # 3단계 재귀 추출 실행
            extracted_list = extract_stem_season(live_client, notebook_id, stem, season_name, season_info)
            
            # 기존 레코드 제거 후 추가
            records = [r for r in records if not (r["일간"] == stem and r["계절"] == season_name)]
            records.extend(extracted_list)
            
            if key not in completed_keys:
                completed_keys.append(key)
                
            save_checkpoint(completed_keys, records)
            success_count += 1
            
            # API Rate Limit 보호를 위해 대기시간 부여
            print("  [*] Waiting 5 seconds before next task...")
            time.sleep(5)
            
        except Exception as e:
            print(f"  [!] Failed to extract data for {key}: {e}")
            fail_count += 1
            if args.test:
                print("[!] Test failed. Exiting.")
                sys.exit(1)
            print("  [*] Sleeping 15 seconds before continuing...")
            time.sleep(15)
            
    # 5. 최종 데이터 병합 및 정렬 (CSV / JSON 출력)
    if not args.test and success_count > 0:
        print("\n[*] Exporting final database...")
        month_order = {
            '인월(寅月)': 1, '묘월(卯月)': 2, '진월(辰月)': 3,
            '사월(巳月)': 4, '오월(午月)': 5, '미월(未月)': 6,
            '신월(申月)': 7, '유월(酉月)': 8, '술월(戌月)': 9,
            '해월(亥月)': 10, '자월(子月)': 11, '축월(丑月)': 12
        }
        stem_order = {stem: idx for idx, stem in enumerate(STEMS)}
        
        # 정렬 수행
        def get_sort_key(r):
            s_idx = stem_order.get(r.get("일간", ""), 99)
            m_name = r.get("월별", "")
            m_idx = 99
            for k, idx in month_order.items():
                if k[:2] in m_name:
                    m_idx = idx
                    break
            return (s_idx, m_idx)
            
        records.sort(key=get_sort_key)
        
        # 1) JSON 내보내기
        final_json_path = r"docs\gungtong_database.json"
        with open(final_json_path, "w", encoding="utf-8") as jf:
            json.dump(records, jf, indent=2, ensure_ascii=False)
        print(f"[+] Final JSON database written to: {final_json_path}")
        
        # 2) CSV 내보내기 (조건식 평탄화 처리)
        final_csv_path = r"docs\gungtong_database.csv"
        import csv
        headers = ["일간", "계절", "월별", "핵심용신", "보조용신", "취용요약", "조건", "결과"]
        try:
            with open(final_csv_path, "w", newline="", encoding="utf-8-sig") as cf:
                writer = csv.DictWriter(cf, fieldnames=headers)
                writer.writeheader()
                for row in records:
                    cond_list = row.get("조건식", [])
                    if not cond_list:
                        cond_list = [{"조건": "", "결과": ""}]
                        
                    for cond in cond_list:
                        flat_row = {
                            "일간": row.get("일간", ""),
                            "계절": row.get("계절", ""),
                            "월별": row.get("월별", ""),
                            "핵심용신": row.get("핵심용신", ""),
                            "보조용신": row.get("보조용신", ""),
                            "취용요약": row.get("취용요약", ""),
                            "조건": cond.get("조건", ""),
                            "결과": cond.get("결과", "")
                        }
                        writer.writerow(flat_row)
            print(f"[+] Final CSV database written to: {final_csv_path}")
        except Exception as csv_err:
            print(f"[!] Failed to write CSV database: {csv_err}")
            
    elapsed = time.time() - start_time
    print(f"\n=== Extraction Process Completed ===")
    print(f"- Success: {success_count}")
    print(f"- Failed: {fail_count}")
    print(f"- Total Records in DB: {len(records)}")
    print(f"- Time elapsed: {elapsed:.1f} seconds")

if __name__ == "__main__":
    main()
