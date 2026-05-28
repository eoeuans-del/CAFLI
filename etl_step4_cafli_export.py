import pandas as pd
import geopandas as gpd
import requests
import json
from shapely.geometry import Point
from rasterstats import zonal_stats

# 앞선 1, 2, 3단계 파이프라인을 모듈로 연결합니다.
from etl_step1_base import build_base_geodataframe
from etl_step2_transit import process_integrated_transit_data
from etl_step3_amenity import process_amenity_data

# API 키 설정
EX_API_KEY = "0962812032"

def fetch_tollgate_traffic_api():
    print("1. 한국도로공사(EX) API에 실시간 톨게이트 교통량을 요청합니다...")
    # 수도권 주요 영업소 하드코딩 매핑 테이블
    tollgate_coords = {
        '서울': {'lon': 127.1036, 'lat': 37.3653},
        '서서울': {'lon': 126.8529, 'lat': 37.3629},
        '동서울': {'lon': 127.1895, 'lat': 37.5256},
        '수원신갈': {'lon': 127.1047, 'lat': 37.2618}
    }
    
    traffic_data = []
    
    try:
        url = f"http://data.ex.co.kr/openapi/trtm/realUnitTrtm?key={EX_API_KEY}&type=json"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        for item in data.get('list', []):
            name = item.get('tgateName', '')
            if name in tollgate_coords:
                traffic_data.append({
                    'name': name,
                    'traffic_volume': int(item.get('trafficAmnt', 0)),
                    'lon': tollgate_coords[name]['lon'],
                    'lat': tollgate_coords[name]['lat']
                })
        print(" -> API 라이브 호출 성공 및 데이터 적재 완료.")
        
        if not traffic_data:
            raise ValueError("파싱된 톨게이트 데이터가 없어 스냅샷으로 전환합니다.")
                
    except Exception as e:
        print(f" ⚠️ API 호출 실패 또는 데이터 없음 ({e})")
        print(" ⚠️ [MVP 방어 코드 가동] 시연 안정성을 위해 내장된 수도권 평균 스냅샷 데이터로 전환합니다.")
        traffic_data = [
            {'name': '서울', 'traffic_volume': 150000, 'lon': 127.1036, 'lat': 37.3653},
            {'name': '서서울', 'traffic_volume': 130000, 'lon': 126.8529, 'lat': 37.3629},
            {'name': '동서울', 'traffic_volume': 110000, 'lon': 127.1895, 'lat': 37.5256},
            {'name': '수원신갈', 'traffic_volume': 140000, 'lon': 127.1047, 'lat': 37.2618}
        ]
        
    df_tg = pd.DataFrame(traffic_data)
    gdf_tg = gpd.GeoDataFrame(df_tg, geometry=gpd.points_from_xy(df_tg['lon'], df_tg['lat']), crs="EPSG:4326").to_crs(epsg=5179)
    return gdf_tg

def calculate_final_cafli(base_gdf: gpd.GeoDataFrame, tg_gdf: gpd.GeoDataFrame, vehicle_df: pd.DataFrame, dem_slope_df: pd.DataFrame):
    # KOSIS 시군구 차량 통계를 하위 행정동으로 상속
    base_gdf['per_capita_vehicle'] = base_gdf['행정구역'].apply(
        lambda x: vehicle_df[vehicle_df.iloc[:, 0].apply(lambda s: str(s) in x)].iloc[0, 1] 
        if any(vehicle_df.iloc[:, 0].apply(lambda s: str(s) in x)) else 0.35
    )
    
    # DEM 경사도 데이터를 도화지에 병합
    base_gdf = base_gdf.merge(dem_slope_df[['adm_cd2', 'avg_slope']], on='adm_cd2', how='left').fillna({'avg_slope': 0.0})

    print("2. [V 지표] 톨게이트 트래픽 기반 차량 의존도 페널티를 연산합니다...")
    base_gdf['centroid'] = base_gdf.geometry.centroid
    base_gdf['v_penalty'] = 0.0
    
    for idx, tg in tg_gdf.iterrows():
        distances = base_gdf['centroid'].distance(tg.geometry)
        penalty_score = tg['traffic_volume'] / (distances + 1)
        base_gdf['v_penalty'] += penalty_score

    print("3. [정석 연산] 왜곡 제거를 위한 밀도 변환 및 0~100점 정규화(Min-Max)를 실행합니다...")
    base_gdf['t_density'] = base_gdf['transit_stop_count'] / base_gdf['area_sqkm']
    base_gdf['s_density'] = base_gdf['amenity_count'] / base_gdf['area_sqkm']
    
    def min_max_scale(series, inverse=False):
        if series.max() == series.min():
            return pd.Series(50.0, index=series.index)
        scaled = (series - series.min()) / (series.max() - series.min()) * 100
        return 100 - scaled if inverse else scaled

    base_gdf['T_score'] = min_max_scale(base_gdf['t_density'])
    base_gdf['S_score'] = min_max_scale(base_gdf['s_density'])
    
    base_gdf['per_capita_vehicle'] = pd.to_numeric(base_gdf['per_capita_vehicle'].astype(str).str.replace(',', ''), errors='coerce').fillna(0.35)
    
    base_gdf['v_combined_penalty'] = base_gdf['v_penalty'] * base_gdf['per_capita_vehicle']
    base_gdf['V_score'] = min_max_scale(base_gdf['v_combined_penalty'], inverse=True)
    base_gdf['W_score'] = min_max_scale(base_gdf['avg_slope'], inverse=True)

    print("4. 기획서 원본 공식(V:35, T:30, W:25, S:10)을 적용하여 최종 CAFLI 지수를 산출합니다...")
    base_gdf['CAFLI_Index'] = (
        base_gdf['V_score'] * 0.35 + 
        base_gdf['T_score'] * 0.30 + 
        base_gdf['W_score'] * 0.25 + 
        base_gdf['S_score'] * 0.10
    ).round(2)

    print("5. 프론트엔드 시각화를 위한 GeoJSON 파일 추출을 시작합니다...")
    export_columns = ['adm_cd2', '행정구역', 'T_score', 'S_score', 'V_score', 'W_score', 'CAFLI_Index', 'geometry']
    final_export = base_gdf[export_columns].copy()
    
    final_export = final_export.to_crs(epsg=4326)
    
    export_path = './data/cafli_model_result.geojson'
    final_export.to_file(export_path, driver='GeoJSON', encoding='utf-8')
    print(f"🎉 성공! 시연용 데이터 마트가 저장되었습니다: {export_path}")
    
    return final_export

