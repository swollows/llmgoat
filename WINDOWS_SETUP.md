# LLMGoat Windows 설치 가이드

## 실습 환경 용도

이 가이드는 **실습 자료 화면 제작**을 위한 Windows 환경 설정입니다.

---

## 시스템 사양

| 항목 | 스펙 |
|------|------|
| CPU | AMD Ryzen 5 5600X |
| GPU | NVIDIA RTX 5060 Ti (16GB VRAM) |
| RAM | 32GB DDR4 |
| OS | Windows 10/11 |

---

## 추천 모델

16GB VRAM 환경에서는 FP16 대신 **양자화 모델** 사용이 필요합니다.

| 모델 | 양자화 | VRAM | 추천도 |
|------|--------|------|--------|
| **Qwen 2.5 7B Instruct** | Q8_0 | ~8GB | ⭐⭐⭐ |
| **Gemma 2 9B IT** | Q4_K_M | ~6GB | ⭐⭐⭐ |
| Llama 3.1 8B | Q8_0 | ~9GB | ⭐⭐ |
| Qwen 2.5 14B | Q4_K_M | ~9GB | ⭐⭐ |

---

## 설치 방법

### 1. 사전 준비

```powershell
# Python 3.10+ 설치 확인
python --version

# CUDA Toolkit 설치 (12.x 권장)
# https://developer.nvidia.com/cuda-downloads 에서 다운로드

# Git 설치
winget install Git.Git
```

### 2. 가상환경 생성

```powershell
# 작업 폴더 생성
mkdir C:\llmgoat
cd C:\llmgoat

# 가상환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. llama-cpp-python 설치 (CUDA)

```powershell
# Visual Studio Build Tools 필요
# https://visualstudio.microsoft.com/visual-cpp-build-tools/ 에서 설치

# CUDA 버전으로 llama-cpp-python 설치
$env:CMAKE_ARGS="-DGGML_CUDA=on"
pip install llama-cpp-python --force-reinstall --no-cache-dir
```

> **참고:** 빌드 오류 시 사전 빌드된 휠 사용:
> ```powershell
> pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
> ```

### 4. LLMGoat 설치

```powershell
# 저장소 클론
git clone https://github.com/swollows/llmgoat.git
cd llmgoat

# 의존성 설치
pip install -e .
```

### 5. 모델 다운로드

```powershell
# HuggingFace CLI 설치
pip install huggingface_hub

# Qwen 2.5 7B Q8_0 다운로드 (~8GB)
huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF `
  qwen2.5-7b-instruct-q8_0.gguf `
  --local-dir C:\llmgoat\models

# 또는 Gemma 2 9B Q4_K_M (~6GB)
huggingface-cli download google/gemma-2-9b-it-GGUF `
  gemma-2-9b-it-q4_k_m.gguf `
  --local-dir C:\llmgoat\models
```

### 6. 실행

```powershell
# 모델 폴더 설정
$env:LLMGOAT_MODELS_FOLDER="C:\llmgoat\models"

# Qwen 2.5 7B로 실행
llmgoat --model qwen2.5-7b-instruct-q8_0.gguf --gpu-layers -1

# 또는 Gemma 2 9B로 실행
llmgoat --model gemma-2-9b-it-q4_k_m.gguf --gpu-layers -1
```

---

## 문제 해결

### CUDA 빌드 오류

```powershell
# 사전 빌드된 휠 사용 (CUDA 12.4)
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

### VRAM 부족

```powershell
# GPU 레이어 수 조절 (일부만 GPU에 로드)
llmgoat --model qwen2.5-7b-instruct-q8_0.gguf --gpu-layers 20
```

### 방화벽 문제

```powershell
# 외부 접속 허용 시
llmgoat --host 0.0.0.0 --port 5000
```

---

## 빠른 시작 (요약)

```powershell
# 1. 가상환경
python -m venv venv && .\venv\Scripts\Activate.ps1

# 2. 설치
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
git clone https://github.com/swollows/llmgoat.git && cd llmgoat
pip install -e .

# 3. 모델 다운로드
pip install huggingface_hub
huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF qwen2.5-7b-instruct-q8_0.gguf --local-dir models

# 4. 실행
llmgoat --model qwen2.5-7b-instruct-q8_0.gguf --gpu-layers -1
```

**접속:** http://127.0.0.1:5000

---

*작성일: 2025-12-23*
