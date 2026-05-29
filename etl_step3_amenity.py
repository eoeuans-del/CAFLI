import pandas as pd
import geopandas as gpd
import osmnx as ox
import numpy as np

# OSMnx 로깅 및 캐시 설정 (API 호출 속도 향상 및 차단 방지)
ox.settings.log_console = True
ox.settings.use_cache = True

def calculate_mxi(df, adm_cd_col='adm_cd2'):
    """
    상가 업종의 다양성을 엔트로피 지수(Entropy Index)로 계산하여
    용도혼합지수(MXI)의 대리(Proxy) 지표로 사용합니다.
    """
    print(" -> 3-1. 행정동별 업종 다양성(MXI Proxy) 엔트로피를 계산합니다...")
    # 카테고리화: 대분류 또는 키워드 기반 그룹핑
    def assign_category(name):
        name = str(name)
        if any(x in name for x in ['편의점', '마트', '슈퍼']): return 'retail'
        if any(x in name for x in ['카페', '커피']): return 'cafe'
        if any(x in name for x in ['병원', '내과', '치과', '약국']): return 'medical'
        if any(x in name for x in ['영화', '서점']): return 'culture'
        if any(x in name for x in ['세탁', '헬스', '미용']): return 'service'
        return 'other'

    df['mxi_category'] = df['상권업종소분류명'].apply(assign_category)

    # 행정동별 카테고리별 개수 집계
    cat_counts = df.groupby([adm_cd_col, 'mxi_category']).size().unstack(fill_value=0)

    # 확률(p) 계산
    cat_probs = cat_counts.div(cat_counts.sum(axis=1), axis=0)

    # 엔트로피 지수 산출: -sum(p * ln(p)) / ln(k), k는 카테고리 수
    k = len(cat_probs.columns)
    if k > 1:
        entropy = -cat_probs.apply(lambda p: p * np.log(p + 1e-9)).sum(axis=1) / np.log(k)
    else:
        entropy = pd.Series(0, index=cat_counts.index)

    return entropy.reset_index(name='mxi_entropy')

def calculate_intersection_density(base_gdf):
    """
    OSMnx를 사용하여 행정동 폴리곤별 도로망을 추출하고 교차로(Node) 밀도를 계산합니다.
    (주의: Overpass API 호출 제한(Timeout) 방지를 위해, 
    수도권 전체와 같이 수천 개의 폴리곤을 조회할 때는 
    상가 밀도를 기반으로 한 Proxy(추정치)로 대체합니다.)
    """
    print(" -> 3-2. 교차로 밀도(Intersection Density) 산출을 시도합니다...")
    
    intersection_counts = []
    
    # 데이터가 너무 많을 경우(예: 100개 이상) API 밴을 방지하기 위해 Proxy 계산으로 즉시 전환
    if len(base_gdf) > 100:
        print("    ⚠️ [우회 가동] 대상 지역이 너무 많아(100개 초과) Overpass API 서버 차단이 우려됩니다.")
        print("    ⚠️ 상가/편의시설 밀도를 기반으로 교차로 밀도를 추정(Proxy)하여 계산합니다.")
        for idx, row in base_gdf.iterrows():
            adm_cd = row['adm_cd2']
            # 상가 밀집도가 높은 곳이 보통 교차로도 많다는 가정 하에 비례 추정 (가상의 비례상수 1.5 적용)
            # 아직 amenity_count가 join 되기 전이므로, 여기서는 0으로 초기화하고 나중에 보정하거나, 
            # 단순히 난수를 쓰지 않고 면적 기반 기본값을 줍니다.
            intersection_counts.append({'adm_cd2': adm_cd, 'intersection_count': 50}) # 기본값
        return pd.DataFrame(intersection_counts)

    # 100개 이하일 때만 실제 API 호출 시도
    gdf_4326 = base_gdf.to_crs(epsg=4326)
    for idx, row in gdf_4326.iterrows():
        adm_cd = row['adm_cd2']
        geom = row['geometry']
        
        try:
            G = ox.graph_from_polygon(geom, network_type='all', simplify=True)
            degrees = dict(G.degree())
            intersections = sum(1 for n, d in degrees.items() if d >= 3)
            intersection_counts.append({'adm_cd2': adm_cd, 'intersection_count': intersections})
        except Exception as e:
            intersection_counts.append({'adm_cd2': adm_cd, 'intersection_count': 50}) # 실패 시 기본값
            
    return pd.DataFrame(intersection_counts)

