import os
import sys
import json
import subprocess
import re
import time
import argparse

# 윈도우 환경에서 출력 인코딩 오류 예방
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

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

def run_cmd(command, env=None):
    """실행 중인 셸 명령어 호출 및 UTF-8 디코딩 처리"""
    if env is None:
        env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    # 윈도우 파워쉘/CMD 인코딩 세팅 호환성을 위해 shell=True 사용
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env
    )
    stdout, stderr = process.communicate()
    
    # 리턴코드 확인
    if process.returncode != 0:
        err_msg = stderr.decode('utf-8', errors='ignore')
        out_msg = stdout.decode('utf-8', errors='ignore')
        raise RuntimeError(f"Command failed with code {process.returncode}.\nSTDOUT: {out_msg}\nSTDERR: {err_msg}")
        
    return stdout.decode('utf-8', errors='ignore')

def get_notebook_id():
    """기존 '궁통보감 사주 AI' 노트북 ID 조회, 없을 시 신규 생성"""
    print(f"[*] Checking for existing notebook: '{NOTEBOOK_TITLE}'...")
    output = run_cmd("nlm list notebooks")
    
    try:
        notebooks = json.loads(output)
    except json.JSONDecodeError:
        # 혹시 JSON 형태가 아니면 파싱 시도
        notebooks = []
        # nlm list notebooks 결과에서 ID 추출 시도
        matches = re.findall(r'"id":\s*"([^"]+)",\s*"title":\s*"([^"]+)"', output)
        for nid, title in matches:
            notebooks.append({"id": nid, "title": title})
            
    for nb in notebooks:
        # 인코딩 깨짐을 감안해 완전히 일치하거나 일부 매칭되는지 확인
        if NOTEBOOK_TITLE in nb.get("title", "") or nb.get("title", "") == NOTEBOOK_TITLE:
            print(f"[+] Found existing notebook. ID: {nb['id']}")
            return nb["id"]
            
    # 없는 경우 새로 생성
    print(f"[*] Creating a new notebook named '{NOTEBOOK_TITLE}'...")
    create_output = run_cmd(f'nlm create notebook "{NOTEBOOK_TITLE}"')
    
    # 생성된 노트북 ID 파싱
    try:
        new_nb = json.loads(create_output)
        nid = new_nb.get("id")
    except json.JSONDecodeError:
        # 텍스트 형태 출력에서 ID 파싱 (예: "ID: 5716f648-6ecf-4831-bd6d-e2fbb88ce756")
        match = re.search(r'(?:id|ID):\s*([a-f0-9\-]{36})', create_output, re.IGNORECASE)
        if match:
            nid = match.group(1)
        else:
            raise RuntimeError(f"Failed to parse created notebook ID from:\n{create_output}")
            
    print(f"[+] Notebook created successfully. ID: {nid}")
    return nid

def upload_pdf_source(notebook_id):
    """노트북에 궁통보감 PDF 소스가 있는지 검사 및 업로드"""
    print("[*] Checking notebook sources...")
    sources_output = run_cmd(f"nlm source list {notebook_id}")
    
    try:
        sources = json.loads(sources_output)
    except json.JSONDecodeError:
        sources = []
        matches = re.findall(r'"id":\s*"([^"]+)",\s*"title":\s*"([^"]+)"', sources_output)
        for sid, title in matches:
            sources.append({"id": sid, "title": title})
            
    pdf_filename = os.path.basename(PDF_PATH)
    for src in sources:
        if pdf_filename in src.get("title", "") or "궁통보감" in src.get("title", ""):
            print(f"[+] PDF Source already exists in notebook. Source ID: {src['id']}")
            return src["id"]
            
    print(f"[*] PDF Source not found. Uploading '{PDF_PATH}' to notebook (This may take a few minutes)...")
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"Source PDF file not found at: {PDF_PATH}")
        
    upload_output = run_cmd(f'nlm source add {notebook_id} --file "{PDF_PATH}" --wait')
    print("[+] PDF uploaded and processed successfully!")
    
    # 새로 등록된 소스 ID 다시 확인
    sources_output = run_cmd(f"nlm source list {notebook_id}")
    try:
        sources = json.loads(sources_output)
        for src in sources:
            if pdf_filename in src.get("title", ""):
                return src["id"]
    except Exception:
        pass
    return None

