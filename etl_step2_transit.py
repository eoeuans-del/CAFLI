import pandas as pd
import geopandas as gpd
# 1단계 파이썬 파일에서 베이스캠프 생성 함수를 모듈로 불러옵니다.
from etl_step1_base import build_base_geodataframe

def process_integrated_transit_data(base_gdf: gpd.GeoDataFrame, bus_csv_path: str, rail_excel_path: str):
    print("1. 버스 및 철도 원천 데이터를 각각 로드하고 스키마를 표준화합니다...")
    
    # [1] 버스 데이터 로드 및 표준화
    df_bus = pd.read_csv(bus_csv_path, encoding='cp949')
    # 파이썬 내부에서 다루기 쉽도록 한글 컬럼명을 영문(lon, lat)으로 강제 개명합니다.
    df_bus = df_bus.rename(columns={'경도': 'lon', '위도': 'lat'})
    df_bus['transit_type'] = 'bus' # 출처 꼬리표 부착

    # [2] 철도 데이터 로드 및 표준화 (.xlsx)
    df_rail = pd.read_excel(rail_excel_path)
    df_rail = df_rail.rename(columns={'역경도': 'lon', '역위도': 'lat'})
    df_rail['transit_type'] = 'railway'
    
    # 배차 충족률 추정을 위한 가중치 부여: 지하철은 일반 버스보다 배차 빈도 및 수송량이 압도적으로 높음
    # 환승역일 경우 가중치 추가 (환승역구분 컬럼 활용)
    df_rail['weight'] = df_rail['환승역구분'].apply(lambda x: 20 if str(x) == '환승역' else 10)
    df_bus['weight'] = 1

    print("2. 두 데이터를 하나의 대중교통 인프라로 수직 병합(Concat)합니다...")
    # 좌표, 타입, 가중치 컬럼을 합칩니다.
    df_combined = pd.concat([
        df_bus[['lon', 'lat', 'transit_type', 'weight']], 
        df_rail[['lon', 'lat', 'transit_type', 'weight']]
    ], ignore_index=True)

    # 간혹 좌표가 누락된 불량 데이터가 있을 수 있으므로 방어 코드를 추가합니다.
    df_combined = df_combined.dropna(subset=['lon', 'lat'])

    print("3. 병합된 X, Y 좌표를 공간 점(Point Geometry)으로 변환합니다 (EPSG:4326 -> 5179)...")
    gdf_transit = gpd.GeoDataFrame(
        df_combined, 
        geometry=gpd.points_from_xy(df_combined['lon'], df_combined['lat']),
        crs="EPSG:4326"
    )
    # 베이스캠프와 완벽히 포개지도록 UTM-K(5179) 좌표계로 강제 통일합니다.
    gdf_transit = gdf_transit.to_crs(epsg=5179)

    print("4. 행정동 그물망으로 정류장 데이터를 건져 올리는 공간 조인(Spatial Join)을 실행합니다...")
    joined = gpd.sjoin(gdf_transit, base_gdf, how='inner', predicate='within')

    print("5. 행정동(adm_cd2) 기준으로 대중교통 인프라(T 지표)를 집계합니다...")
    # 단순 개수(count)와 가중치 합산(dispatch_score)을 모두 구합니다.
    t_counts = joined.groupby('adm_cd2').size().reset_index(name='transit_stop_count')
    t_weights = joined.groupby('adm_cd2')['weight'].sum().reset_index(name='transit_dispatch_score')

    print("6. 집계된 T 지표를 베이스캠프에 최종 결합합니다...")
    final_gdf = base_gdf.merge(t_counts, on='adm_cd2', how='left')
    final_gdf = final_gdf.merge(t_weights, on='adm_cd2', how='left')
    
    # 결측치 처리
    final_gdf['transit_stop_count'] = final_gdf['transit_stop_count'].fillna(0)
    final_gdf['transit_dispatch_score'] = final_gdf['transit_dispatch_score'].fillna(0)

    print(f"-> 통합 대중교통(T 지표) 공간 연산 완료. 총 {len(df_combined)}개의 인프라(가중치 합산 반영)가 지도상에 매핑되었습니다.\n")
    return final_gdf

if __name__ == "__main__":
    print("\n[사전 작업] 1단계 베이스캠프를 불러옵니다...")
    # etl_step1_base.py가 정상 작동해야만 이 도화지가 생성됩니다.
    base_gdf = build_base_geodataframe('./data/regions_boundary.geojson', './data/population_stat.csv')

    print("\n[본 작업] 2단계 버스+철도 통합 공간 조인을 시작합니다...")
    # 데이터 폴더 경로와 파일명을 정확히 맞추어 실행합니다.
    final_result = process_integrated_transit_data(
        base_gdf, 
        './data/transit_stops.csv', 
        './data/railway_stations.xlsx'
    )

    # 상위 10개 행정동의 대중교통 인프라 개수(transit_stop_count)를 확인합니다.
    print(final_result[['adm_cd2', '행정구역', 'area_sqkm', 'transit_stop_count']].head(10))