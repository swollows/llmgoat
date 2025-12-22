# API 동작 문제점 분석

이 문서는 LLMGoat 앱이 동작하는 과정에서 문제가 발생할 수 있는 부분을 정리한 것입니다.

---

## 🔴 확실한 버그

### 1. 잘못된 Flask 라우트 핸들러 시그니처

**파일:** `llmgoat/challenges/a09_misinformation.py` (Line 56-58)

```python
@a09_blueprint.route('/process_image', methods=['POST'])
def weird_route(request, llm):
    goatlog.debug("[*****] Should I ever be here?")
```

**문제점:**
- Flask 라우트 핸들러는 파라미터를 받지 않아야 하는데 `request`, `llm`을 파라미터로 정의함
- 이 라우트가 호출되면 **TypeError 발생**: `weird_route() missing 2 required positional arguments`
- 또한 return 문이 없어서 정상 작동해도 `None` 반환

---

### 2. reset_vectors 라우트 경로 오타

**파일:** `llmgoat/challenges/a08_vector_embedding_weaknesses.py` (Line 53)

```python
@a08_blueprint.route('reset_vectors', methods=['GET'])  # '/' 누락
def reset_vectors():
```

**문제점:**
- 라우트 경로 앞에 `/`가 빠져 있음
- `/api/a08-vector-embedding-weaknesses/reset_vectors`가 아닌 이상한 경로로 등록될 수 있음
- 다른 라우트들은 `/export_vectors`, `/import_vectors`로 정상적으로 시작함

---

### 3. 벡터 데이터에 잘못된 타입 저장

**파일:** `llmgoat/challenges/a08_vector_embedding_weaknesses.py` (Line 30, 57)

```python
VECTOR_STORE["Flag"] = ["a"] * VECTOR_DIMENSION  # 숫자 대신 문자열 "a" 32개
```

**문제점:**
- 다른 항목들은 `model.encode()`로 생성된 float 리스트인데 "Flag"만 문자열 리스트
- `cosine_similarity` 계산 시 `np.array(["a", "a", ...])` 로 변환되어 연산 실패
- try/except (Line 74-75)로 예외 처리되어 있어 크래시는 안 나지만 score가 -1 됨

---

## 🟠 런타임 에러 가능성

### 4. 파일 읽기 오류 시 예외 처리 없음

**파일:** `llmgoat/challenges/a09_misinformation.py` (Line 24-26)

```python
with open(ORIGINAL_IMAGE_PATH, "rb") as f:
    ORIGINAL_BYTES = f.read()
    ORIGINAL_HASH = get_image_rgb_hash(ORIGINAL_BYTES)
```

**문제점:**
- 모듈 임포트 시점에 실행됨
- 파일이 없으면 앱 전체가 시작 실패
- `static/challenges/goat.png` 파일 필수

---

### 5. import_vectors에서 파일 키 검증만 하고 형식 검증 안함

**파일:** `llmgoat/challenges/a08_vector_embedding_weaknesses.py` (Line 41-50)

```python
file = request.files['file']  # 'file' 키 없으면 KeyError
vectors = json.load(file)     # JSON 파싱 실패 시 예외
global VECTOR_STORE
VECTOR_STORE = vectors        # 형식 검증 없이 덮어씀
```

**문제점:**
- `request.files.get('file')`이 아닌 `request.files['file']` 사용 → 파일 없으면 **KeyError**
- 잘못된 JSON 파일 업로드 시 **JSONDecodeError**
- 두 경우 모두 500 에러 발생

---

### 6. None 체크 없이 .get("input") 사용

**파일:** `llmgoat/challenges/a01_prompt_injection.py` (Line 10)

```python
user_input = req.json.get("input", "")
```

**문제점:**
- `req.json`이 `None`일 경우 **AttributeError**: `'NoneType' object has no attribute 'get'`
- Content-Type이 `application/json`이 아니거나 빈 body일 때 발생
- `a02`, `a03` 등 일부 파일은 `(req.json or {}).get()`으로 올바르게 처리함

---

### 7. bare except로 모든 예외 무시

**파일:** `llmgoat/llm/manager.py` (Line 141-142)

```python
def call_llm(self, prompt):
    try:
        ...
    except:
        return "Error 500: The goat chewed on the server cables again."
```

**문제점:**
- 어떤 예외가 발생했는지 로깅하지 않음
- 실제 문제 발생 시 디버깅 불가능
- `KeyboardInterrupt`, `SystemExit` 등 시스템 예외도 잡힘

---

## 🟡 잠재적 문제

### 8. 메모리 정리 없는 세션 데이터 저장

**파일:** 
- `a04_data_and_model_poisoning.py` (Line 16): `reviews_store = {}`
- `a09_misinformation.py` (Line 21): `uploaded_images = {}`

**문제점:**
- 세션 별 데이터가 서버 메모리에 무기한 축적됨
- 이미지 데이터(`uploaded_images`)는 크기가 커서 메모리 압박 심함
- 서버 장시간 운영 시 메모리 부족 가능

---

### 9. global 변수 수정 시 레이스 컨디션

**파일:** `llmgoat/challenges/a08_vector_embedding_weaknesses.py` (Line 49, 56)

```python
global VECTOR_STORE
VECTOR_STORE = vectors
```

**문제점:**
- 여러 요청이 동시에 `import_vectors`나 `reset_vectors` 호출 시 데이터 불일치 가능
- `app.py`의 `llm_lock`이 이 라우트들에는 적용 안 됨

---

## � 요약

| 등급 | 파일 | 문제 |
|------|------|------|
| 🔴 | `a09_misinformation.py:56` | 잘못된 함수 시그니처 (호출 시 TypeError) |
| 🔴 | `a08_.py:53` | 라우트 경로 앞 `/` 누락 |
| 🔴 | `a08_.py:30` | 벡터에 문자열 저장 (타입 불일치) |
| 🟠 | `a09_.py:24` | 파일 없으면 앱 시작 실패 |
| � | `a08_.py:43` | 파일 키 없을 시 KeyError |
| � | `a01_.py:10` | req.json이 None일 때 AttributeError |
| 🟠 | `manager.py:141` | bare except 사용 |
| 🟡 | `a04_.py`, `a09_.py` | 메모리 누적 |
| � | `a08_.py` | 동시성 문제 |

---

*검토일: 2025-12-22*
