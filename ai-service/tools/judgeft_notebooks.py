"""학습 노트북과 채점 노트북을 만든다(스펙 6절, 8-1절).

실행:  cd ai-service && $PY -m tools.judgeft_notebooks       # notebooks/judgeft_train_colab.ipynb, judgeft_eval_colab.ipynb

노트북을 손으로 고치지 않고 이 파일에서 만든다. 이유는 셋이다.
1. 상수(LoRA 설정, 라이브러리 판, 시험지 해시)를 judgeft_files 한 곳에서 가져와, 노트북과 도구의 값이 어긋나지 않게 한다.
2. 토큰화 함수(judgeft_labels.build_example)의 본문을 글자 그대로 옮긴다. CI 가 점검한 함수와 코랩이 쓰는 함수가 같다.
3. 점검(judgeft_check)이 이 파일로 노트북을 다시 만들어 커밋된 노트북과 바이트까지 같은지 본다. 손으로 고친 곳이 있으면 걸린다.
"""
from __future__ import annotations

import inspect
import json
import sys

from . import judgeft_files as F
from .judge5 import MAX_NEW_TOKENS, smoke_messages
from .judgeft_labels import build_example

TRAIN_NB = F.ROOT / "notebooks" / "judgeft_train_colab.ipynb"
EVAL_NB = F.ROOT / "notebooks" / "judgeft_eval_colab.ipynb"
DRIVE_DIR = "/content/drive/MyDrive/alldap_judgeft"


def _hashes() -> dict[str, str]:
    """동결 커밋 전에는 해시 파일이 없어 빈 글자다. 노트북은 빈 해시를 받으면 멈춘다(동결 전 실행을 막는다)."""
    out = {"cases_new": "", "train": "", "val": ""}
    if F.CASES_SHA.exists():
        out["cases_new"] = F.CASES_SHA.read_text(encoding="utf-8").split()[0]
    if F.TRAIN_SHA.exists():
        # dict((키, 값) 짝들): 해시 파일의 줄은 "해시  파일이름" 이다. split() 으로 둘로 나누고 reversed 로 뒤집어
        # (파일이름, 해시) 짝을 만들면, dict 가 파일이름 -> 해시 로 찾는 표가 된다.
        lines = dict(reversed(line.split()) for line in F.TRAIN_SHA.read_text(encoding="utf-8").splitlines())
        out["train"], out["val"] = lines.get("train.jsonl", ""), lines.get("val.jsonl", "")
    return out


def _md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def _code(text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text}


def _nb(cells: list[dict]) -> dict:
    return {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
                                         "kernelspec": {"display_name": "Python 3", "name": "python3"}},
            "nbformat": 4, "nbformat_minor": 0}


# 사용자 안내(두 노트북 공통). 사용자는 파이썬과 코랩에 익숙하지 않다.
GUIDE = """**처음 여는 법:** colab.research.google.com 에서 파일 > 노트북 업로드 로 이 `.ipynb` 파일을 고른다.

**허용 창:** 첫 실행에서 두 창이 뜬다. "이 노트북에 보안 비밀 액세스 권한을 부여하시겠습니까?" 에는 **액세스 권한 부여**, "이 노트북에서 Google Drive 파일에 액세스하도록 허용하시겠습니까?" 에는 **Google Drive에 연결** 을 누르고 계정을 고른 뒤 모두 허용한다. `HF_TOKEN` 이 목록에 있으면 그 줄의 "노트북 액세스" 스위치를 켠다.

**오류가 나면:** 모두 실행이 그 칸에서 멈추고 zip 도 내려받아지지 않는다. 빨간 오류 글의 **마지막 다섯 줄쯤** 을 복사해 그대로 알려 준다. 칸을 고치거나 값을 바꾸지 않는다.

**오래 걸리는 동안:** 브라우저 탭을 닫지 않고 열어 둔다. 컴퓨터의 잠자기를 끈다(맥: 시스템 설정 > 디스플레이 또는 배터리 > 잠자기 방지). 무료 GPU 한도에 걸려 "GPU 백엔드에 연결할 수 없습니다" 가 뜨면 몇 시간 뒤(보통 다음 날) 다시 연다. 이미 한 일은 Drive 에 남아 이어 한다."""

