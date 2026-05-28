import pandas as pd
import os

def split_commercial_data(input_file):
    print(f"🚀 대용량 상권 데이터 분할을 시작합니다: {input_file}")
    
    # 출력 타겟 파일 경로 설정
    output_paths = {
        '서울': './data/commercial_seoul.csv',
        '경기': './data/commercial_gyeonggi.csv',
        '인천': './data/commercial_incheon.csv'
    }
    
    # 기존 파일 초기화 (이전 실행 결과가 남아있을 경우 중복 Append 방지)
    for path in output_paths.values():
        if os.path.exists(path):
            os.remove(path)
            
    # # ★ [수정 포인트]: 10만 줄씩 조각(Chunk) 내어 읽어 들이는 기법으로 메모리 폭주를 원천 차단합니다 (실제 코드 적용 시 해당 줄은 삭제하라) ★
    chunk_size = 100000
    first_chunk = { '서울': True, '경기': True, '인천': True }
    
    try:
        # low_memory=False 옵션으로 대용량 파일 읽기 안정성 확보
        for i, chunk in enumerate(pd.read_csv(input_file, chunksize=chunk_size, encoding='utf-8', low_memory=False)):
            print(f"  -> {i+1}번째 청크(Chunk) 스캔 및 필터링 중...")
            
            # '시도명' 컬럼을 기준으로 각 지역 필터링 
            # (만약 공공데이터의 지역 컬럼명이 다를 경우 '시도명' 부분을 원본에 맞게 수정해야 합니다)
            seoul_df = chunk[chunk['시도명'].str.contains('서울', na=False)]
            gyeonggi_df = chunk[chunk['시도명'].str.contains('경기', na=False)]
            incheon_df = chunk[chunk['시도명'].str.contains('인천', na=False)]
            
            # # ★ [수정 포인트]: mode='a' (Append)를 사용하여 이전 파일 끝에 데이터를 계속 이어 붙입니다 (실제 코드 적용 시 해당 줄은 삭제하라) ★
            if not seoul_df.empty:
                seoul_df.to_csv(output_paths['서울'], mode='a', index=False, encoding='utf-8-sig', header=first_chunk['서울'])
                first_chunk['서울'] = False
                
            if not gyeonggi_df.empty:
                gyeonggi_df.to_csv(output_paths['경기'], mode='a', index=False, encoding='utf-8-sig', header=first_chunk['경기'])
                first_chunk['경기'] = False
                
            if not incheon_df.empty:
                incheon_df.to_csv(output_paths['인천'], mode='a', index=False, encoding='utf-8-sig', header=first_chunk['인천'])
                first_chunk['인천'] = False
                
        print("🎉 성공! 수도권 3개 지역 상권 데이터 추출이 무결점 상태로 완료되었습니다.")
    except Exception as e:
        print(f"❌ 데이터 분할 중 에러 발생: {e}")

if __name__ == "__main__":
    # 데이터 창고에 있는 전국 상권 데이터 원본 파일의 정확한 이름을 아래에 기입해 주십시오.
    split_commercial_data('./data/전국_상권데이터_원본파일명.csv')
    