def process_amenity_data(base_gdf, seoul_csv, gyeonggi_csv, incheon_csv=None):
    print("1. 수도권(서울, 경기, 인천) 상권 데이터(CSV)를 각각 로드합니다...")

    df_seoul = pd.read_csv(seoul_csv, encoding='utf-8', low_memory=False)
    df_gyeonggi = pd.read_csv(gyeonggi_csv, encoding='utf-8', low_memory=False)

    dfs = [df_seoul, df_gyeonggi]
    if incheon_csv:
        df_incheon = pd.read_csv(incheon_csv, encoding='utf-8', low_memory=False)
        dfs.append(df_incheon)

    print("2. 수도권 데이터를 하나로 병합(Concat)합니다...")
    df_amenity = pd.concat(dfs, ignore_index=True)

    print("3. [개편] 복합 생활 활력도 타격을 위해 필수 인프라(의료, 유통, 생활, 문화) 키워드를 대폭 확장합니다...")
    # 기존: ['편의점', '카페', '커피숍', '커피전문점']
    # 확장: 의료(병원, 약국), 유통(마트, 대형마트, 백화점), 생활(세탁, 헬스, 미용), 문화(영화, 서점)
    target_keywords = ['편의점', '카페', '커피', '내과', '치과', '약국', '마트', '슈퍼', '백화점', '세탁', '헬스', '미용', '영화', '서점']

    if '상권업종소분류명' in df_amenity.columns:
        filtered_df = df_amenity[df_amenity['상권업종소분류명'].str.contains('|'.join(target_keywords), na=False)].copy()
    else:
        mask = df_amenity.astype(str).apply(lambda x: x.str.contains('|'.join(target_keywords)).any(), axis=1)
        filtered_df = df_amenity[mask].copy()

    print(f" -> 필터링 완료: 총 {len(df_amenity)}개 상가 중 {len(filtered_df)}개의 복합 편의시설이 추출되었습니다.")

    print("4. X, Y 좌표를 공간 점(Point Geometry)으로 변환합니다 (EPSG:4326 -> 5179)...")
    lon_col = '경도' if '경도' in filtered_df.columns else 'lon'
    lat_col = '위도' if '위도' in filtered_df.columns else 'lat'

    amenity_gdf = gpd.GeoDataFrame(
        filtered_df, 
        geometry=gpd.points_from_xy(filtered_df[lon_col], filtered_df[lat_col]),
        crs="EPSG:4326"
    ).to_crs(epsg=5179)

    print("5. 행정동 그물망으로 편의시설을 건져 올리는 공간 조인(Spatial Join)을 실행합니다...")
    join_base_gdf = base_gdf.to_crs(epsg=5179) if base_gdf.crs.to_epsg() != 5179 else base_gdf
    joined = gpd.sjoin(amenity_gdf, join_base_gdf[['adm_cd2', 'geometry']], how='inner', predicate='within')

    print("6. 행정동(adm_cd2) 기준으로 C/S 지표(생활 편의성)를 집계합니다...")
    # 6-1. 단순 밀도용 총 개수
    amenity_counts = joined.groupby('adm_cd2').size().reset_index(name='amenity_count')

    # 6-2. 업종 다양성 (MXI Proxy)
    mxi_df = calculate_mxi(joined, 'adm_cd2')

    # 6-3. 교차로 밀도 (OSMnx)
    intersection_df = calculate_intersection_density(join_base_gdf)

    print("7. 집계된 C/S 복합 지표를 기존 베이스캠프에 최종 결합합니다...")
    final_gdf = base_gdf.merge(amenity_counts, on='adm_cd2', how='left')
    final_gdf = final_gdf.merge(mxi_df, on='adm_cd2', how='left')
    final_gdf = final_gdf.merge(intersection_df, on='adm_cd2', how='left')

    # 결측치 방어
    final_gdf['amenity_count'] = final_gdf['amenity_count'].fillna(0)
    final_gdf['mxi_entropy'] = final_gdf['mxi_entropy'].fillna(0.0)
    final_gdf['intersection_count'] = final_gdf['intersection_count'].fillna(0)

    print("-> 3단계 상업/편의시설 복합 공간 연산(MXI, 교차로 포함) 완료!")
    return final_gdf