PIP = "!pip install -q " + " ".join(f'"{k}=={v}"' for k, v in F.PINS.items()) + " huggingface_hub\n"

COMMON = f'''import gc, glob, hashlib, json, math, os, platform, random, shutil, time
import torch, transformers, bitsandbytes, peft, accelerate
from google.colab import drive, userdata, files
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, GenerationConfig

drive.mount('/content/drive')
DIR = {DRIVE_DIR!r}
HF_TOKEN = userdata.get('HF_TOKEN')
M3_REPO = {F.M3_REPO!r}
M3_REVISION = {F.M3_REVISION!r}   # v2 와 같은 리비전으로 고정한다(스펙 6-1절)
PINS = {F.PINS!r}

def sha_of(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()

def env_record():
    # 판이 하나라도 다르면 같은 설정에서도 출력이 달라질 수 있다(스펙 6-2절). torch 는 코랩에 깔린 것을 적기만 한다.
    env = {{'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__, 'python': platform.python_version(),
           'transformers': transformers.__version__, 'bitsandbytes': bitsandbytes.__version__,
           'peft': peft.__version__, 'accelerate': accelerate.__version__}}
    wrong = {{k: (v, env[k]) for k, v in PINS.items() if env[k] != v}}
    assert not wrong, f'고정한 판과 다르게 깔렸습니다: {{wrong}}. 런타임을 다시 시작하고 첫 칸부터 다시 실행하세요.'
    return env

def check_env(saved_path):
    # 이어 할 때는 처음 세션과 판이 같아야 한다. 다르면 이어 붙인 결과가 한 환경의 결과가 아니게 된다.
    if os.path.exists(saved_path):
        old = json.load(open(saved_path))
        diff = {{k: (old.get(k), ENV.get(k)) for k in set(old) | set(ENV) if old.get(k) != ENV.get(k)}}
        assert not diff, f'처음 세션과 환경이 다릅니다: {{diff}}. 멈추고 이 줄을 그대로 알려 주세요.'
    else:
        json.dump(ENV, open(saved_path, 'w'), indent=2)

QUANT = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                           bnb_4bit_compute_dtype=torch.float16)  # v2 와 같다. T4 는 bf16 을 지원하지 않는다

def load_base():
    tok = AutoTokenizer.from_pretrained(M3_REPO, revision=M3_REVISION, token=HF_TOKEN)
    # dtype=float16: 4비트로 바뀌지 않는 부분(임베딩, lm_head, 정규화층)의 정밀도. v2 노트북과 같다(스펙 6-1절).
    model = AutoModelForCausalLM.from_pretrained(M3_REPO, revision=M3_REVISION, quantization_config=QUANT,
                                                 dtype=torch.float16, device_map='auto', token=HF_TOKEN)
    return tok, model
'''


