import os
import pandas as pd

# 데이터 폴더 경로
data_dir = './data'

print("🔍 [자동 분류] data 폴더 내의 상가 데이터 내용물을 스캔하여 서울/경기를 찾습니다...")

for filename in os.listdir(data_dir):
    # 상가 데이터 원본은 파일명이 '상가', '상권' 등으로 시작합니다.
    if filename.endswith('.csv') and ('상가' in filename or '상권' in filename or '소상공인' in filename):
        filepath = os.path.join(data_dir, filename)
        
        try:
            # 메모리 과부하를 막기 위해 딱 1줄만 읽어서 지역 확인
            df = pd.read_csv(filepath, encoding='utf-8', nrows=1)
            
            if '시도명' in df.columns:
                region = df['시도명'].iloc[0]
                
                if region == '서울특별시':
                    new_name = 'commercial_seoul.csv'
                    os.rename(filepath, os.path.join(data_dir, new_name))
                    print(f"✅ [변경 완료] {filename} -> {new_name} (서울)")
                
                elif region == '경기도':
                    new_name = 'commercial_gyeonggi.csv'
                    os.rename(filepath, os.path.join(data_dir, new_name))
                    print(f"✅ [변경 완료] {filename} -> {new_name} (경기)")
                    
        except Exception:
            pass # 인코딩 에러나 관련 없는 파일은 무시하고 넘어갑니다.

print("🎉 타겟 파일 준비가 완료되었습니다.")
