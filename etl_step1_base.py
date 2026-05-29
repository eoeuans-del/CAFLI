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

    print("2. [수정] 통계청(SGIS)과 행안부(MOIS) 코드 불일치 및 인구 통계 원본 손상 문제 해결을 위해 외부 매핑 테이블을 로드합니다...")
    import urllib.request
    import json
    import os
    
    mapping_path = './data/adm_mapping.json'
    if not os.path.exists(mapping_path):
        url = 'https://raw.githubusercontent.com/vuski/admdongkor/master/ver20230701/HangJeongDong_ver20230701.geojson'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with open(mapping_path, 'wb') as f:
                f.write(response.read())
                
    with open(mapping_path, 'r', encoding='utf-8') as f:
        mapping_data = json.load(f)
        
    mapping_df = pd.DataFrame([feat['properties'] for feat in mapping_data['features']])
    # adm_cd8(통계청 8자리)를 기준으로 병합
    mapping_df['adm_cd8'] = mapping_df['adm_cd8'].astype(str)
    
    # 조인
    gdf_boundaries = gdf_boundaries.merge(mapping_df[['adm_cd8', 'adm_nm', 'sggnm', 'sidonm']], left_on='adm_cd2', right_on='adm_cd8', how='left')
    
    # 결측치(매핑 실패) 방어: 기존 로직으로 폴백
    sido_map = {
        '11': '서울특별시', '21': '부산광역시', '22': '대구광역시', '23': '인천광역시',
        '24': '광주광역시', '25': '대전광역시', '26': '울산광역시', '29': '세종특별자치시',
        '31': '경기도', '32': '강원도', '33': '충청북도', '34': '충청남도',
        '35': '전라북도', '36': '전라남도', '37': '경상북도', '38': '경상남도', '39': '제주특별자치도'
    }
    
    adm_nm_col = 'ADM_NM'
    if 'ADM_NM' not in gdf_boundaries.columns:
        adm_nm_col = [c for c in gdf_boundaries.columns if 'NM' in c.upper()][0]
        
    fallback_sido = gdf_boundaries['adm_cd2'].str[:2].map(sido_map)
    fallback_nm = fallback_sido + " " + gdf_boundaries[adm_nm_col]
    
    # 매핑 성공하면 adm_nm, 실패하면 fallback_nm 사용
    gdf_boundaries['행정구역'] = gdf_boundaries['adm_nm'].fillna(fallback_nm)
    
    # 시군구 단위를 묶기 위한 파생 컬럼 (예: 서울특별시 종로구)
    gdf_boundaries['sido_sgg'] = gdf_boundaries['sidonm'].fillna(fallback_sido) + " " + gdf_boundaries['sggnm'].fillna("")
    gdf_boundaries['sido_sgg'] = gdf_boundaries['sido_sgg'].str.strip()

    print("3. 베이스 데이터(base_gdf) 구축을 완료합니다...")
    base_gdf = gdf_boundaries.copy()
    
    # 공간 연산 및 SJOIN(공간 조인) 정밀도를 위해 좌표계를 미터 단위 평면 좌표계(EPSG:5179)로 통일
    if not base_gdf.crs:
        base_gdf.set_crs(epsg=5179, allow_override=True, inplace=True)
    elif base_gdf.crs.to_epsg() != 5179:
        base_gdf = base_gdf.to_crs(epsg=5179)

    # [방어벽 4]: VWORLD 원본에 면적(area_sqkm)이 없을 경우, 3/4단계 붕괴를 막기 위한 공간 연산 자동 보정
    if 'area_sqkm' not in base_gdf.columns:
        base_gdf['area_sqkm'] = base_gdf.geometry.area / 1e6

    print(f"-> 총 {len(base_gdf)}개 타겟 행정동의 베이스 데이터 구축이 성공적으로 완료되었습니다.")
    
    return base_gdf