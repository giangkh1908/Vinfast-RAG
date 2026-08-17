"""Ingest full specs matrix vào DB.

Với mỗi combination (spec_key, model_code), nếu chưa có row → insert với value='Không'.
Điều này giúp LLM query DB và biết chính xác xe nào có/không có tính năng gì.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def ingest_full_matrix():
    from app.core.db import get_pool
    
    pool = await get_pool()
    
    print("Đang lấy danh sách specs và models...")
    async with pool.acquire() as conn:
        # Lấy ingest_version hiện tại
        ingest_version = await conn.fetchval("""
            SELECT version FROM ingest_version WHERE is_current LIMIT 1
        """)
        if not ingest_version:
            print("❌ Không tìm thấy ingest_version hiện tại")
            return
        
        print(f"Ingest version: {ingest_version}")
        
        # Lấy tất cả spec_keys (chỉ lấy distinct combinations)
        specs = await conn.fetch("""
            SELECT DISTINCT ON (spec_key, spec_category) 
                spec_key, spec_category, spec_category_vn, spec_key_vn, source_url
            FROM car_specs
            ORDER BY spec_key, spec_category
        """)
        
        # Lấy tất cả model_codes
        models = await conn.fetch("""
            SELECT DISTINCT model_code 
            FROM car_specs 
            ORDER BY model_code
        """)
        
        print(f"Tìm thấy {len(specs)} specs và {len(models)} models")
        
        # Tạo set các combinations đã có (với version_name=NULL, version_code=NULL)
        existing = await conn.fetch("""
            SELECT DISTINCT spec_key, model_code, spec_category
            FROM car_specs
            WHERE version_name IS NULL AND version_code IS NULL
        """)
        existing_combos = {(r['spec_key'], r['model_code'], r['spec_category']) for r in existing}
        print(f"Đã có {len(existing_combos)} combinations với version=NULL")
        
        # Tìm các combinations thiếu
        missing = []
        for spec in specs:
            for model in models:
                combo = (spec['spec_key'], model['model_code'], spec['spec_category'])
                if combo not in existing_combos:
                    missing.append({
                        'spec_key': spec['spec_key'],
                        'spec_category': spec['spec_category'],
                        'spec_category_vn': spec['spec_category_vn'],
                        'spec_key_vn': spec['spec_key_vn'],
                        'model_code': model['model_code'],
                        'source_url': spec['source_url'],
                    })
        
        print(f"Cần thêm {len(missing)} rows với value='Không'")
        
        if not missing:
            print("✓ Database đã đầy đủ, không cần thêm gì")
            return
        
        # Batch insert với ON CONFLICT DO NOTHING
        batch_size = 100
        inserted = 0
        skipped = 0
        
        for i in range(0, len(missing), batch_size):
            batch = missing[i:i + batch_size]
            
            # Tạo values clause
            values = []
            for row in batch:
                values.append(f"""(
                    '{ingest_version}',
                    '{row['model_code']}',
                    NULL,
                    NULL,
                    '{row['spec_category']}',
                    {f"'{row['spec_category_vn']}'" if row['spec_category_vn'] else 'NULL'},
                    '{row['spec_key']}',
                    {f"'{row['spec_key_vn']}'" if row['spec_key_vn'] else 'NULL'},
                    'Không',
                    NULL,
                    {f"'{row['source_url']}'" if row['source_url'] else 'NULL'},
                    CURRENT_TIMESTAMP
                )""")
            
            values_str = ',\n'.join(values)
            
            sql = f"""
                INSERT INTO car_specs (
                    ingest_version, model_code, version_name, version_code,
                    spec_category, spec_category_vn, spec_key, spec_key_vn,
                    spec_value, spec_unit, source_url, updated_at
                ) VALUES {values_str}
                ON CONFLICT (ingest_version, model_code, COALESCE(version_code, ''), 
                           COALESCE(version_name, ''), spec_category, spec_key) 
                DO NOTHING
            """
            
            result = await conn.execute(sql)
            # Parse result to get inserted count
            inserted_count = int(result.split()[-1]) if result else 0
            inserted += inserted_count
            skipped += (len(batch) - inserted_count)
            print(f"Batch {i//batch_size + 1}: thêm {inserted_count}, bỏ qua {len(batch) - inserted_count}")
        
        print(f"\n✓ Hoàn thành!")
        print(f"  - Đã thêm: {inserted} rows")
        print(f"  - Đã bỏ qua (tồn tại): {skipped} rows")
        
        # Verify
        final_count = await conn.fetchval("SELECT COUNT(*) FROM car_specs")
        print(f"✓ Tổng số rows trong car_specs: {final_count}")
        
        # Count rows with value='Không'
        khong_count = await conn.fetchval("""
            SELECT COUNT(*) FROM car_specs WHERE spec_value = 'Không'
        """)
        print(f"✓ Số rows với value='Không': {khong_count}")


if __name__ == "__main__":
    asyncio.run(ingest_full_matrix())
