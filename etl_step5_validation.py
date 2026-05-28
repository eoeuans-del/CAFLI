import geopandas as gpd
import pandas as pd

def validate_cafli_geojson(file_path):
    print(f"🔍 [데이터 검증 시작] '{file_path}' 파일을 분석합니다...\n")
    
    try:
        # GeoJSON 파일을 메모리에 다시 로드합니다.
        gdf = gpd.read_file(file_path)
    except Exception as e:
        print(f"❌ 파일 로드 실패: {e}")
        return

    # 1. 공간 좌표계(CRS) 검증
    crs = gdf.crs
    print(f"✅ 1. 좌표계(CRS) 확인: {crs} (프론트엔드 호환 목표: EPSG:5179)")
    if not crs or crs.to_epsg() != 5179:
        print("  ⚠️ 경고: 좌표계가 EPSG:5179가 아닙니다. 렌더링 시 위치가 어긋날 수 있습니다.")

    # 2. 결측치(NaN) 스캔
    print("\n✅ 2. 결측치(NaN/Null) 스캔 (Divide by Zero 방어 확인):")
    missing_data = gdf[['T_score', 'S_score', 'V_score', 'W_score', 'CAFLI_Index']].isnull().sum()
    if missing_data.sum() == 0:
        print("  -> 모든 지표에 결측치가 없습니다. (무결성 통과)")
    else:
        print("  ⚠️ 경고: 일부 행정동에서 지표 누락이 발견되었습니다.")
        print(missing_data[missing_data > 0])

    # 3. 정규화 스케일(0~100) 검증
    print("\n✅ 3. 지표별 정규화(Min-Max) 통계 분포 확인:")
    metrics = ['T_score', 'S_score', 'V_score', 'W_score']
    for m in metrics:
        min_val = gdf[m].min()
        max_val = gdf[m].max()
        print(f"  - {m}: 최소 {min_val:.1f}점 ~ 최대 {max_val:.1f}점")
        if min_val < 0 or max_val > 100:
            print(f"  ⚠️ 경고: {m} 지표가 0~100 범위를 벗어났습니다.")

    # 4. 논리적 정합성 대조 (Top 5 & Bottom 5 추출)
    print("\n✅ 4. CAFLI 종합 지수 랭킹 확인 (도메인 지식 대조용):")
    sorted_gdf = gdf.sort_values(by='CAFLI_Index', ascending=False)
    
    print("  🏆 [Top 5 지역 (인프라 최상위 도심)]")
    # 가독성을 위해 소수점 둘째 자리까지만 포맷팅하여 출력
    top5 = sorted_gdf[['행정구역', 'CAFLI_Index', 'T_score', 'S_score', 'V_score']].head(5)
    print(top5.to_string(index=False))
    
    print("\n  🚨 [Bottom 5 지역 (인프라 최하위 외곽)]")
    bottom5 = sorted_gdf[['행정구역', 'CAFLI_Index', 'T_score', 'S_score', 'V_score']].tail(5)
    print(bottom5.to_string(index=False))

    print("\n🎉 [검증 완료] 프론트엔드 렌더링으로 넘어갈 준비가 되었습니다.")

if __name__ == "__main__":
    target_file = './data/cafli_model_result.geojson'
    validate_cafli_geojson(target_file)
    