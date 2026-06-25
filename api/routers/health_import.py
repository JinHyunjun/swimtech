# -*- coding: utf-8 -*-
import csv
import io
import json
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from routers.training_log import _get_customer_id, _get_db

router = APIRouter()

# 업로드 파일이 커서 분석이 오래 걸릴 수 있어, 요청은 즉시 끝내고(게이트웨이 타임아웃 방지)
# 실제 분석은 백그라운드 스레드에서 진행 → 프론트는 job_id로 상태를 폴링.
# (인스턴스 재시작 시 사라지는 메모리 캐시이므로, 그 사이 끝내지 못한 작업은 다시 시도해야 함)
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()
_JOB_TTL_SECONDS = 30 * 60
_MAX_UPLOAD_BYTES = {
    "hae": 30 * 1024 * 1024,
    "apple": 100 * 1024 * 1024,
    "samsung": 80 * 1024 * 1024,
}
_ALLOWED_EXTENSIONS = {
    "hae": (".json",),
    "apple": (".zip",),
    "samsung": (".zip", ".csv"),
}


def _cleanup_old_jobs():
    cutoff = time.time() - _JOB_TTL_SECONDS
    with _JOBS_LOCK:
        for jid in [j for j, v in _JOBS.items() if v.get("created_at", 0) < cutoff]:
            _JOBS.pop(jid, None)


def _validate_preview_upload(content: bytes, filename: str, source: str):
    if source not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, "지원하지 않는 가져오기 형식입니다")
    lower_name = (filename or "").lower()
    if not lower_name.endswith(_ALLOWED_EXTENSIONS[source]):
        allowed = ", ".join(_ALLOWED_EXTENSIONS[source])
        raise HTTPException(400, f"{_provider_label(source)} 가져오기는 {allowed} 파일만 지원합니다")
    if not content:
        raise HTTPException(400, "빈 파일은 가져올 수 없습니다")
    if len(content) > _MAX_UPLOAD_BYTES[source]:
        limit_mb = _MAX_UPLOAD_BYTES[source] // 1024 // 1024
        raise HTTPException(400, f"파일이 너무 큽니다. {limit_mb}MB 이하 파일을 사용해주세요")

STROKE_LABELS = {
    "HKSwimmingStrokeStyleFreestyle": "자유형",
    "HKSwimmingStrokeStyleBackstroke": "배영",
    "HKSwimmingStrokeStyleBreaststroke": "평영",
    "HKSwimmingStrokeStyleButterfly": "접영",
    "HKSwimmingStrokeStyleMixed": "혼합",
    "HKSwimmingStrokeStyleUnknown": "혼합",
}

# 실제 export.xml에는 문자열이 아니라 HKSwimmingStrokeStyle의 숫자 rawValue로 기록됨
# (실제 사용자 데이터 약 7만 건의 분포로 검증한 매핑: 0=unknown,1=mixed,2=freestyle,
#  3=backstroke,4=breaststroke,5=butterfly,6=kickboard)
STROKE_CODE_LABELS = {
    "0": "혼합", "1": "혼합", "2": "자유형", "3": "배영",
    "4": "평영", "5": "접영", "6": "혼합",
}


def _stroke_label(value: str) -> str:
    value = (value or "").strip()
    if value in STROKE_CODE_LABELS:
        return STROKE_CODE_LABELS[value]
    return STROKE_LABELS.get(value, "혼합")


# "Health Auto Export" 앱의 strokeStyle 값(영어 문자열, 이미 깔끔하게 라벨링됨)
HAE_STROKE_LABELS = {
    "freestyle": "자유형", "backstroke": "배영", "breaststroke": "평영",
    "butterfly": "접영", "mixed": "혼합", "kickboard": "혼합", "unknown": "혼합",
}