def train_notebook() -> dict:
    h = _hashes()
    header = """# AllDap 채점 모델 파인튜닝: 학습 (M3 + LoRA)

설계: `docs/superpowers/specs/2026-10-05-judge-finetune-design.md` (6절, 7-2절)

**실행 방법**
1. 런타임 > 런타임 유형 변경 > **T4 GPU**. 왼쪽 열쇠 아이콘(보안 비밀)에 이름 `HF_TOKEN` 으로 Hugging Face 토큰을 넣는다.
2. Drive 의 `MyDrive/alldap_judgeft/` 에 `train.jsonl`, `val.jsonl` 을 올린다.
3. **관문 (b)**: 둘째 칸 맨 위를 `MODE = 'gate_b'` 로 고치고 **모두 실행**. 끝나면 `gate_b.json` 이 생긴다. 메모리 부족이나 loss 가 숫자가 아니면 멈추고 알린다(스펙 7-2절).
4. **학습**: 런타임 > 세션 다시 시작 뒤 `MODE = 'train'` 으로 바꾸고 **모두 실행**. 관문 (b) 에서 만든 LoRA 를 이어 쓰지 않도록 반드시 세션을 다시 시작한다. 체크포인트가 하나라도 생긴 뒤에는 `gate_b` 를 다시 돌릴 수 없다.
5. 끊기면 세션을 다시 시작하고 `MODE = 'train'` 그대로 **모두 실행** 한다. 가장 최근의 온전한 체크포인트에서 이어 한다.
6. 끝나면 마지막 칸이 `alldap_judgeft_train.zip`(학습 기록, 어댑터 해시)을 내려받는다. 어댑터 파일은 Drive 의 `adapter/` 에 남는다.

**Drive 휴지통:** 이 노트북은 오래된 체크포인트(하나에 약 0.4GB, 재지 않은 어림)를 지운다. 지운 파일은 Drive 휴지통으로 가서 용량을 계속 차지한다. 학습 기록에 찍히는 `drive_free_gb` 가 3 아래로 내려가면 drive.google.com 의 휴지통에서 **휴지통 비우기** 를 누른다.

설정은 한 번만 학습한다(스펙 6-5절). 이 노트북의 설정 값을 바꾸지 않는다. 시험지는 이 노트북에 없다.

""" + GUIDE
    setup = '''MODE = ''   # 'gate_b' 또는 'train'. 비워 두면 멈춘다(실수로 다른 단계를 돌리지 않게)
assert MODE in ('gate_b', 'train'), "MODE 를 'gate_b' 또는 'train' 으로 고치고 다시 모두 실행하세요."
''' + COMMON + f'''
TRAIN = f'{{DIR}}/train.jsonl'
VAL = f'{{DIR}}/val.jsonl'
EXPECTED = {{'train': {h["train"]!r}, 'val': {h["val"]!r}}}
assert EXPECTED['train'] and EXPECTED['val'], '동결 커밋 전의 노트북입니다. 계획 E11 뒤의 노트북을 쓰세요.'
assert sha_of(TRAIN) == EXPECTED['train'] and sha_of(VAL) == EXPECTED['val'], '올린 학습 데이터의 해시가 다릅니다.'
TRAIN_ROWS = [json.loads(l) for l in open(TRAIN, encoding='utf-8') if l.strip()]
VAL_ROWS = [json.loads(l) for l in open(VAL, encoding='utf-8') if l.strip()]
CKPT = f'{{DIR}}/checkpoints'
ADAPTER = f'{{DIR}}/adapter'
LOG = f'{{DIR}}/training_log.jsonl'
os.makedirs(CKPT, exist_ok=True)
ENV = env_record()

def checkpoints():
    # 완성 표시(done 파일)가 있는 체크포인트만 센다. 저장 도중 끊긴 체크포인트는 done 이 없어 건너뛴다(스펙 6-4절).
    return sorted((int(p.rsplit('-', 1)[1]), p) for p in glob.glob(f'{{CKPT}}/step-*') if os.path.exists(f'{{p}}/done'))

def log(rec):
    open(LOG, 'a').write(json.dumps(rec) + '\\n')

if MODE == 'gate_b':
    assert not checkpoints(), '학습 체크포인트가 이미 있습니다. 관문 (b) 는 학습 전에만 돌립니다. MODE 를 확인하세요.'
else:
    check_env(f'{{DIR}}/train_env.json')   # 첫 학습 세션이면 적고, 이어 하는 세션이면 처음과 비교한다
# 세션마다 한 줄. 읽는 쪽은 단계마다 마지막 줄을 쓴다(끊긴 뒤 다시 한 단계가 두 번 적힐 수 있다).
log({{'session_start': time.time(), 'mode': MODE, 'env': ENV}})
print(len(TRAIN_ROWS), len(VAL_ROWS), ENV)
'''
    model_cell = f'''from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
from safetensors.torch import load_file

LORA_R, LORA_ALPHA, LORA_DROPOUT = {F.LORA_R}, {F.LORA_ALPHA}, {F.LORA_DROPOUT}
LORA_TARGETS = {list(F.LORA_TARGETS)!r}
LEARNING_RATE, EPOCHS, GRAD_ACCUM, WARMUP_RATIO = {F.LEARNING_RATE}, {F.EPOCHS}, {F.GRAD_ACCUM}, {F.WARMUP_RATIO}
KEEP_CHECKPOINTS, TRAIN_SEED = {F.KEEP_CHECKPOINTS}, {F.TRAIN_SEED}

{inspect.getsource(build_example)}
random.seed(TRAIN_SEED); torch.manual_seed(TRAIN_SEED)   # LoRA 초기값을 고정한다
tok, model = load_base()
END_ID = tok.convert_tokens_to_ids('<|im_end|>')
eos = model.generation_config.eos_token_id
assert END_ID in (eos if isinstance(eos, list) else [eos]), '끝 토큰이 생성의 멈춤 토큰이 아니다'
# prepare_model_for_kbit_training 을 쓰지 않는다. 그 함수는 4비트가 아닌 층을 float32 로 바꾸는데, 임베딩과 lm_head 만
# 약 6GB 가 되어 T4 에 들어가지 않을 수 있다. 메모리를 줄이는 두 설정만 직접 켠다.
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={{'use_reentrant': False}})
model.enable_input_require_grads()   # gradient checkpointing 에서 입력 쪽 기울기 경로를 연다(LoRA 만 학습해도 필요하다)
model.config.use_cache = False
model = get_peft_model(model, LoraConfig(r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT,
                                         target_modules=LORA_TARGETS, task_type='CAUSAL_LM'))
for n, p in model.named_parameters():
    if p.requires_grad:
        p.data = p.data.float()   # LoRA 가중치는 float32 로 둔다. float16 으로 고치면 작은 갱신이 0 이 된다(스펙 6-2절)
model.print_trainable_parameters()

def encode_row(row):
    ids, n = build_example(lambda m: tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False),
                           lambda s: tok(s, add_special_tokens=False)['input_ids'], row['messages'], row['target'], END_ID)
    return torch.tensor(ids, device='cuda'), n

def row_loss(row):
    ids, n = encode_row(row)
    with torch.autocast('cuda', dtype=torch.float16):
        # logits_to_keep=n+1: 마지막 n+1 위치의 logits 만 계산한다. 모범 답안의 토큰 n 개를 맞히는 데 필요한 것이
        # 그 앞 위치들이기 때문이다. 입력 위치의 logits(약 15만 어휘 곱하기 입력 길이)를 만들지 않아 메모리가 준다.
        out = model(input_ids=ids[None], logits_to_keep=n + 1)
    logits = out.logits[0, :-1].float()   # n 개 위치. float32 로 바꿔 loss 를 계산한다
    return torch.nn.functional.cross_entropy(logits, ids[-n:])

TOTAL_STEPS = EPOCHS * math.ceil(len(TRAIN_ROWS) / GRAD_ACCUM)
WARMUP = max(1, round(WARMUP_RATIO * TOTAL_STEPS))
opt = bitsandbytes.optim.PagedAdamW8bit([p for p in model.parameters() if p.requires_grad], lr=LEARNING_RATE)
sched = transformers.get_cosine_schedule_with_warmup(opt, WARMUP, TOTAL_STEPS)
scaler = torch.amp.GradScaler('cuda')   # float16 혼합 정밀도의 loss scaling(스펙 6-2절)
print('학습 단계', TOTAL_STEPS, 'warmup', WARMUP)

def batches():
    """학습 단계마다 문항 묶음. 바퀴마다 시드로 순서를 섞는다. 같은 시드면 끊겼다 이어 해도 같은 순서다."""
    for e in range(EPOCHS):
        order = random.Random(f'{{TRAIN_SEED}}:{{e}}').sample(range(len(TRAIN_ROWS)), len(TRAIN_ROWS))
        for i in range(0, len(order), GRAD_ACCUM):
            yield [TRAIN_ROWS[j] for j in order[i:i + GRAD_ACCUM]]

def train_step(batch):
    losses = []
    for row in batch:
        loss = row_loss(row) / len(batch)
        if not torch.isfinite(loss):
            raise RuntimeError(f'loss 가 숫자가 아니다({{loss.item()}}). 설정을 바꾸지 않고 멈춘다(스펙 6-5절).')
        scaler.scale(loss).backward()
        losses.append(loss.item() * len(batch))
    scale = scaler.get_scale()
    scaler.step(opt); scaler.update(); sched.step(); opt.zero_grad(set_to_none=True)
    # 기울기에 inf, NaN 이 있으면 scaler 는 그 단계의 갱신을 건너뛰고 scale 을 줄인다. 줄었으면 건너뛴 것이다.
    # 약 135단계 중 warmup 이 4단계라 앞쪽 건너뜀이 많으면 학습이 덜 된 채 끝날 수 있어 기록한다.
    return sum(losses) / len(losses), scale, scaler.get_scale() < scale
'''
    gate_cell = '''if MODE == 'gate_b':
    # from_pretrained 는 모델을 eval 모드로 돌려주고 get_peft_model 은 바깥 껍데기만 training=True 로 둔다.
    # 층이 eval 이면 gradient checkpointing 이 꺼져(층의 조건이 gradient_checkpointing and training) 메모리를 더 쓴다.
    # 그러면 관문이 메모리 부족으로 거짓 실패하거나 step_seconds, est_hours, save_every 가 학습과 다르게 나온다.
    model.train()
    layers = model.base_model.model.model.layers
    assert all(l.gradient_checkpointing and l.training for l in layers), 'gradient checkpointing 이 켜지지 않았습니다'
    lengths = [(len(encode_row(r)[0]), r['id']) for r in TRAIN_ROWS + VAL_ROWS]
    longest_tokens, longest_id = max(lengths)
    row = next(r for r in TRAIN_ROWS + VAL_ROWS if r['id'] == longest_id)
    torch.cuda.reset_peak_memory_stats()
    times, losses = [], []
    for _ in range(2):   # 학습 단계 둘. 첫 단계는 준비 시간이 섞이므로 둘째 단계의 시간을 쓴다
        t = time.time(); losses.append(train_step([row] * GRAD_ACCUM)[0]); torch.cuda.synchronize(); times.append(time.time() - t)
        assert all(l.gradient_checkpointing and l.training for l in layers), '첫 단계 뒤 gradient checkpointing 이 꺼졌습니다'
    step_seconds = times[-1]
    res = {'longest_id': longest_id, 'longest_tokens': longest_tokens, 'losses': losses, 'env': ENV,
           'finite': all(math.isfinite(x) for x in losses),
           'peak_gb': round(torch.cuda.max_memory_allocated() / 1024**3, 2), 'step_seconds': round(step_seconds, 1),
           'total_steps': TOTAL_STEPS, 'est_hours': round(step_seconds * TOTAL_STEPS / 3600, 1),
           'save_every': max(1, int(1800 // step_seconds))}
    json.dump(res, open(f'{DIR}/gate_b.json', 'w'), indent=2)
    print(res)
    assert res['finite'], 'loss 가 숫자가 아니다. 멈추고 사용자에게 알린다(스펙 7-2절)'
'''
    train_cell = '''def val_loss():
    model.eval()
    with torch.no_grad():
        v = sum(row_loss(r).item() for r in VAL_ROWS) / len(VAL_ROWS)
    model.train()
    return v

FILES = ('adapter_model.safetensors', 'state.pt')

def drive_free_gb():
    # Drive 를 붙인 폴더의 남은 용량. Drive 가 알려 주는 값이라 휴지통이 차지한 몫이 빠져 있을 수 있다(재지 않음).
    return round(shutil.disk_usage(DIR).free / 1024**3, 1)

def save(step):
    p = f'{CKPT}/step-{step}'
    shutil.rmtree(p, ignore_errors=True)   # 같은 번호의 깨진 체크포인트가 남아 있으면 그 done 이 새 것으로 보이지 않게 지운다
    os.makedirs(p)
    model.save_pretrained(p)
    torch.save({'opt': opt.state_dict(), 'sched': sched.state_dict(), 'scaler': scaler.state_dict(), 'step': step,
                'py': random.getstate(), 'torch': torch.get_rng_state(), 'cuda': torch.cuda.get_rng_state()}, f'{p}/state.pt')
    # done 은 마지막에 쓴다. 이 파일이 있어야 완성된 체크포인트다. 두 파일의 해시를 적어 이어 할 때 깨졌는지 본다.
    json.dump({f: sha_of(f'{p}/{f}') for f in FILES}, open(f'{p}/done', 'w'))
    for _, old in checkpoints()[:-KEEP_CHECKPOINTS]:
        shutil.rmtree(old)   # 가장 최근 둘만 남긴다(Drive 15GB, 스펙 6-4절). 지운 파일은 Drive 휴지통으로 간다

def load_checkpoint(p):
    """해시가 맞고 읽히면 단계 번호를, 아니면 None 을 돌려준다. 읽다가 실패하면 모델이 반쯤 바뀌었을 수 있어 멈춘다."""
    want = json.load(open(f'{p}/done'))
    got = {f: sha_of(f'{p}/{f}') for f in FILES}
    if got != want:
        return None
    set_peft_model_state_dict(model, load_file(f'{p}/adapter_model.safetensors'))
    s = torch.load(f'{p}/state.pt', weights_only=False)
    opt.load_state_dict(s['opt']); sched.load_state_dict(s['sched']); scaler.load_state_dict(s['scaler'])
    random.setstate(s['py']); torch.set_rng_state(s['torch']); torch.cuda.set_rng_state(s['cuda'])
    return s['step']

if MODE == 'train':
    SAVE_EVERY = json.load(open(f'{DIR}/gate_b.json'))['save_every']
    start = 0
    # 가장 최근 것부터 본다. 해시가 맞지 않거나 파일을 읽지 못하면 기록하고 지운 뒤 하나 앞의 것으로 간다.
    # 최근 둘을 남기는 이유(스펙 6-4절)를 코드가 실제로 쓰는 자리다.
    for n, p in reversed(checkpoints()):
        try:
            got = load_checkpoint(p)
            why = None if got is not None else '해시가 done 에 적힌 것과 다르다'
        except Exception as e:   # 파일이 잘려 safetensors 나 torch.load 가 실패한 경우
            raise RuntimeError(f'체크포인트 {p} 를 읽다가 멈췄습니다({e}). 모델 상태가 섞였을 수 있어 세션을 다시 시작하고 '
                               f'이 체크포인트 폴더를 지운 뒤 다시 모두 실행하세요.') from e
        if why is None:
            start = got
            log({'resumed_from': start, 'at': time.time(), 'env': ENV})
            print('이어 한다:', p)
            break
        log({'bad_checkpoint': n, 'reason': why, 'at': time.time()})
        print('깨진 체크포인트를 건너뛴다:', p, why)
        shutil.rmtree(p)
    model.train()
    for step, batch in enumerate(batches(), 1):
        if step <= start:
            continue   # 이미 한 단계는 건너뛴다. batches() 는 시드로 순서가 정해져 있어 같은 자리에서 이어진다
        loss, scale, skipped = train_step(batch)
        rec = {'step': step, 'train_loss': loss, 'lr': sched.get_last_lr()[0], 'scale': scale, 'skipped': skipped,
               'at': time.time()}
        if step % SAVE_EVERY == 0 or step == TOTAL_STEPS:
            rec['val_loss'] = val_loss()
            save(step)
            rec['drive_free_gb'] = drive_free_gb()
        log(rec)
        print(rec)
    model.save_pretrained(ADAPTER)   # 채점에 쓰는 어댑터는 마지막 단계의 것이다(스펙 6-3절). 검증 loss 로 고르지 않는다
    sha = sha_of(f'{ADAPTER}/adapter_model.safetensors')
    json.dump({'adapter_sha256': sha, 'steps': TOTAL_STEPS, 'env': ENV}, open(f'{DIR}/train_done.json', 'w'), indent=2)
    print('어댑터 SHA-256:', sha)
'''
    zip_cell = '''os.makedirs('/content/train_out', exist_ok=True)
for name in ('gate_b.json', 'training_log.jsonl', 'train_done.json', 'train_env.json'):
    if os.path.exists(f'{DIR}/{name}'):
        shutil.copy(f'{DIR}/{name}', '/content/train_out/')
shutil.make_archive('/content/alldap_judgeft_train', 'zip', '/content/train_out')
files.download('/content/alldap_judgeft_train.zip')
'''
    return _nb([_md(header), _code(PIP), _code(setup), _code(model_cell), _code(gate_cell), _code(train_cell),
                _code(zip_cell)])


