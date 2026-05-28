import pandas as pd
import geopandas as gpd

def process_amenity_data(base_gdf, seoul_csv, gyeonggi_csv, incheon_csv=None):
    print("1. 수도권(서울, 경기, 인천) 상권 데이터(CSV)를 각각 로드합니다...")
    
    # ★ [수정 포인트]: low_memory=False 옵션을 추가하여 데이터 타입 혼재 경고(DtypeWarning)를 원천 차단합니다.
    df_seoul = pd.read_csv(seoul_csv, encoding='utf-8', low_memory=False)
    df_gyeonggi = pd.read_csv(gyeonggi_csv, encoding='utf-8', low_memory=False)
    
    dfs = [df_seoul, df_gyeonggi]
    
    # ★ [수정 포인트]: 4단계 엔진에서 밀어주는 인천 상권 데이터까지 안전하게 배열에 담습니다.
    if incheon_csv:
        df_incheon = pd.read_csv(incheon_csv, encoding='utf-8', low_memory=False)
        dfs.append(df_incheon)

    print("2. 수도권 데이터를 하나로 병합(Concat)합니다...")
    df_amenity = pd.concat(dfs, ignore_index=True)

    print("3. 핵심 편의시설(편의점, 카페)만 정밀 타격하여 필터링합니다...")
    target_keywords = ['편의점', '카페', '커피숍', '커피전문점']
    
    # 공공데이터 표준 스키마 방어 로직 (컬럼명이 다를 경우를 대비)
    if '상권업종소분류명' in df_amenity.columns:
        filtered_df = df_amenity[df_amenity['상권업종소분류명'].str.contains('|'.join(target_keywords), na=False)].copy()
    elif '표준산업분류명' in df_amenity.columns:
        filtered_df = df_amenity[df_amenity['표준산업분류명'].str.contains('|'.join(target_keywords), na=False)].copy()
    else:
        # 최후의 보루: 전체 텍스트에서 강제 검색
        mask = df_amenity.astype(str).apply(lambda x: x.str.contains('|'.join(target_keywords)).any(), axis=1)
        filtered_df = df_amenity[mask].copy()

    print(f" -> 필터링 완료: 총 {len(df_amenity)}개 상가 중 {len(filtered_df)}개의 핵심 편의시설만 추출되었습니다.")

    print("4. X, Y 좌표를 공간 점(Point Geometry)으로 변환합니다 (EPSG:4326 -> 5179)...")
    lon_col = '경도' if '경도' in filtered_df.columns else 'lon'
    lat_col = '위도' if '위도' in filtered_df.columns else 'lat'
    
    amenity_gdf = gpd.GeoDataFrame(
        filtered_df, 
        geometry=gpd.points_from_xy(filtered_df[lon_col], filtered_df[lat_col]),
        crs="EPSG:4326"
    )
    amenity_gdf = amenity_gdf.to_crs(epsg=5179)

    print("5. 행정동 그물망으로 편의시설을 건져 올리는 공간 조인(Spatial Join)을 실행합니다...")
    # 베이스캠프의 CRS를 안전하게 통일시킵니다 (EPSG:5186 경고 방어)
    if base_gdf.crs and base_gdf.crs.to_epsg() != 5179:
        join_base_gdf = base_gdf.to_crs(epsg=5179)
    else:
        join_base_gdf = base_gdf

    joined = gpd.sjoin(amenity_gdf, join_base_gdf[['adm_cd2', 'geometry']], how='inner', predicate='within')

    print("6. 행정동(adm_cd2) 기준으로 C/S 지표(생활 편의성)를 집계합니다...")
    amenity_counts = joined.groupby('adm_cd2').size().reset_index(name='amenity_count')

    print("7. 집계된 C/S 지표를 기존 베이스캠프에 최종 결합합니다...")
    final_gdf = base_gdf.merge(amenity_counts, on='adm_cd2', how='left')
    final_gdf['amenity_count'] = final_gdf['amenity_count'].fillna(0)

    print("-> 3단계 상업/편의시설 공간 연산 완료!")
    return final_gdf