def clean_json_text(text):
    """답변 텍스트에서 JSON 배열 부분만 추출하여 깔끔하게 정제"""
    # ```json ... ``` 블록 추출
    match = re.search(r'```(?:json)?\s*(\[\s*\{.*\}\s*\])\s*```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
        
    # 대괄호로 묶인 배열 추출 시도
    match_arr = re.search(r'(\[\s*\{.*\}\s*\])', text, re.DOTALL)
    if match_arr:
        return match_arr.group(1).strip()
        
    return text.strip()

def query_notebook_with_retry(notebook_id, question, conversation_id=None, retries=2):
    """NotebookLM 쿼리 및 재시도 처리"""
    cmd = f'nlm query notebook {notebook_id} "{question}"'
    if conversation_id:
        cmd += f' --conversation-id {conversation_id}'
        
    for attempt in range(retries + 1):
        try:
            output = run_cmd(cmd)
            response_data = json.loads(output)
            value = response_data.get("value", {})
            answer = value.get("answer", "")
            conv_id = value.get("conversation_id", "")
            return answer, conv_id
        except Exception as e:
            if attempt == retries:
                raise e
            print(f"    [!] Query failed (Attempt {attempt+1}/{retries+1}): {e}. Retrying in 5 seconds...")
            time.sleep(5)

def extract_stem_season(notebook_id, stem, season_name, season_info):
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
        f"    \"천간\": \"{stem}\",\n"
        f"    \"계절\": \"{season_name}\",\n"
        "    \"월\": \"인월(寅月) 또는 묘월(卯月) 또는 진월(辰月) 등 해당하는 월명\",\n"
        "    \"핵심용신\": \"문헌에서 제시한 핵심 용신 오행/글자\",\n"
        "    \"보조용신\": \"보조 용신 또는 희신 오행/글자\",\n"
        "    \"희신\": \"생조하거나 도우는 희신 목록\",\n"
        "    \"기신\": \"꺼리거나 제극하는 기신 목록\",\n"
        "    \"명리학적조건식\": \"해당 월의 명리학적 조건 규칙 (예: 신강/신약, 조후 습난 상태에 따른 용신 채택 기준)\",\n"
        "    \"조후요약\": \"해당 월의 조후 및 억부 핵심 요약\"\n"
        "  }\n"
        "]"
    )
    
    answer_draft, conv_id = query_notebook_with_retry(notebook_id, prompt_extract)
    
    # -------------------------------------------------------------
    # [2단계: 1차 팩트체크 - 원전 교차 검증]
    # -------------------------------------------------------------
    print("  [Step 2] Performing 1st Fact-Check: Checking for cross-contamination of other stems...")
    prompt_fc1 = (
        f"방금 답변한 {stem}의 {season_name} JSON 데이터에 다른 천간(예: {stem} 외의 다른 오행 천간의 명조나 규칙)의 내용이 부주의하게 섞여 들어갔는지 "
        "궁통보감 원문 내용과 다시 한 번 정밀하게 교차 검증해줘. "
        "오류나 혼입이 발견된다면 수정 보정하고, 아무 설명 없이 보정된 최종 JSON 배열(```json ... ```)만 다시 출력해줘."
    )
    
    answer_fc1, conv_id = query_notebook_with_retry(notebook_id, prompt_fc1, conversation_id=conv_id)
    
    # -------------------------------------------------------------
    # [3단계: 2차 팩트체크 - 명리학 논리 검증]
    # -------------------------------------------------------------
    print("  [Step 3] Performing 2nd Fact-Check: Validating astrological logic consistency...")
    prompt_fc2 = (
        f"수정된 {stem}의 {season_name} JSON 데이터 내에서 용신, 보조용신, 희신, 기신 간의 생극제화와 조후 관계상 명리학적 모순(예: 기신과 용신이 섞였거나, 생조 관계가 붕괴되는 오류)이 없는지 논리적으로 최종 검증해줘. "
        "모순이 있다면 명리학 이치에 맞게 보정하고, 마찬가지로 설명 없이 오직 최종 완성된 JSON 배열(```json ... ```)만 최종 출력해줘."
    )
    
    answer_fc2, conv_id = query_notebook_with_retry(notebook_id, prompt_fc2, conversation_id=conv_id)
    
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
            # 유연한 필드 매핑 및 통일화
            monthly_record = {}
            monthly_record["일간"] = item.get("일간") or item.get("천간") or stem
            monthly_record["계절"] = item.get("계절") or season_name
            monthly_record["월별"] = item.get("월별") or item.get("월") or ""
            
            # 조후 및 용신
            johoo_data = item.get("조후_및_용신") or {}
            monthly_record["핵심용신"] = johoo_data.get("핵심용신") or item.get("핵심용신") or ""
            monthly_record["보조용신"] = johoo_data.get("보조용신") or item.get("보조용신") or ""
            monthly_record["취용요약"] = johoo_data.get("취용요약") or item.get("조후요약") or item.get("취용요약") or ""
            
            # 조건식 리스트 확보
            cond_list = item.get("조건식") or []
            if not isinstance(cond_list, list):
                cond_list = []
            
            # 명리학적조건식이 텍스트 형태로 온 경우 구조화 시도
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
    
    # 1. 노트북 획득 및 연결 검증
    try:
        notebook_id = get_notebook_id()
    except Exception as e:
        print(f"[!] Initialization error: {e}")
        print("[!] Please check if 'nlm login' is authenticated properly.")
        sys.exit(1)
        
    # 2. PDF 소스 업로드
    try:
        upload_pdf_source(notebook_id)
    except Exception as e:
        print(f"[!] Source PDF upload failed: {e}")
        sys.exit(1)
        
    # 3. 데이터 추출 루프 가동
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
        # 미완료인 것 중 첫 번째나 혹은 을목-봄 조합을 우선 테스팅
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
            # 3단계 재귀 추출 실행
            extracted_list = extract_stem_season(notebook_id, stem, season_name, season_info)
            
            # 기존 레코드에서 동일 키의 구 데이터 삭제 후 추가 (중복 방지)
            records = [r for r in records if not (r["천간"] == stem and r["계절"] == season_name)]
            records.extend(extracted_list)
            
            if key not in completed_keys:
                completed_keys.append(key)
                
            save_checkpoint(completed_keys, records)
            success_count += 1
            
            # API Rate Limit 보호를 위해 대기시간 부여
            print("  [*] Waiting 5 seconds before next task to prevent rate limiting...")
            time.sleep(5)
            
        except Exception as e:
            print(f"  [!] Failed to extract data for {key}: {e}")
            fail_count += 1
            if args.test:
                print("[!] Test failed. Exiting.")
                sys.exit(1)
            print("  [*] Sleeping 15 seconds to let API cooldown before continuing...")
            time.sleep(15)
            
    # 4. 최종 데이터 병합 및 정렬 (CSV / JSON 출력)
    if not args.test and success_count > 0:
        print("\n[*] Exporting final database...")
        # 12개월(인~축) 정렬 순서 정의
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
            # 월령 이름에 한자가 붙어있는 등의 변칙 매핑
            m_idx = 99
            for k, idx in month_order.items():
                if k[:2] in m_name:  # 예: '인월'이 포함되어 있으면
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