def _ensure_wearable_table():
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wearable_workouts (
            id                          SERIAL PRIMARY KEY,
            customer_id                 INTEGER REFERENCES customers(id) ON DELETE CASCADE,

            provider                    TEXT NOT NULL,
            external_id                 TEXT,
            workout_type                TEXT,
            source_device               TEXT,

            started_at                  TIMESTAMP,
            ended_at                    TIMESTAMP,
            duration_minutes            INTEGER,

            distance_meters             NUMERIC,
            calories_kcal               NUMERIC,
            avg_heart_rate              NUMERIC,
            max_heart_rate              NUMERIC,

            pool_length_meters          NUMERIC,
            lap_count                   INTEGER,
            stroke_type                 TEXT,

            imported_to_training_log_id INTEGER REFERENCES training_logs(id) ON DELETE SET NULL,
            raw_data                    JSONB DEFAULT '{}'::jsonb,

            created_at                  TIMESTAMPTZ DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ DEFAULT NOW(),

            UNIQUE (customer_id, provider, external_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_wearable_customer ON wearable_workouts(customer_id)")
    conn.commit()
    cur.close()
    conn.close()


class ImportItem(BaseModel):
    external_id:      str
    log_date:         str
    started_at:       Optional[str] = None
    ended_at:         Optional[str] = None
    total_distance:   int
    duration_minutes: int
    stroke_type:      str = "자유형"
    calories:         Optional[float] = None
    pool_length:      int = 25
    source_device:    Optional[str] = None
    source:           str = "apple"   # apple | samsung | hae


class ImportConfirmRequest(BaseModel):
    items: List[ImportItem]


def _provider_label(source: str) -> str:
    if source == "apple":
        return "애플 건강"
    if source == "hae":
        return "Health Auto Export"
    return "삼성헬스"


def _provider_key(source: str) -> str:
    if source == "apple":
        return "apple_health"
    if source == "hae":
        return "health_auto_export"
    return "samsung_health"


def _existing_external_ids(cid: int, provider: str) -> set:
    _ensure_wearable_table()
    conn = _get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT external_id FROM wearable_workouts WHERE customer_id = %s AND provider = %s",
        (cid, provider),
    )
    rows = {r[0] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return rows


def _parse_apple_health_zip(file_bytes: bytes) -> List[dict]:
    """애플 건강 앱의 '건강 데이터 모두 내보내기' export.zip 안의 export.xml을 파싱.
    수영(HKWorkoutActivityTypeSwimming) Workout 엘리먼트만 추출."""
    results = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(400, "올바른 zip 파일이 아닙니다 (애플 건강 내보내기는 export.zip 형식이어야 합니다)")

    xml_candidates = [
        n for n in zf.namelist()
        if n.lower().endswith(".xml") and "cda" not in n.lower() and "/" in n and not n.lower().endswith("/")
    ]
    if not xml_candidates:
        raise HTTPException(400, "zip 안에서 건강 데이터 xml 파일을 찾을 수 없습니다")
    # 기기 언어에 따라 파일명이 'export.xml'이 아니라 '내보내기.xml' 등으로 로컬라이즈될 수 있어,
    # 이름이 아니라 가장 큰 파일(=핵심 건강기록 전체)을 기준으로 찾는다
    xml_name = max(xml_candidates, key=lambda n: zf.getinfo(n).file_size)

    KEEP_UNTIL_PARENT_DONE = {"WorkoutEvent", "MetadataEntry", "WorkoutStatistics"}

    with zf.open(xml_name) as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != "Workout":
                # WorkoutEvent/MetadataEntry/WorkoutStatistics는 Workout의 자손이라, 부모(Workout)가
                # 끝나기 전에 비우면 그 안의 영법(HKSwimmingStrokeStyle) 정보가 사라짐 — 비우지 않고 둠.
                # 나머지(Record 등 수백만 건의 걸음수·심박수)는 여기서 바로 비워 메모리 누수 방지.
                if elem.tag not in KEEP_UNTIL_PARENT_DONE:
                    elem.clear()
                continue
            activity = elem.get("workoutActivityType", "")
            if "Swimming" not in activity:
                elem.clear()
                continue

            start_raw = elem.get("startDate", "")
            end_raw = elem.get("endDate", "")
            try:
                dt = datetime.strptime(start_raw[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                elem.clear()
                continue

            duration_min = 0.0
            try:
                dur = float(elem.get("duration", 0) or 0)
                dur_unit = (elem.get("durationUnit", "min") or "min").lower()
                duration_min = dur / 60 if dur_unit.startswith("sec") else dur
            except Exception:
                pass

            distance_m = 0.0
            dist_raw = elem.get("totalDistance")
            dist_unit = (elem.get("totalDistanceUnit", "") or "").lower()
            if dist_raw:
                try:
                    dist_val = float(dist_raw)
                    if dist_unit.startswith("km"):
                        distance_m = dist_val * 1000
                    elif dist_unit.startswith("mi"):
                        distance_m = dist_val * 1609.34
                    elif dist_unit.startswith("yd"):
                        distance_m = dist_val * 0.9144
                    else:
                        distance_m = dist_val
                except Exception:
                    pass

            calories = None
            try:
                cal_raw = elem.get("totalEnergyBurned")
                if cal_raw:
                    calories = float(cal_raw)
            except Exception:
                pass

            pool_length = 25
            stroke_counter: dict = {}
            # HKSwimmingStrokeStyle은 Workout 직속 자식이 아니라 각 랩(WorkoutEvent) 안에 한 단계
            # 더 들어가 있어, elem.iter()로 전체 하위 트리를 재귀 탐색해야 함
            for meta in elem.iter("MetadataEntry"):
                key = meta.get("key", "")
                if key == "HKSwimmingStrokeStyle":
                    code = meta.get("value", "")
                    stroke_counter[code] = stroke_counter.get(code, 0) + 1
                elif key == "HKLapLength":
                    try:
                        pool_length = round(float((meta.get("value", "25 m") or "25 m").split()[0]))
                    except Exception:
                        pass
            for child in elem.findall("WorkoutStatistics"):
                stat_type = child.get("type") or ""
                if "Distance" in stat_type:
                    try:
                        sv = float(child.get("sum", 0) or 0)
                        su = (child.get("unit", "") or "").lower()
                        v = sv * 1000 if su.startswith("km") else sv
                        if v > distance_m:
                            distance_m = v
                    except Exception:
                        pass
                elif stat_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
                    try:
                        calories = float(child.get("sum", 0) or 0)
                    except Exception:
                        pass

            # 랩마다 영법이 섞여있을 수 있어, 가장 많이 등장한 영법을 그 운동의 대표 영법으로 사용
            stroke = "자유형"
            if stroke_counter:
                dominant_code = max(stroke_counter, key=stroke_counter.get)
                stroke = _stroke_label(dominant_code)

            source_device = elem.get("sourceName", "") or ""
            external_id = f"{start_raw}|{source_device}"

            results.append({
                "external_id": external_id,
                "log_date": dt.date().isoformat(),
                "started_at": start_raw,
                "ended_at": end_raw,
                "total_distance": round(distance_m),
                "duration_minutes": round(duration_min),
                "stroke_type": stroke,
                "calories": calories,
                "pool_length": pool_length,
                "source_device": source_device or "Apple Watch",
                "source": "apple",
            })
            elem.clear()
    return results


def _parse_samsung_csv(file_bytes: bytes) -> List[dict]:
    """삼성헬스 '내 데이터 다운로드'로 받은 운동(exercise) CSV를 파싱.
    삼성헬스 CSV는 버전/기기에 따라 컬럼명이 달라질 수 있어, 컬럼명에 포함된 키워드로
    유연하게 매칭한다 (정확한 스키마는 실제 내보내기 파일로 확인 후 조정이 필요할 수 있음)."""
    results = []
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("cp949", errors="ignore")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV 헤더를 읽을 수 없습니다")

    cols = {c.lower(): c for c in reader.fieldnames}

    def find_col(*keywords):
        for low, orig in cols.items():
            if all(k in low for k in keywords):
                return orig
        return None

    type_col = find_col("exercise", "type") or find_col("activity", "type") or find_col("type")
    start_col = find_col("start") or find_col("date")
    dur_col = find_col("duration")
    dist_col = find_col("distance")
    cal_col = find_col("calorie")
    uuid_col = find_col("uuid") or find_col("datauuid") or find_col("id")
    device_col = find_col("device") or find_col("pkg_name")

    if not (type_col and start_col):
        raise HTTPException(400, "삼성헬스 CSV에서 운동 종류 · 시작 시간 컬럼을 찾지 못했습니다. exercise(운동) 데이터 CSV가 맞는지 확인해주세요.")

    for row in reader:
        type_val = (row.get(type_col) or "").strip().lower()
        if "swim" not in type_val and "14002" not in type_val and "수영" not in type_val:
            continue
        start_val = (row.get(start_col) or "").strip()
        if not start_val:
            continue

        log_date = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                log_date = datetime.strptime(start_val[:19], fmt).date()
                break
            except Exception:
                continue
        if not log_date:
            continue

        duration_min = 0
        if dur_col:
            try:
                raw = float(row.get(dur_col) or 0)
                duration_min = round(raw / 60000) if raw > 1000 else round(raw)
            except Exception:
                pass

        distance_m = 0
        if dist_col:
            try:
                distance_m = round(float(row.get(dist_col) or 0))
            except Exception:
                pass

        calories = None
        if cal_col:
            try:
                calories = float(row.get(cal_col) or 0)
            except Exception:
                pass

        external_id = (row.get(uuid_col) or "").strip() if uuid_col else ""
        if not external_id:
            external_id = f"{start_val}|{distance_m}"

        results.append({
            "external_id": external_id,
            "log_date": log_date.isoformat(),
            "started_at": start_val,
            "ended_at": None,
            "total_distance": distance_m,
            "duration_minutes": duration_min,
            "stroke_type": "자유형",
            "calories": calories,
            "source_device": (row.get(device_col) or "Galaxy Watch") if device_col else "Galaxy Watch",
            "source": "samsung",
        })
    return results


def _hae_unit_to_meters(qty, unit) -> float:
    if qty is None:
        return 0.0
    unit = (unit or "").lower()
    qty = float(qty)
    if unit in ("km", "kilometer", "kilometers"):
        return qty * 1000
    if unit in ("mi", "mile", "miles"):
        return qty * 1609.34
    if unit in ("yd", "yard", "yards"):
        return qty * 0.9144
    return qty  # m으로 간주


def _parse_health_auto_export_json(file_bytes: bytes) -> List[dict]:
    """'Health Auto Export' 앱(https://www.healthexportapp.com)에서 '운동(Workouts)'만 내보낸
    JSON을 파싱. 애플 건강 전체 내보내기(800MB+)와 달리, 이 앱은 운동 데이터만 골라서
    수 KB~수 MB 수준의 작은 파일로 바로 내보낼 수 있어 훨씬 가볍다."""
    try:
        payload = json.loads(file_bytes.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(400, "올바른 JSON 파일이 아닙니다")

    workouts = (payload.get("data") or {}).get("workouts") or payload.get("workouts") or []
    if not isinstance(workouts, list):
        raise HTTPException(400, "워크아웃 데이터를 찾을 수 없습니다 ('운동' 데이터 타입으로 내보냈는지 확인해주세요)")

    results = []
    for w in workouts:
        name = (w.get("name") or "").strip()
        if "swim" not in name.lower() and "수영" not in name:
            continue

        start_raw = w.get("start", "")
        try:
            dt = datetime.strptime(start_raw[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        duration_min = round(float(w.get("duration") or 0) / 60)  # HAE는 duration이 '초' 단위

        distance_obj = w.get("distance") or {}
        distance_m = _hae_unit_to_meters(distance_obj.get("qty"), distance_obj.get("units"))

        lap_obj = w.get("lapLength") or {}
        pool_length = round(_hae_unit_to_meters(lap_obj.get("qty"), lap_obj.get("units"))) or 25

        stroke_raw = (w.get("strokeStyle") or "").strip().lower()
        stroke = HAE_STROKE_LABELS.get(stroke_raw, "자유형" if not stroke_raw else "혼합")

        calories = None
        for key in ("activeEnergyBurned", "totalEnergy", "activeEnergy"):
            v = w.get(key)
            if isinstance(v, dict) and v.get("qty") is not None:
                calories = float(v["qty"])
                break

        external_id = str(w.get("id") or f"{start_raw}|{name}")

        results.append({
            "external_id": external_id,
            "log_date": dt.date().isoformat(),
            "started_at": start_raw,
            "ended_at": w.get("end"),
            "total_distance": round(distance_m),
            "duration_minutes": duration_min,
            "stroke_type": stroke,
            "calories": calories,
            "pool_length": pool_length,
            "source_device": "Health Auto Export",
            "source": "hae",
        })
    return results


def _find_samsung_exercise_csv(zf: zipfile.ZipFile) -> str:
    candidates = [n for n in zf.namelist() if n.lower().endswith(".csv") and "exercise" in n.lower()]
    if not candidates:
        raise HTTPException(400, "zip 안에서 운동(exercise) 관련 CSV 파일을 찾지 못했습니다")
    return sorted(candidates, key=len)[0]


def _run_import_job(job_id: str, content: bytes, filename: str, source: str, cid: int):
    """백그라운드 스레드에서 실행되는 실제 분석 작업."""
    try:
        if source == "apple":
            if not filename.endswith(".zip"):
                raise ValueError("애플 건강 내보내기는 .zip 파일이어야 합니다")
            items = _parse_apple_health_zip(content)
        elif source == "samsung":
            if filename.endswith(".zip"):
                try:
                    zf = zipfile.ZipFile(io.BytesIO(content))
                except zipfile.BadZipFile:
                    raise ValueError("올바른 zip 파일이 아닙니다")
                csv_name = _find_samsung_exercise_csv(zf)
                with zf.open(csv_name) as f:
                    items = _parse_samsung_csv(f.read())
            elif filename.endswith(".csv"):
                items = _parse_samsung_csv(content)
            else:
                raise ValueError("지원하지 않는 파일 형식입니다 (.zip 또는 .csv만 가능)")
        elif source == "hae":
            if not filename.endswith(".json"):
                raise ValueError("Health Auto Export 내보내기는 .json 파일이어야 합니다")
            items = _parse_health_auto_export_json(content)
        else:
            raise ValueError("알 수 없는 데이터 출처입니다")

        if not items:
            with _JOBS_LOCK:
                _JOBS[job_id] = {**_JOBS.get(job_id, {}), "status": "done", "items": []}
            return

        existing_ids = _existing_external_ids(cid, _provider_key(source))
        out = [
            {**it, "is_duplicate": it["external_id"] in existing_ids}
            for it in sorted(items, key=lambda x: x["started_at"] or x["log_date"], reverse=True)
        ]
        with _JOBS_LOCK:
            _JOBS[job_id] = {**_JOBS.get(job_id, {}), "status": "done", "items": out}
    except HTTPException as e:
        with _JOBS_LOCK:
            _JOBS[job_id] = {**_JOBS.get(job_id, {}), "status": "error", "detail": e.detail}
    except Exception as e:
        with _JOBS_LOCK:
            _JOBS[job_id] = {**_JOBS.get(job_id, {}), "status": "error", "detail": str(e)}


@router.post("/preview")
async def preview_import(request: Request, file: UploadFile = File(...), source: str = "apple"):
    """파일을 받아 백그라운드 분석 작업을 등록하고 즉시 job_id를 반환 (게이트웨이 타임아웃 방지).
    실제 결과는 /preview/status/{job_id}로 따로 조회."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")

    _cleanup_old_jobs()
    content = await file.read()
    filename = (file.filename or "").lower()
    source = (source or "").strip().lower()
    _validate_preview_upload(content, filename, source)

    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "processing",
            "created_at": time.time(),
            "customer_id": cid,
            "source": source,
            "filename": filename,
        }

    thread = threading.Thread(
        target=_run_import_job, args=(job_id, content, filename, source, cid), daemon=True
    )
    thread.start()

    return {"job_id": job_id}


@router.get("/preview/status/{job_id}")
def preview_status(job_id: str, request: Request):
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "해당 작업을 찾을 수 없습니다 (서버가 재시작되었거나 만료됨)")
    if job.get("customer_id") != cid:
        raise HTTPException(404, "해당 작업을 찾을 수 없습니다")
    return job


@router.post("/confirm")
def confirm_import(body: ImportConfirmRequest, request: Request):
    """사용자가 선택한 항목을 wearable_workouts에 원본 보존 후, training_logs로 변환."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    if len(body.items) > 200:
        raise HTTPException(400, "한 번에 최대 200건까지만 가져올 수 있습니다")

    _ensure_wearable_table()
    conn = _get_db()
    cur = conn.cursor()
    added = 0
    skipped = 0
    try:
        for it in body.items:
            provider = _provider_key(it.source)
            cur.execute("""
                INSERT INTO wearable_workouts
                    (customer_id, provider, external_id, workout_type, source_device,
                     started_at, ended_at, duration_minutes, distance_meters, calories_kcal,
                     pool_length_meters, stroke_type, raw_data)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (customer_id, provider, external_id) DO NOTHING
                RETURNING id
            """, (
                cid, provider, it.external_id, "swimming", it.source_device,
                it.started_at, it.ended_at, it.duration_minutes, it.total_distance, it.calories,
                it.pool_length, it.stroke_type, json.dumps(it.dict()),
            ))
            row = cur.fetchone()
            if not row:
                skipped += 1
                continue
            wearable_id = row[0]

            source_label = _provider_label(it.source)
            cur.execute("""INSERT INTO training_logs
                (customer_id, log_date, stroke_type, total_distance, duration_minutes, pool_length, intensity, memo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (cid, it.log_date, it.stroke_type, it.total_distance, it.duration_minutes,
                 it.pool_length, "보통", f"[{source_label} 가져오기]"))
            log_id = cur.fetchone()[0]

            cur.execute(
                "UPDATE wearable_workouts SET imported_to_training_log_id = %s, updated_at = NOW() WHERE id = %s",
                (log_id, wearable_id),
            )
            added += 1
        conn.commit()
        return {"added": added, "skipped": skipped}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"가져오기 오류: {e}")
    finally:
        cur.close()
        conn.close()


@router.get("/workouts")
def list_wearable_workouts(request: Request):
    """그동안 가져온 워치 운동 기록 전체 조회 (감사/이력 확인용)."""
    cid = _get_customer_id(request)
    if not cid:
        raise HTTPException(401, "로그인이 필요합니다")
    _ensure_wearable_table()
    conn = _get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, provider, started_at, distance_meters, duration_minutes,
               stroke_type, source_device, imported_to_training_log_id, created_at
        FROM wearable_workouts WHERE customer_id = %s
        ORDER BY started_at DESC LIMIT 200
    """, (cid,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {"workouts": [
        {
            "id": r[0], "provider": r[1], "started_at": str(r[2]) if r[2] else None,
            "distance_meters": float(r[3]) if r[3] is not None else None,
            "duration_minutes": r[4], "stroke_type": r[5], "source_device": r[6],
            "imported_to_training_log_id": r[7], "created_at": str(r[8]),
        }
        for r in rows
    ]}