if __name__ == "__main__":
    print("\n[파이프라인 가동] 1~3단계 도화지를 빌드합니다 (시간이 소요될 수 있습니다)...")
    
    # C++ 코어 엔진(GDAL)이 정확히 인식할 수 있도록 실제 파일명과 동일하게 전체 대문자로 일치
    base_gdf = build_base_geodataframe('./data/BND_ADM_DONG_PG.shp', './data/population_stat.csv')
    
    # ★ [수정 포인트]: 필터링 전후의 데이터 건수를 측정하고, 데이터가 0건일 경우 엔진을 강제 정지시키는 탐지기를 부착합니다 (실제 코드 적용 시 해당 줄은 삭제하라) ★
    print(f" 🔍 [탐지기] 필터링 전 총 데이터 건수: {len(base_gdf)}건")
    print(f" 🔍 [탐지기] '행정구역' 컬럼 샘플 5개:\n{base_gdf['행정구역'].head(5)}")
    
    # 거리 역설 방지를 위한 수도권 필터링에 인천 명시적 추가
    base_gdf = base_gdf[base_gdf['행정구역'].str.contains('서울|경기|인천', na=False)].copy()
    
    print(f" 🔍 [탐지기] 필터링 후 수도권 데이터 건수: {len(base_gdf)}건")
    if len(base_gdf) == 0:
        import sys
        print(" 🚨 [치명적 오류] 필터링 후 데이터가 0건입니다. 조인 실패로 데이터가 증발했습니다. 엔진을 강제 종료합니다.")
        sys.exit(1)
        
    transit_gdf = process_integrated_transit_data(base_gdf, './data/transit_stops.csv', './data/railway_stations.xlsx')
    
    # S지표 확장을 위해 인천 상권 데이터 파라미터 추가
    fully_loaded_gdf = process_amenity_data(transit_gdf, './data/commercial_seoul.csv', './data/commercial_gyeonggi.csv', './data/commercial_incheon.csv')
    
    print("\n[본 작업] 4단계 API 연동 및 지수 산출을 시작합니다...")
    tg_gdf = fetch_tollgate_traffic_api()
    
    print(" -> 통계청 차량 등록 데이터와 DEM 수치표고모델(경사도) 데이터를 융합합니다...")
    vehicle_df = pd.read_csv('./data/vehicle_stats.csv', encoding='cp949')
    
    print(" -> (진행 중) 래스터 이미지 공간 분석을 통해 행정동별 경사도 표고 편차를 연산합니다...")
    fully_loaded_gdf = gpd.GeoDataFrame(fully_loaded_gdf, geometry='geometry')
    
    # 공간 속성(CRS) 강제 주입 및 불량 폴리곤 도려내기
    fully_loaded_gdf.set_crs(epsg=5179, allow_override=True, inplace=True)
    fully_loaded_gdf = fully_loaded_gdf.dropna(subset=['geometry'])
    
    # ★ [핵심 수정 포인트]: 오타 없이 순수 기하학 객체(geometry)만 정확하게 주입합니다.
# ★ [수정 포인트]: GeoSeries의 복합 객체 구조를 해체하여 래스터 엔진이 가장 좋아하는 '순수 기하학 리스트(List)' 형태로 강제 변환 후 주입합니다 (실제 코드 적용 시 해당 줄은 삭제하라) ★
    dem_stats = zonal_stats(fully_loaded_gdf.geometry.tolist(), './data/dem_90m.img', stats="std", geojson_out=False)
    # 결과를 담을 데이터프레임(dem_slope_df)을 명시적으로 초기화한 뒤 데이터 주입
    dem_slope_df = pd.DataFrame({'adm_cd2': fully_loaded_gdf['adm_cd2']})
    dem_slope_df['avg_slope'] = [s['std'] if s['std'] is not None else 0 for s in dem_stats]
    
    result = calculate_final_cafli(fully_loaded_gdf, tg_gdf, vehicle_df, dem_slope_df)
    
    print("\n📊 [최종 산출 결과 미리보기 (Top 5)]")
    print(result[['행정구역', 'CAFLI_Index', 'V_score', 'T_score', 'W_score', 'S_score']].sort_values(by='CAFLI_Index', ascending=False).head(5))