def eval_notebook() -> dict:
    h = _hashes()
    header = f"""# AllDap 채점 모델 파인튜닝: 채점 (학습 전 M3, 학습 후 M3)

설계: `docs/superpowers/specs/2026-10-05-judge-finetune-design.md` (8-1절)

**실행 방법**
1. 런타임 > 런타임 유형 변경 > **T4 GPU**. 왼쪽 열쇠 아이콘(보안 비밀)에 이름 `HF_TOKEN` 으로 Hugging Face 토큰을 넣는다.
2. Drive 의 `MyDrive/alldap_judgeft/` 에 `cases_new.jsonl`(새 시험지 `testdata/judgeft/cases.jsonl`)과 `cases_frozen.jsonl`(동결 시험지 `testdata/judge5v2/cases.jsonl`)을 올린다. 학습 후 M3 를 돌릴 때는 학습 노트북이 만든 `adapter/` 가 같은 폴더에 있어야 한다.
3. 둘째 칸의 `SHEET`, `MODEL`, `RUN` 을 오케스트레이터가 알려 준 값으로 바꾼다. 학습 후 M3 이면 오케스트레이터가 준 `ADAPTER_SHA256 = '...'` 한 줄을 그 자리에 그대로 붙여 넣는다. 학습 전 M3 이면 `ADAPTER_SHA256` 을 비워 둔다.
4. **모두 실행**. 끊기면 세션을 다시 시작하고 같은 값으로 모두 실행한다. 이미 채점한 문항은 건너뛴다(반쯤 쓴 마지막 줄은 버리고 그 문항부터 다시 한다).
5. 끝나면 마지막 칸이 결과 파일 둘(`<모델>_run<번호>.jsonl`, `.env.json`)을 담은 zip 을 내려받는다.

**학습이 끝날 때까지 새 시험지의 결과 파일을 열어 보지 않는다**(스펙 6-5절). 내려받은 zip 은 그대로 오케스트레이터에 넘긴다.
생성 설정은 v2 와 같다(탐욕적 디코딩, 최대 출력 {MAX_NEW_TOKENS} 토큰, repetition_penalty 1.0).

""" + GUIDE
    setup = '''SHEET = 'frozen'      # 'new' 또는 'frozen'
MODEL = 'M3pre'       # 'M3pre'(학습 전) 또는 'M3ft'(학습 후)
RUN = 1               # 1, 2, 3
ADAPTER_SHA256 = ''   # MODEL 이 'M3ft' 일 때 학습 노트북의 어댑터 해시
''' + COMMON + f'''
assert SHEET in ('new', 'frozen') and MODEL in ('M3pre', 'M3ft') and RUN in (1, 2, 3)
# 학습 전 M3 에 해시가 적혀 있으면 어느 쪽을 돌리려던 것인지 알 수 없다. 결과 줄의 adapter_sha256 도 거짓이 된다.
assert (MODEL == 'M3pre') == (ADAPTER_SHA256 == ''), 'M3pre 이면 ADAPTER_SHA256 을 비우고, M3ft 이면 채웁니다.'
EXPECTED = {{'new': {h["cases_new"]!r}, 'frozen': {F.FROZEN_SHA256!r}}}
MAX_NEW_TOKENS = {MAX_NEW_TOKENS}
SMOKE_MESSAGES = {json.dumps(smoke_messages(), ensure_ascii=False)}
CASES = f'{{DIR}}/cases_{{SHEET}}.jsonl'
assert EXPECTED[SHEET], '동결 커밋 전의 노트북입니다. 계획 E11 뒤의 노트북을 쓰세요.'
sha = sha_of(CASES)
assert sha == EXPECTED[SHEET], f'시험지 해시가 다릅니다: {{sha}}'
CASE_ROWS = [json.loads(l) for l in open(CASES, encoding='utf-8') if l.strip()]
OUT = f'{{DIR}}/results/{{SHEET}}'
os.makedirs(OUT, exist_ok=True)
PATH = f'{{OUT}}/{{MODEL}}_run{{RUN}}.jsonl'
ENV = env_record()
check_env(PATH.replace('.jsonl', '.env.json'))   # 첫 세션이면 적고, 이어 하는 세션이면 처음과 비교한다
print(len(CASE_ROWS), '문항', ENV)
'''
    run_cell = '''tok, model = load_base()
if MODEL == 'M3ft':
    from peft import PeftModel
    assert ADAPTER_SHA256 and sha_of(f'{DIR}/adapter/adapter_model.safetensors') == ADAPTER_SHA256, '어댑터 해시가 다릅니다'
    model = PeftModel.from_pretrained(model, f'{DIR}/adapter')   # 어댑터를 바탕 모델 위에 얹는다(합치지 않는다)
model.eval()
# 생성 설정은 v2 노트북과 같게 처음부터 만든다. 저장소 기본값의 repetition_penalty 1.05 가 섞이지 않게 한다.
eos = model.generation_config.eos_token_id
pad = tok.pad_token_id if tok.pad_token_id is not None else (eos[0] if isinstance(eos, list) else eos)
gen = GenerationConfig(max_new_tokens=MAX_NEW_TOKENS, do_sample=False, repetition_penalty=1.0,
                       eos_token_id=eos, pad_token_id=pad)

def generate(messages):
    text = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    enc = tok(text, return_tensors='pt', add_special_tokens=False).to(model.device)
    with torch.no_grad():
        out = model.generate(**enc, generation_config=gen, use_model_defaults=False)
    new = out[0, enc['input_ids'].shape[1]:]
    finish = 'length' if new.shape[0] >= MAX_NEW_TOKENS else 'stop'
    return tok.decode(new, skip_special_tokens=True), finish

text, finish = generate(SMOKE_MESSAGES)
assert text.strip(), '가짜 문항의 출력이 비었다. 멈추고 알린다'
json.dump({'model': MODEL, 'output': text, 'finish': finish, 'generation': gen.to_dict()},
          open(f'{OUT}/{MODEL}_run{RUN}_smoke.json', 'w'), ensure_ascii=False, indent=2)
def resume_lines():
    """이미 쓴 줄. 마지막 줄이 쓰다가 끊겨 JSON 이 아니면 버리고 파일을 다시 쓴다. 버린 것은 기록한다."""
    if not os.path.exists(PATH):
        return []
    raw = [l for l in open(PATH, encoding='utf-8').read().split('\\n') if l.strip()]
    good = []
    for i, l in enumerate(raw):
        try:
            good.append(json.loads(l))
        except json.JSONDecodeError:
            assert i == len(raw) - 1, f'{PATH} 의 {i + 1}번째 줄이 깨졌습니다. 마지막 줄이 아니라 멈춥니다.'
            open(PATH, 'w', encoding='utf-8').write(''.join(json.dumps(g, ensure_ascii=False) + '\\n' for g in good))
            open(f'{OUT}/{MODEL}_run{RUN}_resume.log', 'a').write(json.dumps({'dropped_partial_line': l[:200], 'at': time.time()}) + '\\n')
            print('반쯤 쓴 마지막 줄을 버리고 이어 한다')
    return good

done = {g['case_id'] for g in resume_lines()}
for i, row in enumerate(CASE_ROWS):
    if row['case_id'] in done:
        continue
    text, finish = generate(row['messages'])
    line = {'case_id': row['case_id'], 'model': MODEL, 'repo': M3_REPO, 'revision': M3_REVISION, 'run': RUN,
            'output': text, 'finish': finish, 'cases_sha256': sha, 'domain': row['domain'],
            'adapter_sha256': ADAPTER_SHA256 or None}
    with open(PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(line, ensure_ascii=False) + '\\n')
    print(i + 1, '/', len(CASE_ROWS), finish)   # 점수는 찍지 않는다. 학습이 끝날 때까지 결과를 보지 않는다
'''
    zip_cell = '''name = f'alldap_judgeft_{SHEET}_{MODEL}_run{RUN}'
os.makedirs(f'/content/{name}', exist_ok=True)
for p in glob.glob(f'{OUT}/{MODEL}_run{RUN}*'):
    shutil.copy(p, f'/content/{name}/')
shutil.make_archive(f'/content/{name}', 'zip', f'/content/{name}')
files.download(f'/content/{name}.zip')
'''
    return _nb([_md(header), _code(PIP), _code(setup), _code(run_cell), _code(zip_cell)])


def render(nb: dict) -> str:
    return json.dumps(nb, ensure_ascii=False, indent=1) + "\n"


def expected() -> dict:
    return {TRAIN_NB: render(train_notebook()), EVAL_NB: render(eval_notebook())}


def main() -> int:
    for path, text in expected().items():
        path.write_text(text, encoding="utf-8")
        print(f"썼다: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
