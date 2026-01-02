import os
import gc
import shutil
import subprocess

from llama_cpp import Llama
from transformers import BlipProcessor, BlipForConditionalGeneration, utils as TransformersUtils

from llmgoat.utils import definitions
from llmgoat.llm.prompting import detect_prompt_format, detect_prompt_format_details
from llmgoat.llm.output_sanitizer import strip_think_blocks
from llmgoat.utils.logger import goatlog
from llmgoat.utils.helpers import download_file  # kept for backward compat
from llmgoat.utils.llama_logger import capture_llama_prints


# ----------------------------
# Model specs
# ----------------------------
# 기본(Windows/일반 PC)용: Qwen3-8B Q8_0
QWEN3_8B_Q8_NAME = "qwen3-8b-q8_0.gguf"

# 기본 fallback: Gemma2-9B Q4_K_M
GEMMA2_9B_Q4KM_NAME = "gemma-2-9b-it-Q4_K_M.gguf"

# DGX용 “고품질” Gemma2: 27B Q6_K_L
GEMMA2_27B_Q6KL_NAME = "gemma-2-27b-it-Q6_K_L.gguf"

# DGX용 Qwen3: 32B Q8_0 (공식 GGUF repo 파일명 그대로 - 대소문자 중요)
QWEN3_32B_Q8_NAME = "Qwen3-32B-Q8_0.gguf"


MODEL_SPECS = {
    # Windows/기본용
    "qwen3_8b_q8": {
        "name": QWEN3_8B_Q8_NAME,
        "repo_id": "devmasa/Qwen3-8B-Q8_0-GGUF",
        "filename": QWEN3_8B_Q8_NAME,
        "sha256": None,
    },
    "gemma2_9b_q4km": {
        "name": GEMMA2_9B_Q4KM_NAME,
        "repo_id": "bartowski/gemma-2-9b-it-GGUF",
        "filename": GEMMA2_9B_Q4KM_NAME,
        "sha256": None,
    },

    # DGX용
    "gemma2_27b_q6kl": {
        "name": GEMMA2_27B_Q6KL_NAME,
        "repo_id": "bartowski/gemma-2-27b-it-GGUF",
        "filename": GEMMA2_27B_Q6KL_NAME,
        "sha256": None,
    },
    "qwen3_32b_q8": {
        "name": QWEN3_32B_Q8_NAME,
        "repo_id": "Qwen/Qwen3-32B-GGUF",
        "filename": QWEN3_32B_Q8_NAME,
        "sha256": None,
    },
}

# 프로필별 “다운로드 대상”을 분리해서,
# 기본 프로필에서 DGX급 파일을 실수로 받지 않도록 함.
MODEL_PROFILES = {
    # 기본(Windows/일반 PC): Qwen3-8B 우선 + Gemma2-9B fallback
    "default": ["qwen3_8b_q8", "gemma2_9b_q4km"],

    # DGX: Gemma2-27B + Qwen3-32B를 함께 준비(번갈아 실습)
    # (fallback으로 Gemma2-9B도 같이)
    "dgx": ["gemma2_27b_q6kl", "qwen3_32b_q8", "gemma2_9b_q4km"],
}

DEFAULT_PROFILE = "default"

# 로드 우선순위(프로필별)
PROFILE_LOAD_PRIORITY = {
    "default": [QWEN3_8B_Q8_NAME, GEMMA2_9B_Q4KM_NAME],
    "dgx": [GEMMA2_27B_Q6KL_NAME, QWEN3_32B_Q8_NAME, GEMMA2_9B_Q4KM_NAME],
}


MAX_TOKENS = 256
TEMPERATURE = 0.7


