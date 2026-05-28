import pandas as pd
import geopandas as gpd

def build_base_geodataframe(geojson_path, pop_csv_path):
    print("1. 행정동 공간 경계(GeoJSON/SHP) 데이터를 메모리에 로드합니다...")
    gdf_boundaries = gpd.read_file(geojson_path)
    
    # [방어벽 1]: VWORLD 등 다양한 SHP 스키마를 기존 엔진 규격(adm_cd2)으로 강제 매핑
    col_map = {c.upper(): c for c in gdf_boundaries.columns}
    
    if 'ADM_DR_CD' in col_map:
        gdf_boundaries.rename(columns={col_map['ADM_DR_CD']: 'adm_cd2'}, inplace=True)
    elif 'ADM_CD' in col_map:
        gdf_boundaries.rename(columns={col_map['ADM_CD']: 'adm_cd2'}, inplace=True)
    elif 'EMD_CD' in col_map:
        gdf_boundaries.rename(columns={col_map['EMD_CD']: 'adm_cd2'}, inplace=True)

    gdf_boundaries['adm_cd2'] = gdf_boundaries['adm_cd2'].astype(str)

    print("2. 주민등록 인구 및 가구 통계(CSV)를 로드합니다...")
    df_pop = pd.read_csv(pop_csv_path, encoding='utf-8-sig')
    
    # [방어벽 2]: 보이지 않는 공백과 오타를 무력화하는 강제 컬럼명 고정
    df_pop.rename(columns={df_pop.columns[0]: '행정구역'}, inplace=True)

    print("2-5. 인구 통계 데이터에서 괄호 안의 행정동 코드(10자리)만 추출합니다...")
    df_pop['extracted_cd'] = df_pop['행정구역'].str.extract(r'\((\d+)\)').astype(str)

    print("3. 추출된 코드를 기준으로 공간 데이터와 통계 데이터를 병합(Left Join)합니다...")
    # [방어벽 3]: VWORLD의 행정동 코드가 8자리일 경우를 대비한 동적 조인 길이 조정
    sample_shp_cd_len = len(gdf_boundaries['adm_cd2'].iloc[0].strip())
    if sample_shp_cd_len == 8:
        df_pop['join_cd'] = df_pop['extracted_cd'].str[:8]
    else:
        df_pop['join_cd'] = df_pop['extracted_cd']

    base_gdf = gdf_boundaries.merge(df_pop, left_on='adm_cd2', right_on='join_cd', how='left')

    # [방어벽 4]: VWORLD 원본에 면적(area_sqkm)이 없을 경우, 3/4단계 붕괴를 막기 위한 공간 연산 자동 보정
    if 'area_sqkm' not in base_gdf.columns:
        temp_gdf = base_gdf.copy()
        # 정확한 면적 산출을 위해 미터 단위 평면 좌표계(EPSG:5179)로 일시 투영
        if not temp_gdf.crs:
            temp_gdf.set_crs(epsg=5179, allow_override=True, inplace=True)
        elif temp_gdf.crs.to_epsg() != 5179:
            temp_gdf = temp_gdf.to_crs(epsg=5179)
        base_gdf['area_sqkm'] = temp_gdf.geometry.area / 1e6

    print(f"-> 총 {len(base_gdf)}개 타겟 행정동의 베이스 데이터 구축이 성공적으로 완료되었습니다.")
    
    return base_gdf