class LLManager:
    _instance = None  # the Singleton instance
    _init_started = False  # Ensure init is run only once
    _llm_instance = None  # the LLM current instance
    _current_model = None  # the currently loaded model (name)
    _current_model_path = None  # the currently loaded model path
    _prompt_format = None  # cached PromptFormat for the current model

    # ----------------------------
    # Model download helpers (HF CLI)
    # ----------------------------
    def _ensure_models_dir(self, models_dir: str):
        os.makedirs(models_dir, exist_ok=True)

    def _hf_cli_path(self):
        return shutil.which("huggingface-cli")

    def _get_profile(self) -> str:
        profile = os.environ.get("LLMGOAT_MODEL_PROFILE", DEFAULT_PROFILE).strip().lower()
        if profile not in MODEL_PROFILES:
            goatlog.warning(
                f"Unknown LLMGOAT_MODEL_PROFILE='{profile}'. Falling back to '{DEFAULT_PROFILE}'. "
                f"Valid: {list(MODEL_PROFILES.keys())}"
            )
            return DEFAULT_PROFILE
        return profile

    def _run_hf_cli_download(self, repo_id: str, filename: str, local_dir: str):
        """
        Download a single file from Hugging Face Hub using huggingface-cli.

        NOTE:
        - Gemma 계열은 Hugging Face에서 라이선스 동의/로그인이 필요할 수 있음.
          (huggingface-cli login + 해당 모델 페이지에서 약관 동의)
        """
        cli = self._hf_cli_path()
        if not cli:
            raise RuntimeError(
                "huggingface-cli not found in PATH. "
                "Install it (pip install -U 'huggingface_hub[cli]') or add it to PATH."
            )

        cmd = [cli, "download", repo_id, filename, "--local-dir", local_dir]

        # Windows에서 symlink 이슈 회피 옵션(환경에 따라 필요)
        if os.name == "nt":
            cmd += ["--local-dir-use-symlinks", "False"]

        goatlog.info(f"[HF] Downloading via CLI: {repo_id}/{filename} -> {local_dir}")

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(
                "huggingface-cli download failed.\n"
                f"cmd: {' '.join(cmd)}\n"
                f"stdout:\n{res.stdout}\n"
                f"stderr:\n{res.stderr}\n"
            )

    def _find_file_recursive(self, root_dir: str, target_name: str):
        for root, _, files in os.walk(root_dir):
            for f in files:
                if f == target_name:
                    return os.path.join(root, f)
        return None

    def _ensure_model_present(self, spec: dict, models_dir: str):
        """
        Ensure the model file exists directly under models_dir.
        Returns True if present (or successfully downloaded), else False.
        """
        target_path = os.path.join(models_dir, spec["name"])
        if os.path.exists(target_path):
            return True

        # Download via huggingface-cli
        self._run_hf_cli_download(spec["repo_id"], spec["filename"], models_dir)

        # huggingface-cli가 nested 경로에 놓는 경우가 있어 root로 끌어올림
        if not os.path.exists(target_path):
            found = self._find_file_recursive(models_dir, spec["filename"])
            if found:
                try:
                    if os.path.abspath(found) != os.path.abspath(target_path):
                        os.replace(found, target_path)
                except Exception:
                    shutil.move(found, target_path)

        return os.path.exists(target_path)

    def _spec_by_model_filename(self, model_filename: str):
        for spec in MODEL_SPECS.values():
            if spec["name"] == model_filename:
                return spec
        return None

    def ensure_profile_models(self, models_dir: str = definitions.DEFAULT_MODELS_FOLDER):
        """
        Download models for the current profile at app startup (unless disabled).
        """
        if os.environ.get("LLMGOAT_SKIP_MODEL_DOWNLOAD", "0") == "1":
            goatlog.warning("LLMGOAT_SKIP_MODEL_DOWNLOAD=1 set; skipping model downloads.")
            return

        self._ensure_models_dir(models_dir)

        profile = self._get_profile()
        profile_keys = MODEL_PROFILES[profile]
        specs = [MODEL_SPECS[k] for k in profile_keys]

        # 사용자가 LLMGOAT_DEFAULT_MODEL을 지정했다면, 그 모델이 SPEC에 존재할 경우
        # 프로필과 무관하게 “추가로” 보장 다운로드.
        selected_model = os.environ.get(definitions.LLMGOAT_DEFAULT_MODEL)
        if selected_model:
            extra = self._spec_by_model_filename(selected_model)
            if extra and extra not in specs:
                specs.insert(0, extra)

        goatlog.info(f"Model profile = '{profile}'. Will ensure: {[s['name'] for s in specs]}")

        for spec in specs:
            try:
                if self._ensure_model_present(spec, models_dir=models_dir):
                    goatlog.info(f"Model present: {spec['name']}")
                else:
                    goatlog.warning(f"Model missing after download attempt: {spec['name']}")
            except Exception as e:
                goatlog.warning(f"Could not ensure model '{spec['name']}': {e}")

    # ----------------------------
    # Singleton
    # ----------------------------
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ----------------------------
    # Init / Load
    # ----------------------------
    def load_additional_models(self):
        goatlog.info("Downloading 'Salesforce/blip-image-captioning-base'...")
        BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
        goatlog.info("Download of 'Salesforce/blip-image-captioning-base' completed")

    def init(self):
        if self._init_started:
            return
        self._init_started = True

        # Profile-based model preparation (IMPORTANT)
        self.ensure_profile_models()

        available_models = self.available_models()

        selected_model = os.environ.get(definitions.LLMGOAT_DEFAULT_MODEL)

        if len(available_models) == 0:
            raise RuntimeError(
                f"No .gguf models found in {definitions.DEFAULT_MODELS_FOLDER}. "
                "Either enable downloads (LLMGOAT_SKIP_MODEL_DOWNLOAD=0) and ensure huggingface-cli works, "
                "or manually place .gguf models into the models folder."
            )

        # 1) If available load the selected model
        if selected_model in available_models:
            goatlog.info("Selected model is available, loading it...")
            self.load_model(selected_model)
        else:
            # 2) Otherwise load by profile priority
            profile = self._get_profile()
            priority = PROFILE_LOAD_PRIORITY.get(profile, PROFILE_LOAD_PRIORITY[DEFAULT_PROFILE])
            loaded = False
            for candidate in priority:
                if candidate in available_models:
                    goatlog.info(f"Loading by profile priority: {candidate}")
                    self.load_model(candidate)
                    loaded = True
                    break

            # 3) Fallback: first available
            if not loaded:
                goatlog.info(f"Loading the first available model: {available_models[0]}")
                self.load_model(available_models[0])

        # Set HF verbosity
        verbose_env_value = os.environ.get(definitions.LLMGOAT_VERBOSE, str(int(False)))
        is_silent = True if verbose_env_value == "0" else False
        if is_silent:
            TransformersUtils.logging.disable_progress_bar()
            TransformersUtils.logging.set_verbosity_error()

        # Load additional stuff
        self.load_additional_models()

    def free_llm_instance(self):
        if self._llm_instance is not None:
            try:
                self._llm_instance.__del__()
            except Exception:
                pass

            self._llm_instance = None
            gc.collect()
            goatlog.info("Previous model instance freed from memory.")

    def load_model(self, model):
        goatlog.info("Model check")

        if self._current_model != model:
            try:
                goatlog.info(f"Loading model: {model}")

                # get number of CPU cores + GPU layers
                n_threads = min(os.cpu_count(), int(os.environ.get(definitions.LLMGOAT_N_THREADS)))
                n_gpu_layers = int(os.environ.get(definitions.LLMGOAT_N_GPU_LAYERS))

                # explicitly free the memory taken by the current model
                self.free_llm_instance()

                model_path = os.path.join(definitions.DEFAULT_MODELS_FOLDER, model)
                verbose_env_value = os.environ.get(definitions.LLMGOAT_VERBOSE, str(int(False)))
                is_verbose = True if verbose_env_value == "1" else False

                with capture_llama_prints():
                    self._llm_instance = Llama(
                        model_path=model_path,
                        n_ctx=40960,
                        n_threads=n_threads,
                        n_batch=32,
                        n_gpu_layers=n_gpu_layers,
                        verbose=is_verbose,
                    )

                self._current_model = model
                self._current_model_path = model_path

                self._prompt_format, fmt_reason = detect_prompt_format_details(model, model_path=model_path)
                goatlog.info(
                    f"Prompt format: {self._prompt_format.name} (reason={fmt_reason}, stop={self._prompt_format.stop})"
                )

                goatlog.info(f"Hardware config: {n_threads} CPU cores, n_gpu_layers: {n_gpu_layers}")
            except Exception as e:
                goatlog.error(f"An error occurred: {str(e)}")

    def get_model(self):
        if self._llm_instance is None:
            raise RuntimeError("Model not loaded yet")
        return self._llm_instance

    def available_models(self, models_dir=definitions.DEFAULT_MODELS_FOLDER):
        os.makedirs(models_dir, exist_ok=True)
        return [
            f
            for f in os.listdir(models_dir)
            if f.lower().endswith(".gguf") and os.path.isfile(os.path.join(models_dir, f))
        ]

    def get_current_model_name(self):
        return self._current_model

    def get_current_model_path(self):
        return self._current_model_path

    def call_llm(self, prompt, stop=None):
        try:
            llm = self.get_model()
            if stop is None:
                if self._prompt_format is not None:
                    stop = self._prompt_format.stop
                else:
                    stop = detect_prompt_format(
                        self.get_current_model_name(),
                        model_path=self.get_current_model_path(),
                    ).stop

            output = llm(
                prompt,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                stop=stop,
            )
            text = output["choices"][0]["text"].strip()
            return strip_think_blocks(text)
        except:
            return "Error 500: The goat chewed on the server cables again."